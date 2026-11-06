"""
A refused request tells the caller when to come back.

The defect this prevents: the 429 carried a reason and no wait, so a throttled
client retried immediately and made the condition it was being limited for
worse. RFC 9110 defines Retry-After on 429 for exactly this, and its absence is
the kind of gap a checklist catches and a test suite does not.

The limit kept honest here: the header reports the window the limiter will
actually enforce, and it is omitted rather than invented when no window is
behind the refusal. "Unknown client" is a configuration fault, not a quota, so
it carries no wait.
"""
import pytest
from fastapi.testclient import TestClient

from custos.rate_limiter import QuotaConfig, RateLimiter


@pytest.fixture()
def limiter():
    r = RateLimiter()
    r.register("tight", QuotaConfig(requests_per_minute=2, requests_per_hour=100))
    return r


def test_no_wait_reported_when_nothing_is_exceeded(limiter):
    assert limiter.retry_after_seconds("tight") is None


def test_wait_reported_matches_the_minute_window(limiter):
    for _ in range(2):
        assert limiter.check_and_consume("tight")[0] is True
    allowed, reason = limiter.check_and_consume("tight")
    assert allowed is False
    assert "Minute" in reason

    wait = limiter.retry_after_seconds("tight")
    assert isinstance(wait, int)
    assert 1 <= wait <= 60, f"wait {wait} is outside the window it claims to describe"


def test_asking_for_the_wait_does_not_consume_or_advance(limiter):
    for _ in range(2):
        limiter.check_and_consume("tight")
    first = limiter.retry_after_seconds("tight")
    second = limiter.retry_after_seconds("tight")
    assert first == second, "reporting the wait must be read-only"
    # Still refused afterwards, i.e. the refusal was not quietly spent.
    assert limiter.check_and_consume("tight")[0] is False


def test_unknown_key_has_no_wait_to_report(limiter):
    assert limiter.retry_after_seconds("nobody-registered") is None


def test_hour_window_reports_the_hour(limiter):
    r = RateLimiter()
    r.register("hourly", QuotaConfig(requests_per_minute=100, requests_per_hour=2))
    for _ in range(2):
        r.check_and_consume("hourly")
    allowed, reason = r.check_and_consume("hourly")
    assert allowed is False and "Hour" in reason
    wait = r.retry_after_seconds("hourly")
    assert 1 <= wait <= 3600


def test_429_response_carries_the_header():
    """End-to-end: the refusal a caller sees includes the wait."""
    import main as app_module

    with TestClient(app_module.app) as client:
        wait = None
        for _ in range(200):
            r = client.post(
                "/v1/evaluate",
                json={"client_id": "retry-after-probe", "tenant_id": "default",
                      "content": "hello", "token_count": 1},
            )
            if r.status_code == 429:
                wait = r.headers.get("Retry-After")
                break
        assert wait is not None, "no 429 was produced, so the header could not be checked"
        assert wait.isdigit(), f"Retry-After must be integer seconds, got {wait!r}"
        assert 1 <= int(wait) <= 3600
