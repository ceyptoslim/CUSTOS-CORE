"""Fail-closed production secret validation (strict env-presence rule).

Regression tests for the P2 audit finding: CUSTOS_JWT_SECRET previously
fell back to a hardcoded dev default with no production startup check.
"""
import pytest
from fastapi.testclient import TestClient

from custos.auth import validate_production_secrets


class TestValidateProductionSecrets:
    def test_production_unset_secret_raises(self, monkeypatch):
        monkeypatch.setenv("CUSTOS_ENV", "production")
        monkeypatch.delenv("CUSTOS_JWT_SECRET", raising=False)
        with pytest.raises(RuntimeError, match="CUSTOS_JWT_SECRET"):
            validate_production_secrets()

    def test_production_dev_default_secret_raises(self, monkeypatch):
        monkeypatch.setenv("CUSTOS_ENV", "production")
        monkeypatch.setenv("CUSTOS_JWT_SECRET", "dev-secret-change-in-production")
        with pytest.raises(RuntimeError, match="dev default"):
            validate_production_secrets()

    def test_production_real_secret_passes(self, monkeypatch):
        monkeypatch.setenv("CUSTOS_ENV", "production")
        monkeypatch.setenv("CUSTOS_JWT_SECRET", "a-real-unique-production-secret-32bytes")
        assert validate_production_secrets() is None

    def test_development_unset_secret_passes(self, monkeypatch):
        # Backwards compatibility: dev/test environments keep the fallback.
        monkeypatch.setenv("CUSTOS_ENV", "development")
        monkeypatch.delenv("CUSTOS_JWT_SECRET", raising=False)
        assert validate_production_secrets() is None


class TestStartupWiring:
    def test_app_refuses_to_start_in_production_without_secret(self, monkeypatch):
        import main as app_module
        monkeypatch.setenv("CUSTOS_ENV", "production")
        monkeypatch.delenv("CUSTOS_JWT_SECRET", raising=False)
        with pytest.raises(RuntimeError):
            with TestClient(app_module.app):
                pass

    def test_app_starts_in_production_with_real_secret(self, monkeypatch, tmp_path):
        import main as app_module
        monkeypatch.setenv("CUSTOS_ENV", "production")
        monkeypatch.setenv("CUSTOS_JWT_SECRET", "a-real-unique-production-secret-32bytes")
        # Production also requires an audit store that outlives the process
        # (see tests/test_audit_persistence.py). Provisioning it here is the
        # configuration a real deployment needs, not a concession to the test.
        monkeypatch.setenv("AUDIT_DB_PATH", str(tmp_path / "audit.sqlite"))
        # Rebuild the default tenant's chain now that the store is configured,
        # which is what a process starting with the variable set does at import.
        from custos.tenant import TenantConfig
        from custos.tenant import DEFAULT_QUOTA

        app_module.tenant_manager.register(
            "default", TenantConfig(tenant_id="default", quota=DEFAULT_QUOTA)
        )
        with TestClient(app_module.app) as client:
            resp = client.get("/v1/info")
            assert resp.status_code == 200
            assert resp.json()["audit_durable"] is True
