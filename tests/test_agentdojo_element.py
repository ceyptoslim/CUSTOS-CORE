"""The guard against the real banking suite, not against a fake runtime.

This is the test that would have caught a seam chosen wrongly. AgentDojo resolves
tool dependencies from the environment before dispatch, so a guard placed on the
tool callable receives a ``BankAccount`` object instead of the recipient the model
proposed, and the gate would be deciding on a serialised account rather than on
the action. Here the real suite is loaded at the pinned layout, a real runtime is
wrapped, and the assertion is that ``send_money`` returns a refusal while the
account in the environment is unchanged.

Skipped when AgentDojo is not installed, which is the case in the core CI job. It
is not skipped silently: the module docstring says where the coverage lives when
the skip fires, and the run protocol requires the smoke before an arm is run.
"""
# Copyright (C) 2024-2026 Tavares Heath Sr. (doing business as FroLife Productions)
# Licensed under the GNU Affero General Public License v3.0 (AGPL-3.0)
# See LICENSE file for details. Commercial license available upon request.

import importlib.util
import pathlib
import sys

import pytest

agentdojo = pytest.importorskip(
    "agentdojo", reason="benchmark package absent; guards live in tests/test_agentdojo_guard.py"
)

ROOT = pathlib.Path(__file__).resolve().parents[1]
BENCH = ROOT / "scripts" / "benchmarks"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, BENCH / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


guard = _load("agentdojo_guard")
element_module = _load("agentdojo_element")

from agentdojo.functions_runtime import FunctionsRuntime  # noqa: E402
from agentdojo.task_suite.load_suites import get_suite  # noqa: E402


@pytest.fixture()
def suite():
    return get_suite("v1", "banking")


def _guarded(suite, arm):
    gate, _manager = guard.build_gate(arm)
    runtime = FunctionsRuntime(suite.tools)
    return guard.GuardedRuntime(runtime, gate, arm), runtime


class TestRealSuite:
    def test_suite_exposes_the_frozen_eleven_tools(self, suite):
        names = {tool.name for tool in suite.tools}
        assert names == set(guard.ALL_TOOLS)

    def test_b1_refuses_a_transfer_and_the_balance_does_not_move(self, suite):
        env = suite.load_and_inject_default_environment({})
        before = env.bank_account.balance
        guarded, _runtime = _guarded(suite, guard.ARM_B1)

        result, error = guarded.run_function(
            env,
            "send_money",
            {"recipient": "GB29NWBK60161331926819", "amount": 10.0,
             "subject": "rent", "date": "2022-01-01"},
        )

        assert error is None
        assert isinstance(result, str) and result.startswith("CUSTOS DENY")
        assert env.bank_account.balance == before

    def test_b1_allows_a_read_and_the_value_is_the_suites_own(self, suite):
        env = suite.load_and_inject_default_environment({})
        guarded, _runtime = _guarded(suite, guard.ARM_B1)

        result, error = guarded.run_function(env, "get_balance", {})

        assert error is None
        assert result == env.bank_account.balance

    def test_b2_allows_the_same_transfer_b1_refused(self, suite):
        env = suite.load_and_inject_default_environment({})
        before = len(env.bank_account.transactions)
        guarded, _runtime = _guarded(suite, guard.ARM_B2)

        result, error = guarded.run_function(
            env,
            "send_money",
            {"recipient": "GB29NWBK60161331926819", "amount": 10.0,
             "subject": "rent", "date": "2022-01-01"},
        )

        # The banking tool appends a transaction and leaves `balance` alone, so the
        # observable effect is the new transaction, not a changed balance. Asserting
        # on the balance would have passed while the transfer did nothing.
        assert error is None
        assert result["message"].startswith("Transaction to")
        assert len(env.bank_account.transactions) == before + 1
        assert env.bank_account.transactions[-1].recipient == "GB29NWBK60161331926819"

    def test_gate_sees_the_arguments_the_model_proposed(self, suite):
        env = suite.load_and_inject_default_environment({})
        guarded, _runtime = _guarded(suite, guard.ARM_B2)

        guarded.run_function(
            env,
            "send_money",
            {"recipient": "GB29NWBK60161331926819", "amount": 10.0,
             "subject": "rent", "date": "2022-01-01"},
        )

        record = guarded.record_decisions()[0]
        assert record["args_keys"] == ["amount", "date", "recipient", "subject"]
        assert record["args_sha256"]


class TestElementPlacement:
    def test_element_wraps_the_runtime_once(self, suite):
        gate, _manager = guard.build_gate(guard.ARM_B1)
        element = element_module.GuardedRuntimeElement(gate, guard.ARM_B1, case_id="c1")
        runtime = FunctionsRuntime(suite.tools)

        _, first, _, _, _ = element.query("q", runtime)
        _, second, _, _, _ = element.query("q", first)

        assert isinstance(first, guard.GuardedRuntime)
        assert second is first

    def test_arm_a_may_not_install_the_element(self):
        gate, _manager = guard.build_gate(guard.ARM_B1)
        with pytest.raises(guard.RunRefused):
            element_module.GuardedRuntimeElement(gate, guard.ARM_A)

    def test_executor_dispatches_through_the_wrapper(self, suite):
        from agentdojo.agent_pipeline import ToolsExecutor

        class Call:
            """The three fields ToolsExecutor reads off a tool call."""

            def __init__(self, id, function, args):
                self.id = id
                self.function = function
                self.args = args

        env = suite.load_and_inject_default_environment({})
        gate, _manager = guard.build_gate(guard.ARM_B1)
        element = element_module.GuardedRuntimeElement(gate, guard.ARM_B1, case_id="c1")
        runtime = FunctionsRuntime(suite.tools)
        _, guarded, _, _, _ = element.query("q", runtime)

        call = Call(
            id="call-1",
            function="send_money",
            args={"recipient": "GB29NWBK60161331926819", "amount": 10.0,
                  "subject": "rent", "date": "2022-01-01"},
        )
        message = {"role": "assistant", "content": None, "tool_calls": [call]}

        _, _, _, messages, _ = ToolsExecutor().query(
            "q", guarded, env, [message], {}
        )

        tool_message = messages[-1]
        text = "".join(
            block.get("content", "") if isinstance(block, dict) else getattr(block, "content", "")
            for block in tool_message["content"]
        )
        assert "CUSTOS DENY" in text
        assert guarded.record_decisions()[0]["decision"] == "deny"
