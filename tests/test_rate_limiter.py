"""
Tests for custos/rate_limiter.py
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from custos.rate_limiter import QuotaConfig, RateLimiter


@pytest.fixture
def limiter():
    rl = RateLimiter()
    rl.register("test_client", QuotaConfig(
        requests_per_minute=5,
        requests_per_hour=100,
        tokens_per_minute=1000,
    ))
    return rl


class TestRegistration:
    def test_registered_client_can_make_requests(self, limiter):
        allowed, msg = limiter.check_and_consume("test_client")
        assert allowed is True
        assert msg == "OK"

    def test_unknown_client_is_rejected(self, limiter):
        allowed, msg = limiter.check_and_consume("ghost_client")
        assert allowed is False
        assert "Unknown client" in msg

    def test_unregister_removes_client(self, limiter):
        assert limiter.unregister("test_client") is True
        allowed, _ = limiter.check_and_consume("test_client")
        assert allowed is False

    def test_unregister_returns_false_for_unknown(self, limiter):
        assert limiter.unregister("nobody") is False


class TestQuotaEnforcement:
    def test_minute_quota_is_enforced(self, limiter):
        for _ in range(5):
            allowed, _ = limiter.check_and_consume("test_client")
            assert allowed is True
        allowed, msg = limiter.check_and_consume("test_client")
        assert allowed is False
        assert "Minute" in msg

    def test_token_quota_is_enforced(self):
        rl = RateLimiter()
        rl.register("tok", QuotaConfig(
            requests_per_minute=100,
            requests_per_hour=1000,
            tokens_per_minute=10,
        ))
        allowed, _ = rl.check_and_consume("tok", tokens=10)
        assert allowed is True
        allowed, msg = rl.check_and_consume("tok", tokens=1)
        assert allowed is False
        assert "Token" in msg

    def test_multiple_clients_are_isolated(self):
        rl = RateLimiter()
        rl.register("a", QuotaConfig(requests_per_minute=1, requests_per_hour=100))
        rl.register("b", QuotaConfig(requests_per_minute=10, requests_per_hour=100))
        rl.check_and_consume("a")  # exhaust a
        allowed_a, _ = rl.check_and_consume("a")
        allowed_b, _ = rl.check_and_consume("b")
        assert allowed_a is False
        assert allowed_b is True


class TestGetAllQuotas:
    def test_returns_dict(self, limiter):
        quotas = limiter.get_all_quotas()
        assert isinstance(quotas, dict)
        assert "test_client" in quotas

    def test_no_mutation_error_during_iteration(self, limiter):
        """Regression: list(keys()) snapshot prevents RuntimeError."""
        limiter.register("c2", QuotaConfig(10, 100))
        limiter.register("c3", QuotaConfig(10, 100))
        quotas = limiter.get_all_quotas()
        assert len(quotas) >= 3

    def test_quota_fields_are_present(self, limiter):
        q = limiter.get_all_quotas()["test_client"]
        for field in ["requests_per_minute", "requests_per_hour",
                      "tokens_per_minute", "current_minute_count",
                      "current_hour_count", "current_token_count"]:
            assert field in q
