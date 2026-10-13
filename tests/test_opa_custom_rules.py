"""
Regression tests (Oct 2026): OPA engine must actually enforce custom rules.

Before this fix, OPAPolicyEngine.add_rule() was a warn-and-ignore no-op —
tenant rules persisted through the PolicyStore were silently unenforced
whenever CUSTOS_POLICY_ENGINE=opa. Worse, evaluate_with_metadata() still
carried the DENY->ALLOW co-fire bug that evaluate() had already fixed.

Semantics under test:
- custom DENY is terminal (OPA is never even consulted)
- custom AUDIT downgrades an OPA allow to AUDIT
- custom rules can never loosen an OPA deny
- rule_count reflects locally enforced rules
- evaluate_with_metadata() is deny-terminal, identical to evaluate()
"""
# Copyright (C) 2024-2026 FroLife Productions
# Licensed under the GNU Affero General Public License v3.0 (AGPL-3.0)

from unittest.mock import MagicMock, patch

from custos.opa_engine import OPAPolicyEngine
from custos.policy_engine import PolicyAction, PolicyRule


def mock_opa_response(allow=True, deny=None, triggered_rule=None, audit=False):
    return {
        "result": {
            "allow": allow,
            "deny": deny or [],
            "triggered_rule": triggered_rule,
            "audit": audit,
        }
    }


def make_mock_client(response_json=None, status_code=200, raise_error=None):
    mock_client = MagicMock()
    mock_instance = MagicMock()
    mock_instance.__enter__ = MagicMock(return_value=mock_instance)
    mock_instance.__exit__ = MagicMock(return_value=False)

    if raise_error:
        mock_instance.post = MagicMock(side_effect=raise_error)
    else:
        mock_response = MagicMock()
        mock_response.status_code = status_code
        mock_response.raise_for_status = MagicMock()
        mock_response.json = MagicMock(return_value=response_json)
        mock_instance.post = MagicMock(return_value=mock_response)

    mock_client.return_value = mock_instance
    return mock_client


CUSTOM_DENY = PolicyRule(
    name="custom_no_project_codenames",
    pattern=r"(?i)project\s+midnight",
    action=PolicyAction.DENY,
    reason="Internal codename blocked by tenant rule",
)

CUSTOM_AUDIT = PolicyRule(
    name="custom_audit_salaries",
    pattern=r"(?i)salary",
    action=PolicyAction.AUDIT,
    reason="Compensation discussions must be audited",
)


class TestOPACustomRulesEnforced:
    """add_rule() must enforce, not warn-and-ignore."""

    def test_custom_deny_blocks_even_when_opa_allows(self):
        engine = OPAPolicyEngine(opa_url="http://test:8181")
        engine.add_rule(CUSTOM_DENY)
        mock = make_mock_client(mock_opa_response(allow=True))
        with patch("custos.opa_engine.httpx.Client", mock):
            result = engine.evaluate("Let's talk about Project Midnight")
        assert result.allowed is False
        assert result.action == PolicyAction.DENY
        assert result.triggered_rule == "custom_no_project_codenames"

    def test_custom_deny_never_consults_opa(self):
        """A terminal custom deny must not even reach the OPA server."""
        engine = OPAPolicyEngine(opa_url="http://test:8181")
        engine.add_rule(CUSTOM_DENY)
        mock = make_mock_client(mock_opa_response(allow=True))
        with patch("custos.opa_engine.httpx.Client", mock):
            engine.evaluate("Project Midnight again")
        assert mock.return_value.post.call_count == 0

    def test_custom_audit_downgrades_opa_allow(self):
        engine = OPAPolicyEngine(opa_url="http://test:8181")
        engine.add_rule(CUSTOM_AUDIT)
        mock = make_mock_client(mock_opa_response(allow=True))
        with patch("custos.opa_engine.httpx.Client", mock):
            result = engine.evaluate("His salary is public record")
        assert result.allowed is True
        assert result.action == PolicyAction.AUDIT
        assert result.triggered_rule == "custom_audit_salaries"

    def test_custom_rules_cannot_loosen_opa_deny(self):
        engine = OPAPolicyEngine(opa_url="http://test:8181")
        engine.add_rule(CUSTOM_DENY)
        engine.add_rule(CUSTOM_AUDIT)
        mock = make_mock_client(
            mock_opa_response(allow=False, deny=["SSN pattern detected"],
                              triggered_rule="block_pii_ssn")
        )
        with patch("custos.opa_engine.httpx.Client", mock):
            result = engine.evaluate("SSN: 123-45-6789 salary")
        assert result.allowed is False
        assert result.action == PolicyAction.DENY

    def test_rule_count_reflects_custom_rules(self):
        engine = OPAPolicyEngine(opa_url="http://test:8181")
        assert engine.rule_count == 0
        engine.add_rule(CUSTOM_DENY)
        engine.add_rule(CUSTOM_AUDIT)
        assert engine.rule_count == 2

    def test_metadata_path_enforces_custom_deny(self):
        engine = OPAPolicyEngine(opa_url="http://test:8181")
        engine.add_rule(CUSTOM_DENY)
        mock = make_mock_client(mock_opa_response(allow=True))
        with patch("custos.opa_engine.httpx.Client", mock):
            result = engine.evaluate_with_metadata(
                "Project Midnight in metadata path", client_id="t1"
            )
        assert result.allowed is False
        assert result.triggered_rule == "custom_no_project_codenames"


class TestMetadataPathCoFire:
    """evaluate_with_metadata must be deny-terminal exactly like evaluate()."""

    def test_metadata_deny_with_audit_flag_still_denies(self):
        """The co-fire bypass (deny + audit -> ALLOW) must not exist here."""
        engine = OPAPolicyEngine(opa_url="http://test:8181")
        mock = make_mock_client(
            mock_opa_response(
                allow=False,
                deny=["SSN pattern detected"],
                triggered_rule="block_pii_ssn",
                audit=True,
            )
        )
        with patch("custos.opa_engine.httpx.Client", mock):
            result = engine.evaluate_with_metadata(
                "SSN: 123-45-6789 and my password is hunter2",
                client_id="t1",
            )
        assert result.allowed is False
        assert result.action == PolicyAction.DENY
        assert "audit flag also set" in result.reason


class TestTenantOPACustomRules:
    """The tenant manager + policy factory path must enforce custom rules
    on the OPA engine — this is the exact silent-loss scenario."""

    def test_tenant_add_policy_rule_enforced_on_opa_engine(
        self, monkeypatch
    ):
        monkeypatch.setenv("CUSTOS_POLICY_ENGINE", "opa")
        from custos.policy_factory import create_policy_engine
        from custos.tenant import TenantConfig, TenantManager

        engine = create_policy_engine()
        assert type(engine).__name__ == "OPAPolicyEngine"

        manager = TenantManager()
        manager.register(
            "t-opa-custom",
            TenantConfig(tenant_id="t-opa-custom"),
        )
        # Same PolicyRule the /v1/tenants/{id}/policy route builds
        # from a PolicyRuleRequest before calling add_policy_rule().
        rule = PolicyRule(
            name="custom_block_codenames",
            pattern=r"(?i)project\s+midnight",
            action=PolicyAction.DENY,
            reason="Tenant rule",
        )
        manager.add_policy_rule("t-opa-custom", rule)

        mock = make_mock_client(mock_opa_response(allow=True))
        with patch("custos.opa_engine.httpx.Client", mock):
            ctx = manager.get_or_default("t-opa-custom")
            result = ctx.policy_engine.evaluate("Project Midnight")
        assert result.allowed is False
        assert result.triggered_rule == "custom_block_codenames"
