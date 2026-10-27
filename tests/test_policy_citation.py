"""Policy-commit citation at emission — enforcement tests.

Design: docs/design/policy-commit-citation.md (R1-R5). The pre-registered
sabotage class 005 (weaken-citation) depends on these assertions: a
deliberate weakening of the citation binding must turn the suite red.
"""
# Copyright (C) 2024-2026 FroLife Productions
# Licensed under the GNU Affero General Public License v3.0 (AGPL-3.0)
# See LICENSE file for details. Commercial license available upon request.

import json

import pytest

from custos.action_gate import ActionGate, ActionRequest
from custos.audit import AuditChain
from custos.custody import (
    AnchorManager,
    MemorySink,
    PolicyCommitRecord,
    verify_custody,
)
from custos.policy_citation import (
    canonical_policy_bytes,
    empty_policy_digest,
    policy_digest,
)
from custos.policy_engine import PolicyAction, PolicyRule


def _rule(name="rule_a", pattern="forbidden", action=PolicyAction.DENY):
    return PolicyRule(name=name, pattern=pattern, action=action, reason="test rule")


class TestCanonicalDigest:
    """R1 — exactly one canonical representation per policy set."""

    def test_digest_deterministic_and_order_insensitive(self):
        tools = {"brave_search", "http_post"}
        rules = [_rule(), _rule("rule_b", "secret")]
        d1 = policy_digest(tools, rules)
        d2 = policy_digest(set(sorted(tools, reverse=True)), list(reversed(rules)))
        assert d1 == d2

    def test_semantic_change_changes_digest(self):
        d1 = policy_digest({"tool_a"}, [_rule()])
        d2 = policy_digest({"tool_a", "tool_b"}, [_rule()])
        d3 = policy_digest({"tool_a"}, [_rule(pattern="other")])
        assert d1 != d2 != d3

    def test_empty_policy_digest_is_stable(self):
        assert empty_policy_digest() == policy_digest(set(), [])
        assert empty_policy_digest() == policy_digest([], [])


class TestCitationAtEmission:
    """R2 — every emitted record cites the in-force policy digest."""

    def _gate(self, tenant="t1", tools=None, rules=None):
        chain = AuditChain()

        class _Engine:
            def __init__(self, rules):
                self._rs = list(rules or [])
                self._rdc = None

            @property
            def rules(self):
                return list(self._rs)

            @property
            def rules_digest(self):
                from custos.policy_citation import rules_canonical_digest
                if self._rdc is None:
                    self._rdc = rules_canonical_digest(self._rs)
                return self._rdc

            def add_rule(self, rule):
                self._rs.append(rule)
                self._rdc = None

        ctx = type("C", (), {})()
        ctx.audit_chain = chain
        ctx.policy_engine = _Engine(rules)

        class _TM:
            def get_strict(self, tenant_id):
                return ctx if tenant_id == tenant else None

        gate = ActionGate(_TM())
        gate._tool_allowlists[tenant] = set(tools or [])
        return gate, chain, ctx

    def _evaluate(self, gate, ctx, tenant="t1"):
        action = ActionRequest(tool="some_tool", command="do the thing")
        return gate.evaluate_action(tenant, action, client_id="agent")

    def test_record_cites_in_force_policy_digest(self):
        """THE pre-registered assertion for sabotage class 005.

        A record emitted after a mid-stream policy change must cite the
        NEW in-force digest — a stale snapshot digest must fail here.
        """
        gate, chain, ctx = self._gate(tools={"tool_a"})
        self._evaluate(gate, ctx)
        expected = policy_digest({"tool_a"}, [])
        assert chain._records[0].policy_digest == expected

        # Mid-stream policy change: next record must cite the new digest.
        gate.register_tools("t1", {"tool_a", "tool_b"})
        self._evaluate(gate, ctx)
        expected2 = policy_digest({"tool_a", "tool_b"}, [])
        assert chain._records[1].policy_digest == expected2
        assert chain._records[1].policy_digest != chain._records[0].policy_digest

    def test_rule_change_also_changes_citation(self):
        rules = [_rule()]
        gate, chain, ctx = self._gate(tools={"tool_a"}, rules=rules)
        self._evaluate(gate, ctx)
        d1 = chain._records[0].policy_digest
        ctx.policy_engine.add_rule(_rule("rule_z", "extra"))
        self._evaluate(gate, ctx)
        assert chain._records[1].policy_digest != d1

    def test_policy_digest_is_covered_by_record_hash(self):
        """Tampering the citation after emission must break verify()."""
        gate, chain, ctx = self._gate(tools={"tool_a"})
        self._evaluate(gate, ctx)
        ok, _ = chain.verify()
        assert ok
        chain._records[0].policy_digest = "f" * 64
        ok, msg = chain.verify()
        assert not ok, "tampered citation must break the chain verify"

    def test_legacy_records_verify_unchanged(self):
        """Records without citation hash byte-identically to the old preimage."""
        chain = AuditChain()
        chain.record("client", "ALLOW", "reason", "content")
        ok, msg = chain.verify()
        assert ok
        assert chain._records[0].policy_digest is None


class TestPolicyCommitAnchoring:
    """R3/R4 — policy commits anchored to custody sinks; membership re-walk."""

    def _manager(self, sink=None):
        sink = sink or MemorySink()
        mgr = AnchorManager([sink], lambda: {}, anchor_n=999)
        return mgr, sink

    def _commit_dicts(self, sink):
        return [a.to_dict() for a in sink.anchors]

    def test_gate_anchors_new_digests_to_sinks(self):
        gate, chain, ctx = TestCitationAtEmission()._gate(tools={"tool_a"})
        mgr, sink = self._manager()
        gate.set_custody(mgr)
        gate._maybe_anchor_policy_commit(
            "t1", ctx, policy_digest({"tool_a"}, [])
        )
        mgr.drain_policy_commits()
        assert len(sink.anchors) == 1
        commit = sink.anchors[0]
        assert isinstance(commit, PolicyCommitRecord)
        assert commit.kind == "policy_commit"
        assert commit.head_hash == policy_digest({"tool_a"}, [])
        import hashlib as h
        assert (
            h.sha256(commit.canonical_json.encode()).hexdigest()
            == commit.head_hash
        )

    def test_no_reanchor_for_unchanged_digest(self):
        gate, chain, ctx = TestCitationAtEmission()._gate(tools={"tool_a"})
        mgr, sink = self._manager()
        gate.set_custody(mgr)
        dg = policy_digest({"tool_a"}, [])
        gate._maybe_anchor_policy_commit("t1", ctx, dg)
        mgr.drain_policy_commits()
        gate._maybe_anchor_policy_commit("t1", ctx, dg)
        mgr.drain_policy_commits()
        assert len(sink.anchors) == 1

    def test_verify_established_on_anchored_citation(self):
        gate, chain, ctx = TestCitationAtEmission()._gate(tools={"tool_a"})
        mgr, sink = self._manager()
        gate.set_custody(mgr)
        TestCitationAtEmission()._evaluate(gate, ctx)
        records = [r.to_dict() for r in chain._records]
        result = verify_custody(records, self._commit_dicts(sink))
        assert result["verdicts"]["P5_policy_commit_integrity"] == "ESTABLISHED"
        assert result["verdicts"]["P6_citation_membership"] == "ESTABLISHED"

    def test_unanchored_citation_contradicts(self):
        """R4 — a record citing a never-anchored digest is a provenance gap."""
        gate, chain, ctx = TestCitationAtEmission()._gate(tools={"tool_a"})
        mgr, sink = self._manager()
        # custody attached but sink failing: commit cannot land
        sink.fail(True)
        gate.set_custody(mgr)
        TestCitationAtEmission()._evaluate(gate, ctx)
        records = [r.to_dict() for r in chain._records]
        result = verify_custody(records, self._commit_dicts(sink))
        assert result["verdicts"]["P6_citation_membership"] == "CONTRADICTION"
        assert result["overall"] == "CONTRADICTION"

    def test_tampered_canonical_json_contradicts(self):
        mgr, sink = self._manager()
        canonical = canonical_policy_bytes({"tool_a"}, []).decode()
        dg = policy_digest({"tool_a"}, [])
        mgr.anchor_policy_commit("t1", dg, canonical)
        mgr.drain_policy_commits()
        dicts = self._commit_dicts(sink)
        dicts[0]["canonical_json"] = canonical.replace("tool_a", "tool_EVIL")
        records = [
            {
                "timestamp": 1.0,
                "client_id": "t1",
                "action": "ALLOW",
                "triggered_rule": None,
                "reason": "r",
                "content_hash": "c",
                "previous_hash": "0" * 64,
                "record_hash": "0" * 64,
                "policy_digest": dg,
                "tenant_id": "t1",
            }
        ]
        result = verify_custody(records, dicts)
        assert result["verdicts"]["P5_policy_commit_integrity"] == "CONTRADICTION"

    def test_absent_dimension_adds_no_keys(self):
        """R5 — legacy stores keep their verdicts untouched."""
        chain = AuditChain()
        chain.record("client", "ALLOW", "reason", "content")
        mgr, sink = self._manager()
        records = [r.to_dict() for r in chain._records]
        result = verify_custody(records, self._commit_dicts(sink))
        assert "P5_policy_commit_integrity" not in result["verdicts"]
        assert "P6_citation_membership" not in result["verdicts"]
