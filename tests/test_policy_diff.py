"""
Tests for custos/policy_diff.py and POST /v1/policy/diff
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from fastapi.testclient import TestClient
from custos.policy_diff import PolicyDiffer
from custos.policy_engine import PolicyAction, PolicyRule
from main import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def differ():
    return PolicyDiffer()


@pytest.fixture
def default_rules():
    return [
        PolicyRule("block_ssn", r"\b\d{3}-\d{2}-\d{4}\b", PolicyAction.DENY, "SSN detected"),
    ]


@pytest.fixture
def strict_rules():
    return [
        PolicyRule("block_ssn", r"\b\d{3}-\d{2}-\d{4}\b", PolicyAction.DENY, "SSN detected"),
        PolicyRule("block_names", r"(?i)\bjohn\b", PolicyAction.DENY, "Name blocked"),
    ]


class TestPolicyDiffer:
    def test_same_decision_no_change(self, differ, default_rules):
        result = differ.diff("Hello world", default_rules, default_rules)
        assert result.decision_changed is False

    def test_different_decision_shows_change(self, differ, default_rules, strict_rules):
        result = differ.diff("My name is John", default_rules, strict_rules)
        assert result.decision_changed is True
        assert result.current_action == "allow"
        assert result.proposed_action == "deny"

    def test_content_preview_truncated(self, differ, default_rules):
        long_content = "x" * 200
        result = differ.diff(long_content, default_rules, default_rules)
        assert len(result.content_preview) <= 100

    def test_change_summary_shows_both_actions(self, differ, default_rules, strict_rules):
        result = differ.diff("My name is John", default_rules, strict_rules)
        assert "allow" in result.change_summary
        assert "deny" in result.change_summary

    def test_no_change_summary_correct(self, differ, default_rules):
        result = differ.diff("Clean content", default_rules, default_rules)
        assert "No change" in result.change_summary

    def test_rule_removed_changes_decision(self, differ, default_rules):
        empty_rules = []
        result = differ.diff("My SSN is 123-45-6789", default_rules, empty_rules)
        assert result.decision_changed is True
        assert result.current_action == "deny"
        assert result.proposed_action == "allow"


class TestPolicyDiffEndpoint:
    def test_same_rules_no_change(self, client):
        resp = client.post("/v1/policy/diff", json={
            "content": "Hello world",
            "current_rules": [
                {"name": "test", "pattern": r"\bSSN\b",
                 "action": "deny", "reason": "test"}
            ],
            "proposed_rules": [
                {"name": "test", "pattern": r"\bSSN\b",
                 "action": "deny", "reason": "test"}
            ],
        })
        assert resp.status_code == 200
        assert resp.json()["decision_changed"] is False

    def test_new_rule_changes_decision(self, client):
        resp = client.post("/v1/policy/diff", json={
            "content": "My SSN is 123-45-6789",
            "current_rules": [],
            "proposed_rules": [
                {"name": "block_ssn", "pattern": r"\b\d{3}-\d{2}-\d{4}\b",
                 "action": "deny", "reason": "SSN detected"}
            ],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["decision_changed"] is True
        assert data["current_action"] == "allow"
        assert data["proposed_action"] == "deny"

    def test_invalid_action_returns_422(self, client):
        resp = client.post("/v1/policy/diff", json={
            "content": "test",
            "current_rules": [
                {"name": "x", "pattern": "x",
                 "action": "invalid_action", "reason": "x"}
            ],
            "proposed_rules": [],
        })
        assert resp.status_code == 422
