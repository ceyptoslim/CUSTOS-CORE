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

    def test_app_starts_in_production_with_real_secret(self, monkeypatch):
        import main as app_module
        monkeypatch.setenv("CUSTOS_ENV", "production")
        monkeypatch.setenv("CUSTOS_JWT_SECRET", "a-real-unique-production-secret-32bytes")
        with TestClient(app_module.app) as client:
            resp = client.get("/v1/info")
            assert resp.status_code == 200
