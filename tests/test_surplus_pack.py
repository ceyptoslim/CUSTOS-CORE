"""
Surplus-Recovery Outreach Policy Pack — tests.

Covers: every rule group, the fail-closed statute gate (empty registry denies
ALL citations), verified-statute pass-through, pack-not-loaded fail-closed,
and composition with the existing TenantManager/persistence components.
"""
# Copyright (C) 2024-2026 FroLife Productions
# Licensed under the GNU Affero General Public License v3.0 (AGPL-3.0)
# See LICENSE file for details. Commercial license available upon request.

import json

import pytest

from custos.policy_engine import PolicyAction
from custos.tenant import TenantManager
from packs.surplus_recovery import (
    DEFAULT_TENANT_ID,
    evaluate_outreach,
    find_unverified_citations,
    load_pack,
    load_verified_statutes,
    pack_rules,
)


@pytest.fixture()
def tm():
    manager = TenantManager()
    load_pack(manager)
    return manager


CLEAN_LETTER = (
    "Dear Property Owner,\n\n"
    "Our records indicate that a tax deed sale of a property associated with "
    "you resulted in surplus funds held by the county. You may be entitled to "
    "claim these funds. We would like to speak with you about the claim "
    "process. Please contact us at your convenience.\n\n"
    "We encourage you to consult your own attorney about your options.\n\n"
    "Sincerely,\nFroLife Productions"
)


class TestPackRules:
    def test_pack_exposes_four_rules(self):
        rules = pack_rules()
        assert len(rules) == 4
        assert all(r.pattern for r in rules)

    def test_rules_compose_existing_engine(self, tm):
        ctx = tm.get_strict(DEFAULT_TENANT_ID)
        assert ctx is not None
        bare = TenantManager().get_strict("default")
        assert ctx.policy_engine.rule_count == bare.policy_engine.rule_count + len(pack_rules())


class TestGuaranteeLanguage:
    @pytest.mark.parametrize(
        "phrase",
        [
            "This is a guaranteed recovery.",
            "It is completely risk-free.",
            "There is no risk to you.",
            "We offer 100% success.",
        ],
    )
    def test_guarantees_denied(self, tm, phrase):
        result = evaluate_outreach(tm, CLEAN_LETTER + " " + phrase)
        assert result.allowed is False
        assert result.triggered_rule == "surplus_guarantee_language"


class TestUPLRisk:
    @pytest.mark.parametrize(
        "phrase",
        [
            "This letter is legal advice.",
            "I am an attorney and can help.",
            "We are a law firm.",
            "We can represent you in court.",
        ],
    )
    def test_upl_denied(self, tm, phrase):
        result = evaluate_outreach(tm, CLEAN_LETTER + " " + phrase)
        assert result.allowed is False
        assert result.triggered_rule == "surplus_upl_risk"

    def test_consult_own_attorney_is_allowed(self, tm):
        result = evaluate_outreach(tm, CLEAN_LETTER)
        assert result.allowed is True
        assert result.triggered_rule is None


class TestPredatoryUrgency:
    @pytest.mark.parametrize(
        "phrase",
        [
            "Act now to claim your funds.",
            "This is a final notice.",
            "This is your last chance.",
            "Act immediately or you'll lose everything.",
        ],
    )
    def test_urgency_denied(self, tm, phrase):
        result = evaluate_outreach(tm, CLEAN_LETTER + " " + phrase)
        assert result.allowed is False
        assert result.triggered_rule == "surplus_predatory_urgency"


class TestFeeAudit:
    def test_fee_percentage_flags_for_review(self, tm):
        result = evaluate_outreach(tm, CLEAN_LETTER + " Our fee is 33% of recovered funds.")
        assert result.allowed is True  # AUDIT = allowed, flagged for owner review
        assert result.action == PolicyAction.AUDIT
        assert result.triggered_rule == "surplus_fee_structure"


class TestStatuteGateFailClosed:
    @pytest.mark.parametrize(
        "citation",
        [
            "Under s. 197.582 you may claim the surplus.",
            "Per F.S. 197.582 the funds are held by the clerk.",
            "As stated in Fla. Stat. § 201.582, ...",
            "Section 197.582 governs disbursement.",
            "Statute 197.582 applies. Sec. 197.582 controls. § 197.582 governs.",
        ],
    )
    def test_any_citation_denied_with_empty_registry(self, tm, citation):
        result = evaluate_outreach(tm, CLEAN_LETTER + " " + citation)
        assert result.allowed is False
        assert result.triggered_rule == "surplus_statute_gate"
        assert "197.582" in result.reason or "201.582" in result.reason

    def test_registry_ships_empty(self):
        registry = load_verified_statutes()
        assert registry == {}

    def test_registry_missing_file_fails_closed(self, tmp_path):
        registry = load_verified_statutes(tmp_path / "does_not_exist.json")
        assert registry == {}

    def test_registry_malformed_fails_closed(self, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text("{ not json", encoding="utf-8")
        assert load_verified_statutes(bad) == {}

    def test_verified_statute_passes_gate(self, tm):
        registry = {"197.582": {"title": "Owner-verified", "verified_date": "2026-09-05"}}
        letter = CLEAN_LETTER + " Under s. 197.582 you may be entitled to these funds."
        result = evaluate_outreach(tm, letter, registry=registry)
        assert result.allowed is True
        assert result.triggered_rule != "surplus_statute_gate"

    def test_unknown_statute_denied_even_with_populated_registry(self, tm):
        registry = {"197.582": {"title": "Owner-verified", "verified_date": "2026-09-05"}}
        letter = CLEAN_LETTER + " Under s. 999.999 you may be entitled to these funds."
        result = evaluate_outreach(tm, letter, registry=registry)
        assert result.allowed is False
        assert result.triggered_rule == "surplus_statute_gate"
        assert "999.999" in result.reason

    def test_find_unverified_citations_lists_each_once(self):
        text = "s. 197.582 and F.S. 197.582 and s. 999.999"
        assert find_unverified_citations(text, registry={"197.582": {}}) == ["999.999"]


class TestFailClosedComposition:
    def test_pack_not_loaded_denies(self):
        manager = TenantManager()  # pack NOT loaded
        result = evaluate_outreach(manager, CLEAN_LETTER)
        assert result.allowed is False
        assert result.triggered_rule == "surplus_pack_not_loaded"

    def test_load_pack_persists_rules_via_store(self, tmp_path):
        from custos.policy_store import PolicyStore

        store_dir = tmp_path / "store"
        manager = TenantManager(policy_store=PolicyStore(str(store_dir)))
        load_pack(manager)
        persisted = manager.list_policy_rules(DEFAULT_TENANT_ID)
        assert [r.name for r in persisted] == [r.name for r in pack_rules()]

    def test_registry_json_is_valid_with_empty_florida_map(self, tmp_path):
        from packs.surplus_recovery import DEFAULT_REGISTRY_PATH

        data = json.loads(DEFAULT_REGISTRY_PATH.read_text(encoding="utf-8"))
        assert data["florida"] == {}
        assert "OWNER-POPULATED" in data["_instructions"]
