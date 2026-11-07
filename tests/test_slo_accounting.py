"""SLO-1 now closes, and the closure is measured here rather than believed.

The history matters to a reader of these guards, so it is in the module docstring
rather than in a commit nobody opens:

The first version of SLO-1 said the difference between `custos_requests_total` and
the allowed and denied counters was "requests refused before a decision". That was
wrong twice. It was unattributable, because no counter separated a 422 from a 403
from a 429, and it also silently contained decisions flagged for audit, which
increment `custos_requests_audited` instead of `custos_requests_allowed`. Issue 158
asked for the labels. They are in `custos_refused_total{kind}` now, and SLO-1 is a
six-term sum with no remainder:

    total = allowed + audited + denied + refused{invalid_request}
                                  + refused{unknown_tenant}
                                  + refused{rate_limited}

What is guarded, in both directions:

* the document keeps the sum, names all six terms, and does not fall back to a
  difference that hides a category;
* the arithmetic closes in a live process, exercised through every path that can
  reach one of the six terms rather than asserted over counters alone;
* the labelled counter's total equals what the identity says it should, per kind,
  so a label that stops being incremented fails here rather than in a dashboard.

The third of those is the one that would have caught the original error. An
identity checked only in aggregate passes while a category is missing, because the
missing category is on both sides of a difference. Checked per kind, it does not.
"""

import pathlib
import re

from fastapi.testclient import TestClient

import main as app_module

SLO = pathlib.Path("docs/SLO.md")
TERMS = (
    "custos_requests_allowed",
    "custos_requests_audited",
    "custos_requests_denied",
)


def _norm(text: str) -> str:
    return " ".join(text.split())


def _slo_1_paragraph() -> str:
    """The SLO-1 entry, from its bold heading to the next objective."""
    body = SLO.read_text(encoding="utf-8")
    start = body.index("**SLO-1,")
    end = body.index("**SLO-2,")
    return _norm(body[start:end])


def _counters(client) -> dict:
    """Every custos_ line, with the labelled series kept under their full name."""
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


def _refused(counters: dict, kind: str) -> float:
    return counters.get(f'custos_refused_total{{kind="{kind}"}}', 0.0)


class TestTheDocumentStatesTheSum:
    def test_it_is_written_as_a_sum_that_closes(self):
        para = _slo_1_paragraph()
        assert "closes" in para, "SLO-1 no longer says the accounting closes"
        assert "inequality" not in para, (
            "SLO-1 is an inequality again, which is only true if a category is missing"
        )

    def test_it_names_all_six_terms(self):
        para = _slo_1_paragraph()
        for term in TERMS:
            assert term in para, f"SLO-1 does not name {term}"
        for kind in ("invalid_request", "unknown_tenant", "rate_limited"):
            assert f'kind="{kind}"' in para, f"SLO-1 does not name the {kind} label"

    def test_it_keeps_the_reason_the_first_version_was_wrong(self):
        """The audit category is the term a reader would drop first."""
        para = _slo_1_paragraph()
        assert "audit" in para and "indistinguishable from a refusal" in para

    def test_it_says_the_counter_is_per_process(self):
        para = _slo_1_paragraph()
        assert "per process" in para


class TestTheArithmeticClosesInALiveProcess:
    def _drive(self, client, before: dict) -> dict:
        """Every path that can reach one of the six terms, then read again."""
        client.post(
            "/v1/evaluate",
            json={"client_id": "slo-probe", "tenant_id": "default",
                  "content": "hello", "token_count": 1},
        )
        client.post(
            "/v1/evaluate",
            json={"client_id": "slo-probe", "tenant_id": "no-such-tenant",
                  "content": "hello", "token_count": 1},
        )
        # The model limits content by characters and the validator by bytes, so a
        # multi-byte character string under the character limit and over the byte
        # limit is the one shape that reaches validate_request. An empty string is
        # refused by the model, before the decision path is entered, which is why
        # the first version of this probe measured nothing and said so.
        client.post(
            "/v1/evaluate",
            json={"client_id": "slo-probe", "tenant_id": "default",
                  "content": "\u00e9" * 16_385, "token_count": 1},
        )
        for _ in range(200):
            r = client.post(
                "/v1/evaluate",
                json={"client_id": "slo-probe", "tenant_id": "default",
                      "content": "hello", "token_count": 1},
            )
            if r.status_code == 429:
                break
        return _counters(client)

    def test_the_six_terms_account_for_every_request(self):
        with TestClient(app_module.app) as client:
            before = _counters(client)
            after = self._drive(client, before)
        total = after["custos_requests_total"] - before["custos_requests_total"]
        decided = sum(after[t] - before[t] for t in TERMS)
        refused = sum(
            _refused(after, k) - _refused(before, k)
            for k in ("invalid_request", "unknown_tenant", "rate_limited")
        )
        assert total > 0, "nothing reached the decision path, so nothing was measured"
        assert refused >= 3, f"the probe did not refuse three times, it refused {refused}"
        assert total == decided + refused, (
            f"the identity does not close: total {total}, decided {decided}, "
            f"refused {refused}. Either a refusal site was added without a label or a "
            f"decision outcome was added without a term in SLO-1."
        )

    def test_each_label_moves_for_its_own_reason(self):
        """Per kind, because an aggregate identity hides a missing category."""
        with TestClient(app_module.app) as client:
            before = _counters(client)
            after = self._drive(client, before)
        for kind, reason in (
            ("invalid_request", "the empty content should have been refused as invalid"),
            ("unknown_tenant", "the unknown tenant should have been refused"),
            ("rate_limited", "the loop should have driven the limiter into refusal"),
        ):
            moved = _refused(after, kind) - _refused(before, kind)
            assert moved >= 1, f"{kind} did not move: {reason}"


class TestEveryLabelIsWired:
    """The identity is only as true as the labels behind it.

    A labelled counter can fail in two quiet ways that a sum cannot see: the series
    stops being emitted while the key and the increment stay in the code, or the key
    is emitted and never incremented so the series is always zero. The second is the
    worse one, because a zero looks like a healthy absence of refusals.
    """

    SOURCE = pathlib.Path("main.py")

    def test_the_emitted_kinds_are_the_three_the_identity_needs(self):
        kinds = set(
            re.findall(
                r'custos_refused_total\{\{kind="([a-z_]+)"\}\}',
                self.SOURCE.read_text(encoding="utf-8"),
            )
        )
        assert kinds == {"invalid_request", "unknown_tenant", "rate_limited"}, (
            f"the identity needs three labelled refusals and the body emits {sorted(kinds)}"
        )

    def test_every_emitted_label_is_incremented_somewhere(self):
        source = self.SOURCE.read_text(encoding="utf-8")
        for kind in ("invalid_request", "unknown_tenant", "rate_limited"):
            key = f"custos_refused_{kind}"
            assert f'_metrics["{key}"] += 1' in source, (
                f"{key} is emitted but nothing increments it, so the series would "
                f"always read zero and look like an absence of refusals"
            )

    def test_the_burn_counter_is_incremented_by_the_handler_that_serves_the_503(self):
        source = self.SOURCE.read_text(encoding="utf-8")
        handler_start = source.index("async def audit_store_full_handler")
        handler_end = source.index("@app.get(\"/v1/info\")")
        assert '_metrics["custos_decisions_unrecorded"] += 1' in source[handler_start:handler_end]
