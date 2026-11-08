"""The AgentDojo guard holds the frozen design, not a plausible one.

Three separate claims are guarded here.

The first is the seam: a denied call must leave the tool unexecuted and the
environment untouched, because a task that did not happen scores differently from
a task that happened differently, and the benchmark's native scorer cannot tell
the difference on its own.

The second is the allowlist partition. The pre-registration's whole prediction
rests on which six tools are read-only, so the sets are asserted literally. A tool
added to the banking suite at a later pin fails here rather than drifting into
whichever set a rule would have picked.

The third is the binding between this code and the document that governs it. The
freeze commit and both recorded hashes must still appear in
``docs/benchmark/agentdojo-prereg-v1.md``, and the case list on disk must still
hash to the frozen value. A guard that can be silently re-pointed at a new
document is decoration.

Nothing here needs AgentDojo, a provider key or a network. The integration smoke
in ``tests/test_agentdojo_element.py`` covers the real pipeline and skips when the
benchmark package is absent, which is the case in CI.
"""
# Copyright (C) 2024-2026 Tavares Heath Sr. (doing business as FroLife Productions)
# Licensed under the GNU Affero General Public License v3.0 (AGPL-3.0)
# See LICENSE file for details. Commercial license available upon request.

import importlib.util
import json
import pathlib
import shutil
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "benchmarks" / "agentdojo_guard.py"
PREREG_DOC = ROOT / "docs" / "benchmark" / "agentdojo-prereg-v1.md"
CASE_LIST = ROOT / "docs" / "benchmark" / "case-list-v1.txt"


def _load_guard():
    spec = importlib.util.spec_from_file_location("agentdojo_guard_under_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    # Registered before exec because the module defines dataclasses under
    # `from __future__ import annotations`: the dataclass machinery resolves the
    # defining module through sys.modules and fails on an unregistered one.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


guard = _load_guard()


class FakeRuntime:
    """A stand-in for FunctionsRuntime that counts what actually ran."""

    def __init__(self, results=None):
        self.calls = []
        self.results = results or {}

    def run_function(self, env, function, kwargs, raise_on_error=False):
        self.calls.append((function, dict(kwargs)))
        if function in self.results:
            return self.results[function], None
        return f"ran {function}", None


class TestToolPartition:
    def test_read_only_set_is_literal(self):
        assert guard.READ_ONLY_TOOLS == {
            "get_iban",
            "get_balance",
            "get_most_recent_transactions",
            "get_scheduled_transactions",
            "read_file",
            "get_user_info",
        }

    def test_mutating_set_is_literal(self):
        assert guard.MUTATING_TOOLS == {
            "send_money",
            "schedule_transaction",
            "update_scheduled_transaction",
            "update_password",
            "update_user_info",
        }

    def test_partition_is_disjoint_and_complete(self):
        assert not (guard.READ_ONLY_TOOLS & guard.MUTATING_TOOLS)
        assert len(guard.ALL_TOOLS) == 11

    def test_arms_use_the_frozen_allowlists(self):
        assert guard.ARM_ALLOWLISTS[guard.ARM_A] == frozenset()
        assert guard.ARM_ALLOWLISTS[guard.ARM_B1] == guard.READ_ONLY_TOOLS
        assert guard.ARM_ALLOWLISTS[guard.ARM_B2] == guard.ALL_TOOLS

    def test_gate_is_registered_with_the_arm_allowlist_only(self):
        gate, _manager = guard.build_gate(guard.ARM_B1)
        assert gate.list_tools(guard.TENANT_ID) == set(guard.READ_ONLY_TOOLS)


class TestDeniedCallLeavesNoEffect:
    def test_mutating_tool_is_not_executed_under_b1(self):
        runtime = FakeRuntime()
        gate, _ = guard.build_gate(guard.ARM_B1)
        guarded = guard.GuardedRuntime(runtime, gate, guard.ARM_B1, case_id="c1")

        result, error = guarded.run_function(
            None, "send_money", {"recipient": "GB00", "amount": 98.7}
        )

        assert runtime.calls == []
        assert error is None
        assert result.startswith("CUSTOS DENY: tool 'send_money'")
        assert "action_gate_tool_not_allowlisted" in result
        assert result.endswith("No effect was applied.")

    def test_read_only_tool_runs_under_b1(self):
        runtime = FakeRuntime({"get_balance": 100.0})
        gate, _ = guard.build_gate(guard.ARM_B1)
        guarded = guard.GuardedRuntime(runtime, gate, guard.ARM_B1)

        result, error = guarded.run_function(None, "get_balance", {})

        assert result == 100.0
        assert error is None
        assert runtime.calls == [("get_balance", {})]

    def test_b2_executes_the_same_mutation_b1_refused(self):
        runtime = FakeRuntime()
        gate, _ = guard.build_gate(guard.ARM_B2)
        guarded = guard.GuardedRuntime(runtime, gate, guard.ARM_B2)

        result, _ = guarded.run_function(None, "send_money", {"recipient": "GB00"})

        assert result == "ran send_money"
        assert runtime.calls == [("send_money", {"recipient": "GB00"})]

    def test_unknown_tool_takes_the_harness_error_path(self):
        runtime = FakeRuntime()
        gate, _ = guard.build_gate(guard.ARM_B1)
        guarded = guard.GuardedRuntime(runtime, gate, guard.ARM_B1)

        result, _ = guarded.run_function(None, "not_a_tool", {})

        assert result == "ran not_a_tool"
        assert guarded.records == []


class TestDecisionRecord:
    def test_one_record_per_gated_call(self):
        runtime = FakeRuntime()
        gate, _ = guard.build_gate(guard.ARM_B1)
        guarded = guard.GuardedRuntime(runtime, gate, guard.ARM_B1, case_id="UserTask0:InjectionTask0")

        guarded.run_function(None, "get_balance", {})
        guarded.run_function(None, "send_money", {"amount": 5})

        rows = guarded.record_decisions()
        assert len(rows) == 2
        assert rows[0]["decision"] == "allow"
        assert rows[1]["decision"] == "deny"
        assert rows[1]["triggered_rule"] == "action_gate_tool_not_allowlisted"
        assert rows[0]["case_id"] == "UserTask0:InjectionTask0"
        assert rows[0]["arm"] == guard.ARM_B1

    def test_record_carries_the_argument_digest_not_the_arguments(self):
        runtime = FakeRuntime()
        gate, _ = guard.build_gate(guard.ARM_B2)
        guarded = guard.GuardedRuntime(runtime, gate, guard.ARM_B2)

        guarded.run_function(None, "send_money", {"recipient": "GB00", "amount": 1.0})
        guarded.run_function(None, "send_money", {"recipient": "XX99", "amount": 1.0})

        first, second = guarded.record_decisions()
        assert first["args_keys"] == ["amount", "recipient"]
        assert len(first["args_sha256"]) == 64
        # Different recipient, same shape: the digest must move, which is how a
        # reader knows the arguments reached the gate rather than just its name.
        assert first["args_sha256"] != second["args_sha256"]
        # Key names are kept on purpose so a reader can see what was evaluated;
        # the values are not, which is what the digest is for.
        assert "GB00" not in json.dumps(first)

    def test_sink_receives_every_decision(self):
        seen = []
        runtime = FakeRuntime()
        gate, _ = guard.build_gate(guard.ARM_B1)
        guarded = guard.GuardedRuntime(runtime, gate, guard.ARM_B1, sink=seen.append)

        guarded.run_function(None, "get_balance", {})
        guarded.run_function(None, "send_money", {})

        assert [r.decision for r in seen] == ["allow", "deny"]

    def test_arm_a_cannot_be_wrapped(self):
        gate, _ = guard.build_gate(guard.ARM_B1)
        with pytest.raises(guard.RunRefused):
            guard.GuardedRuntime(FakeRuntime(), gate, guard.ARM_A)

    def test_unknown_arm_is_refused(self):
        with pytest.raises(guard.RunRefused):
            guard.build_gate("B3")


class TestFrozenBindings:
    def test_case_list_still_hashes_to_the_frozen_value(self):
        cases = guard.verify_case_list(CASE_LIST)
        assert len(cases) == 144
        assert cases[0] == "UserTask0:InjectionTask0"
        assert cases[-1] == "UserTask15:InjectionTask8"

    def test_a_changed_case_list_is_refused(self, tmp_path):
        copy = tmp_path / "case-list.txt"
        shutil.copyfile(CASE_LIST, copy)
        copy.write_text(copy.read_text().replace("UserTask0:InjectionTask0", "UserTask0:InjectionTask9"))
        with pytest.raises(guard.CaseListDrift):
            guard.verify_case_list(copy)

    def test_freeze_identifiers_are_still_in_the_pre_registration(self):
        text = PREREG_DOC.read_text()
        assert guard.FROZEN_PREREG_COMMIT in text
        assert guard.FROZEN_CASE_LIST_SHA256 in text
        assert guard.FROZEN_CASE_LIST_ENUMERATION_SHA256 in text
        assert guard.FROZEN_MODEL_ID in text


class TestRunConfigurationRefusals:
    def _config(self, tmp_path, **overrides):
        values = {
            "arm": guard.ARM_B1,
            "model": guard.FROZEN_MODEL_ID,
            "attack": "important_instructions",
            "case_list": CASE_LIST,
            "out_dir": tmp_path,
        }
        values.update(overrides)
        return guard.ArmConfig(**values)

    def test_frozen_configuration_passes(self, tmp_path):
        assert self._config(tmp_path).validate() == []

    def test_model_alias_is_refused(self, tmp_path):
        problems = self._config(tmp_path, model=guard.FORBIDDEN_MODEL_ALIAS).validate()
        assert problems and "alias" in problems[0]

    def test_other_model_is_refused(self, tmp_path):
        problems = self._config(tmp_path, model="gpt-4.1").validate()
        assert problems and "frozen snapshot" in problems[0]

    def test_undeclared_attack_is_refused(self, tmp_path):
        problems = self._config(tmp_path, attack="").validate()
        assert problems and "attack is not declared" in problems[0]

    def test_unknown_arm_is_refused(self, tmp_path):
        problems = self._config(tmp_path, arm="C").validate()
        assert problems and "unknown arm" in problems[0]
