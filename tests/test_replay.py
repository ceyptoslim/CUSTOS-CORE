"""
Tests for custos/replay.py and POST /v1/replay
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from fastapi.testclient import TestClient
from custos.audit import AuditChain
from custos.policy_engine import PolicyEngine
from custos.replay import ReplayEngine
from main import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def replay_setup():
    chain = AuditChain()
    engine = PolicyEngine()
    replay = ReplayEngine(chain, engine)
    content = "What is the capital of France?"
    record = chain.record("test", "allow", "No policy violations detected", content)
    return replay, chain, record, content


class TestReplayEngine:
    def test_replay_matching_content_succeeds(self, replay_setup):
        replay, chain, record, content = replay_setup
        result = replay.replay_by_hash(record.record_hash, content)
        assert result.original_record_hash == record.record_hash
        assert result.replayed_action == "allow"

    def test_replay_decision_matches_original(self, replay_setup):
        replay, chain, record, content = replay_setup
        result = replay.replay_by_hash(record.record_hash, content)
        assert result.decision_matches is True

    def test_replay_wrong_hash_raises(self, replay_setup):
        replay, _, _, content = replay_setup
        with pytest.raises(ValueError, match="not found"):
            replay.replay_by_hash("a" * 64, content)

    def test_replay_wrong_content_raises(self, replay_setup):
        replay, chain, record, content = replay_setup
        with pytest.raises(ValueError, match="content does not match"):
            replay.replay_by_hash(record.record_hash, "wrong content")

    def test_replay_denied_content_shows_mismatch(self):
        chain = AuditChain()
        engine = PolicyEngine()
        replay = ReplayEngine(chain, engine)
        content = "My SSN is 123-45-6789"
        # Manually store as allow (simulating old policy)
        record = chain.record("test", "allow", "old policy allowed this", content)
        result = replay.replay_by_hash(record.record_hash, content)
        # Current policy denies SSN — decision should not match
        assert result.replayed_action == "deny"
        assert result.decision_matches is False

    def test_replay_result_has_replay_timestamp(self, replay_setup):
        replay, chain, record, content = replay_setup
        result = replay.replay_by_hash(record.record_hash, content)
        assert result.replay_timestamp > record.timestamp


class TestReplayEndpoint:
    def test_valid_replay_returns_200(self, client):
        # First create a record via evaluate
        eval_resp = client.post("/v1/evaluate", json={
            "client_id": "default",
            "content": "Replay endpoint test content",
        })
        assert eval_resp.status_code == 200
        record_hash = eval_resp.json()["audit_record_hash"]

        replay_resp = client.post("/v1/replay", json={
            "record_hash": record_hash,
            "original_content": "Replay endpoint test content",
        })
        assert replay_resp.status_code == 200

    def test_invalid_hash_returns_404(self, client):
        resp = client.post("/v1/replay", json={
            "record_hash": "a" * 64,
            "original_content": "some content",
        })
        assert resp.status_code == 404

    def test_replay_response_has_decision_matches(self, client):
        eval_resp = client.post("/v1/evaluate", json={
            "client_id": "default",
            "content": "Decision match test",
        })
        record_hash = eval_resp.json()["audit_record_hash"]
        replay_resp = client.post("/v1/replay", json={
            "record_hash": record_hash,
            "original_content": "Decision match test",
        })
        assert "decision_matches" in replay_resp.json()
