"""
Tests for API endpoints (main.py)
Covers: /health, /ready, /metrics, /v1/evaluate, /v1/audit
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from fastapi.testclient import TestClient
from main import app


@pytest.fixture
def client():
    return TestClient(app)


class TestHealthEndpoint:
    def test_returns_200(self, client):
        assert client.get("/health").status_code == 200

    def test_status_is_ok(self, client):
        assert client.get("/health").json()["status"] == "ok"

    def test_uptime_is_non_negative(self, client):
        data = client.get("/health").json()
        assert "uptime_seconds" in data
        assert data["uptime_seconds"] >= 0


class TestReadyEndpoint:
    def test_returns_200(self, client):
        assert client.get("/ready").status_code == 200

    def test_status_is_ready(self, client):
        assert client.get("/ready").json()["status"] == "ready"

    def test_checks_are_present(self, client):
        data = client.get("/ready").json()
        assert "checks" in data
        assert "policy_engine" in data["checks"]
        assert "rate_limiter" in data["checks"]
        assert "audit_chain" in data["checks"]

    def test_all_checks_pass(self, client):
        checks = client.get("/ready").json()["checks"]
        for name, status in checks.items():
            assert status == "ok", f"Check {name} failed"


class TestMetricsEndpoint:
    def test_returns_200(self, client):
        assert client.get("/metrics").status_code == 200

    def test_prometheus_format(self, client):
        text = client.get("/metrics").text
        assert "custos_requests_total" in text
        assert "custos_audit_chain_length" in text
        assert "# HELP" in text
        assert "# TYPE" in text


class TestEvaluateEndpoint:
    def test_clean_request_is_allowed(self, client):
        r = client.post("/v1/evaluate", json={
            "client_id": "default",
            "content": "Summarize the quarterly report",
        })
        assert r.status_code == 200
        data = r.json()
        assert data["allowed"] is True
        assert data["action"] == "allow"

    def test_response_includes_audit_hash(self, client):
        r = client.post("/v1/evaluate", json={
            "client_id": "default",
            "content": "Hello world",
        })
        data = r.json()
        assert "audit_record_hash" in data
        assert len(data["audit_record_hash"]) == 64  # SHA-256 hex

    def test_pii_request_is_denied(self, client):
        r = client.post("/v1/evaluate", json={
            "client_id": "default",
            "content": "My SSN is 123-45-6789",
        })
        assert r.status_code == 200
        data = r.json()
        assert data["allowed"] is False
        assert data["action"] == "deny"

    def test_unknown_client_returns_429(self, client):
        r = client.post("/v1/evaluate", json={
            "client_id": "nonexistent_client",
            "content": "Hello",
        })
        assert r.status_code == 429

    def test_empty_content_returns_422(self, client):
        r = client.post("/v1/evaluate", json={
            "client_id": "default",
            "content": "   ",
        })
        assert r.status_code == 422

    def test_oversized_content_returns_422(self, client):
        r = client.post("/v1/evaluate", json={
            "client_id": "default",
            "content": "x" * 33_000,
        })
        assert r.status_code == 422


class TestAuditEndpoint:
    def test_audit_log_is_accessible(self, client):
        # Make a request first to populate the chain
        client.post("/v1/evaluate", json={
            "client_id": "default",
            "content": "Audit test content",
        })
        r = client.get("/v1/audit")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_audit_records_have_required_fields(self, client):
        client.post("/v1/evaluate", json={
            "client_id": "default",
            "content": "Field check content",
        })
        records = client.get("/v1/audit").json()
        assert len(records) > 0
        record = records[-1]
        for field in ["timestamp", "client_id", "action", "reason",
                      "content_hash", "record_hash", "previous_hash"]:
            assert field in record

    def test_audit_chain_verify_passes(self, client):
        r = client.get("/v1/audit/verify")
        assert r.status_code == 200
        assert r.json()["valid"] is True
