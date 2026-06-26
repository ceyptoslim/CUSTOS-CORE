"""
Tests for custos/snapshot.py and GET /v1/audit/snapshot
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import time
import pytest
from fastapi.testclient import TestClient
from custos.audit import AuditChain
from custos.snapshot import SnapshotEngine
from main import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def snapshot_setup():
    chain = AuditChain()
    chain.record("c1", "allow", "ok", "first content")
    chain.record("c1", "deny", "pii", "second content")
    chain.record("c2", "allow", "ok", "third content")
    engine = SnapshotEngine(chain)
    return engine, chain


class TestSnapshotEngine:
    def test_snapshot_contains_all_records(self, snapshot_setup):
        engine, chain = snapshot_setup
        result = engine.generate()
        assert result.record_count == 3

    def test_snapshot_chain_valid(self, snapshot_setup):
        engine, chain = snapshot_setup
        result = engine.generate()
        assert result.chain_valid is True

    def test_snapshot_has_hash(self, snapshot_setup):
        engine, chain = snapshot_setup
        result = engine.generate()
        assert len(result.snapshot_hash) == 64

    def test_empty_range_returns_empty(self, snapshot_setup):
        engine, chain = snapshot_setup
        future_time = time.time() + 9999
        result = engine.generate(start_time=future_time)
        assert result.record_count == 0

    def test_snapshot_verify_passes(self, snapshot_setup):
        engine, chain = snapshot_setup
        result = engine.generate()
        valid, reason = engine.verify_snapshot(result.to_dict())
        assert valid is True
        assert reason == "OK"

    def test_tampered_snapshot_fails_verify(self, snapshot_setup):
        engine, chain = snapshot_setup
        result = engine.generate()
        tampered = result.to_dict()
        tampered["record_count"] = 999
        valid, reason = engine.verify_snapshot(tampered)
        assert valid is False
        assert "tampered" in reason.lower()

    def test_snapshot_without_hash_fails_verify(self, snapshot_setup):
        engine, chain = snapshot_setup
        valid, reason = engine.verify_snapshot({"record_count": 0})
        assert valid is False

    def test_time_range_filters_records(self, snapshot_setup):
        engine, chain = snapshot_setup
        now = time.time()
        result = engine.generate(start_time=now - 60, end_time=now + 60)
        assert result.record_count == 3


class TestSnapshotEndpoint:
    def test_snapshot_returns_200(self, client):
        resp = client.get("/v1/audit/snapshot")
        assert resp.status_code == 200

    def test_snapshot_has_required_fields(self, client):
        resp = client.get("/v1/audit/snapshot")
        data = resp.json()
        for field in ["generated_at", "record_count", "records",
                      "chain_valid", "snapshot_hash", "latest_hash"]:
            assert field in data

    def test_snapshot_verify_endpoint(self, client):
        snapshot = client.get("/v1/audit/snapshot").json()
        resp = client.post("/v1/audit/snapshot/verify", json={"snapshot": snapshot})
        assert resp.status_code == 200
        assert resp.json()["valid"] is True

    def test_tampered_snapshot_verify_fails(self, client):
        snapshot = client.get("/v1/audit/snapshot").json()
        snapshot["record_count"] = 9999
        resp = client.post("/v1/audit/snapshot/verify", json={"snapshot": snapshot})
        assert resp.json()["valid"] is False
