"""SLO-1 is an inequality because the difference is real, and the difference is
measured here rather than believed.

The document says the counting is not a tidy sum:

    custos_requests_total - (custos_requests_allowed + custos_requests_denied)

equals the requests refused before a decision was reached, and that remainder is
unattributable because no counter separates a 429 from a 401 from a 503 from the
gate's fail-closed refusal. Issue 158 is the counter that would let the objective be
written as a sum.

Two things are guarded, and they are different directions of the same claim. The
document must keep saying inequality rather than sum while 158 is open, because the
sum would be false and a reader would believe it. And the remainder must actually be
non-zero when the service refuses a request before deciding, because if it ever went
to zero the document's caution would be the wrong caution and the honest thing would
be to tighten it. A document that is more careful than the code needs is still a
document that is wrong about the code.
"""

import pathlib

from fastapi.testclient import TestClient

import main as app_module

SLO = pathlib.Path("docs/SLO.md")


def _norm(text: str) -> str:
    return " ".join(text.split())


def _slo_1_paragraph() -> str:
    """The SLO-1 entry, from its bold heading to the next objective."""
    body = SLO.read_text(encoding="utf-8")
    start = body.index("**SLO-1,")
    end = body.index("**SLO-2,")
    return _norm(body[start:end])


def _counters(client) -> dict:
    out = {}
    for line in client.get("/metrics").text.splitlines():
        if not line.startswith("custos_") or line.startswith("#"):
            continue
        name, _, value = line.partition(" ")
        try:
            out[name] = float(value)
        except ValueError:
            continue
    return out


class TestTheDocumentKeepsSayingInequality:
    def test_it_is_written_as_an_inequality_with_the_remainder_named(self):
        para = _slo_1_paragraph()
        assert "inequality" in para, "SLO-1 no longer says it is an inequality"
        assert "difference is real" in para or "not fully attributable" in para

    def test_it_names_the_counter_that_would_make_it_a_sum(self):
        para = _slo_1_paragraph()
        assert "158" in para, "SLO-1 must name the issue whose closure upgrades it"

    def test_it_does_not_present_the_accounting_as_a_sum(self):
        """The formula itself, not the vocabulary around it.

        The first version of this guard listed forbidden phrases, and a mutation that
        rewrote the formula into an equality while leaving the word "inequality" in
        the closing sentence stayed green. Pinning the arithmetic rather than the
        adjectives is what makes the check touch the claim.
        """
        para = _slo_1_paragraph()
        subtraction = "custos_requests_total - (custos_requests_allowed + custos_requests_denied)"
        assert subtraction in para, (
            "SLO-1 no longer shows the remainder as a subtraction; if the counters now "
            "add up, the objective should be rewritten deliberately, not by drift"
        )
        equality_forms = [
            "custos_requests_total = custos_requests_allowed",
            "custos_requests_allowed + custos_requests_denied = custos_requests_total",
        ]
        for form in equality_forms:
            assert form not in para, (
                f"SLO-1 is now written as an equality ({form!r}) while the remainder "
                "is still unattributable"
            )


class TestTheRemainderIsActuallyNonZero:
    def test_a_rate_limited_request_lands_in_total_and_not_in_an_outcome(self):
        """Measured, not asserted: drive the limiter into refusal and read /metrics.

        If this ever fails because the remainder is zero, that is good news and the
        document should be tightened rather than this test deleted, which is why the
        assertion message says so.
        """
        with TestClient(app_module.app) as client:
            before = _counters(client)
            posts = 0
            saw_429 = False
            for _ in range(200):
                r = client.post(
                    "/v1/evaluate",
                    json={
                        "client_id": "slo-accounting-probe",
                        "tenant_id": "default",
                        "content": "hello",
                        "token_count": 1,
                    },
                )
                posts += 1
                if r.status_code == 429:
                    saw_429 = True
                    break
            after = _counters(client)

        assert saw_429, "no 429 was produced, so the remainder could not be measured"
        total = after["custos_requests_total"] - before["custos_requests_total"]
        decided = (after["custos_requests_allowed"] - before["custos_requests_allowed"]) + (
            after["custos_requests_denied"] - before["custos_requests_denied"]
        )
        assert total == posts, (
            f"every request should be counted in total: posted {posts}, counted {total}"
        )
        assert after["custos_rate_limit_hits"] > before["custos_rate_limit_hits"]
        remainder = total - decided
        assert remainder >= 1, (
            "the remainder is zero: the refusal was counted as an outcome, so SLO-1 "
            "can be written as a sum and the document should be tightened"
        )
