"""Action gate across policy engines — the seam that had no coverage.

Before this file, no test combined ActionGate with a non-regex engine, and the
seam was broken: with CUSTOS_POLICY_ENGINE=opa or =hybrid, evaluate_action raised
AttributeError('OPAPolicyEngine' object has no attribute 'rules_digest') from the
citation path before it could decide anything. The suite stayed green because
nothing exercised the combination.

Two properties are asserted here, and the pre-registered sabotage class 011
(fabricate-citation) depends on them:

  1. The gate decides under every engine the factory can return. A configured
     engine must never turn an authorization decision into an exception.
  2. A citation exists only when it covers what the decision consulted. Under an
     unpinned OPA or hybrid engine the Rego rules cannot be hashed, so there is
     no honest digest, and the record must carry none rather than a digest over
     the smaller set the process can see.
"""
# Copyright (C) 2024-2026 Tavares Heath Sr. (doing business as FroLife Productions)
# Licensed under the GNU Affero General Public License v3.0 (AGPL-3.0)
# See LICENSE file for details. Commercial license available upon request.

import re

import pytest

from custos.action_gate import ActionGate, ActionRequest
from custos.policy_citation import engine_policy_digest, policy_digest
from custos.policy_engine import PolicyAction, PolicyRule
from custos.tenant import TenantManager

SHA256 = re.compile(r"^[0-9a-f]{64}$")
PIN_A = "a" * 64
PIN_B = "b" * 64


@pytest.fixture()
def gate_for(monkeypatch):
    """Build a gate whose tenant runs on the requested engine."""

    def build(engine: str, *, pin: str | None = None, opa_url: str | None = None) -> ActionGate:
        monkeypatch.setenv("CUSTOS_POLICY_ENGINE", engine)
        if pin is None:
            monkeypatch.delenv("CUSTOS_OPA_POLICY_DIGEST", raising=False)
        else:
            monkeypatch.setenv("CUSTOS_OPA_POLICY_DIGEST", pin)
        if opa_url is None:
            # Unreachable on purpose: the engines fail closed/fall back fast, and
            # these tests are about the gate's bookkeeping, not OPA's answers.
            monkeypatch.setenv("CUSTOS_OPA_URL", "http://127.0.0.1:9")
        else:
            monkeypatch.setenv("CUSTOS_OPA_URL", opa_url)
        gate = ActionGate(TenantManager())
        gate.register_tools("default", {"web_search"})
        return gate

    return build


def evaluate(gate: ActionGate):
    return gate.evaluate_action(
        "default", ActionRequest(tool="web_search", command="search Miami clerk records")
    )


class TestGateDecidesUnderEveryEngine:
    """Property 1: no configured engine may turn a decision into an exception."""

    @pytest.mark.parametrize("engine", ["regex", "opa", "hybrid"])
    def test_evaluate_returns_a_decision(self, gate_for, engine):
        gate = gate_for(engine)
        result = evaluate(gate)  # must not raise
        assert result.decision.action in (
            PolicyAction.ALLOW,
            PolicyAction.DENY,
            PolicyAction.AUDIT,
        )

    def test_bench_tenant_still_denies_on_every_engine(self, gate_for):
        """The reason opa/hybrid crashed matters: it crashed before this check."""
        for engine in ("regex", "opa", "hybrid"):
            gate = gate_for(engine)
            result = gate.evaluate_action("ghost", ActionRequest(tool="web_search"))
            assert result.decision.allowed is False
            assert result.decision.triggered_rule == "action_gate_unknown_tenant"

    def test_unallowlisted_tool_still_denies_on_every_engine(self, gate_for):
        for engine in ("regex", "opa", "hybrid"):
            gate = gate_for(engine)
            gate.register_tools("default", {"calculator"})
            result = gate.evaluate_action("default", ActionRequest(tool="web_search"))
            assert result.decision.allowed is False
            assert result.decision.triggered_rule == "action_gate_tool_not_allowlisted"


class TestCitationCoversWhatItCites:
    """Property 2: a digest exists only when every consulted source is hashed."""

    def test_regex_citation_is_unchanged_by_this_fix(self, gate_for):
        """Byte-compatibility: records emitted before the fix must re-verify."""
        gate = gate_for("regex")
        ctx = gate._tm.get("default")
        expected = policy_digest({"web_search"}, ctx.policy_engine.rules)
        assert gate.cited_policy_digest("default") == expected
        assert SHA256.match(expected)

    def test_opa_without_pin_cites_nothing(self, gate_for):
        gate = gate_for("opa")
        assert gate.cited_policy_digest("default") is None

    def test_hybrid_without_pin_cites_nothing(self, gate_for):
        gate = gate_for("hybrid")
        assert gate.cited_policy_digest("default") is None

    def test_opa_with_pin_cites_the_pin(self, gate_for):
        gate = gate_for("opa", pin=PIN_A)
        cited = gate.cited_policy_digest("default")
        assert cited and SHA256.match(cited)

    def test_rotating_the_pin_changes_the_citation(self, gate_for):
        first = gate_for("opa", pin=PIN_A).cited_policy_digest("default")
        second = gate_for("opa", pin=PIN_B).cited_policy_digest("default")
        assert first != second

    def test_pinned_opa_citation_is_not_the_regex_digest(self, gate_for):
        """If it matched, the engine would be invisible in the citation."""
        opa = gate_for("opa", pin=PIN_A)
        regex_digest = policy_digest({"web_search"}, opa._tm.get("default").policy_engine.citation_rules)
        assert opa.cited_policy_digest("default") != regex_digest

    def test_hybrid_pinned_differs_from_regex(self, gate_for):
        hybrid = gate_for("hybrid", pin=PIN_A)
        regex_gate = gate_for("regex")
        assert hybrid.cited_policy_digest("default") != regex_gate.cited_policy_digest("default")

    def test_malformed_pin_is_refused_not_hashed(self, gate_for):
        gate = gate_for("opa", pin="not-a-sha256")
        assert gate.cited_policy_digest("default") is None

    def test_engine_digest_helper_refuses_unpinned_non_regex(self):
        rule = PolicyRule(
            name="r", pattern="x", action=PolicyAction.DENY, reason="r"
        )
        assert engine_policy_digest({"t"}, [rule], "opa", None) is None
        assert engine_policy_digest({"t"}, [rule], "hybrid", "") is None
        assert engine_policy_digest({"t"}, [rule], "opa", PIN_A) is not None
        # The regex payload is untouched by the engine-aware branch.
        assert engine_policy_digest({"t"}, [rule], "regex", None) == policy_digest({"t"}, [rule])


class TestRecordCarriesTheCitationItClaims:
    """The citation must reach the record, not just the accessor."""

    def test_regex_record_cites_the_digest(self, gate_for):
        gate = gate_for("regex")
        expected = gate.cited_policy_digest("default")
        evaluate(gate)
        records = gate._tm.get("default").audit_chain.get_records()
        assert records[-1]["policy_digest"] == expected

    def test_opa_record_emits_no_citation_when_unpinned(self, gate_for):
        gate = gate_for("opa")
        evaluate(gate)
        records = gate._tm.get("default").audit_chain.get_records()
        assert records, "a decision must be recorded even when nothing is citable"
        assert records[-1]["policy_digest"] is None

    def test_pinned_opa_record_cites_the_pinned_digest(self, gate_for):
        gate = gate_for("opa", pin=PIN_A)
        expected = gate.cited_policy_digest("default")
        evaluate(gate)
        records = gate._tm.get("default").audit_chain.get_records()
        assert records[-1]["policy_digest"] == expected


class TestRequireBoundStillGovernsUncitableEngines:
    """CUSTOS_AUDIT_REQUIRE_BOUND=1 is how an operator refuses null citations."""

    def test_unpinned_opa_denies_and_keeps_its_own_reason(self, gate_for, monkeypatch):
        """OPA is unreachable here, so the deny predates the record; it stands."""
        monkeypatch.setenv("CUSTOS_AUDIT_REQUIRE_BOUND", "1")
        gate = gate_for("opa")
        result = evaluate(gate)
        assert result.decision.allowed is False
        assert result.decision.triggered_rule == "opa_unavailable", (
            "the store refusing a record must not rewrite why the action was denied"
        )

    def test_uncitable_allow_does_not_stand_under_require_bound(self, gate_for, monkeypatch):
        """Hybrid allows via regex fallback; the uncitable record must sink it."""
        monkeypatch.setenv("CUSTOS_AUDIT_REQUIRE_BOUND", "1")
        gate = gate_for("hybrid")
        result = evaluate(gate)
        assert result.decision.allowed is False
        assert result.decision.triggered_rule == "action_gate_record_unwritable"
        assert "No policy citation" in result.decision.reason


class TestUnrecordableDecisionIsNotAnAllow:
    """A decision nobody can re-walk is not evidence, so it is not an allow."""

    def test_broken_store_turns_an_allow_into_a_deny(self, gate_for):
        gate = gate_for("regex")

        def boom(**kwargs):
            raise OSError("audit backend unreachable")

        gate._tm.get("default").audit_chain.record = boom
        result = evaluate(gate)
        assert result.decision.allowed is False
        assert result.decision.triggered_rule == "action_gate_record_unwritable"

    def test_broken_store_leaves_a_deny_standing(self, gate_for):
        gate = gate_for("regex")
        gate.register_tools("default", {"calculator"})

        def boom(**kwargs):
            raise OSError("audit backend unreachable")

        gate._tm.get("default").audit_chain.record = boom
        result = gate.evaluate_action("default", ActionRequest(tool="web_search"))
        assert result.decision.allowed is False
        assert result.decision.triggered_rule == "action_gate_tool_not_allowlisted", (
            "the store failing must not rewrite the reason the decision was denied"
        )

    def test_broken_store_never_raises(self, gate_for):
        """An exception is not a decision, and a caller cannot act on one."""
        for engine in ("regex", "opa", "hybrid"):
            gate = gate_for(engine)

            def boom(**kwargs):
                raise OSError("audit backend unreachable")

            gate._tm.get("default").audit_chain.record = boom
            assert evaluate(gate).decision is not None
