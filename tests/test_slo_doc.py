"""The SLO document stays bound to the instruments it names.

An objectives document fails quietly: it survives every green test suite while
describing metrics that were renamed, a counter that never existed, or an objective
the service cannot produce. These guards hold it to `/metrics` and `/ready` as they
are implemented, and to the drills that exist in the tree.
"""

import pathlib
import re

DOC = pathlib.Path("docs/SLO.md")
MAIN = pathlib.Path("main.py")
DRILLS = pathlib.Path("scripts/drills")


def _flat(path: pathlib.Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


def _metric_names_emitted() -> set[str]:
    """Every metric name main.py actually writes into the /metrics body."""
    source = MAIN.read_text(encoding="utf-8")
    # The /metrics body is built as f"custos_name {value}", so the separator is a
    # space. The first version of this extractor looked for the brace immediately
    # after the name and returned an empty set, which made the "names only real
    # metrics" guard pass over everything: a scan that finds nothing agrees with
    # every claim.
    # Two shapes reach the body: f"custos_name {value}" and the labelled form
    # f'custos_name{{kind="..."}} {value}'. The first version of this extractor
    # handled only the first, so `custos_refused_total` was invisible on the
    # emitting side while also being written in the document with a brace suffix
    # that the backtick scan could not see, and the two gaps cancelled: the guard
    # passed while the metric was neither extractable nor checkable. Both shapes
    # are read now, and the document scan strips a label suffix back to the name.
    names = set(re.findall(r'f["\'](custos_[a-z_]+)', source))
    return names


class TestEveryMetricTheDocumentNamesIsEmitted:
    def test_the_metrics_table_names_only_real_metrics(self):
        doc = _flat(DOC)
        emitted = _metric_names_emitted()
        documented = {
            name
            for name in re.findall(r"`(custos_[a-z_]+)(?:\{[^}`]*\})?`", doc)
        }
        named = {n for n in emitted | documented if n in documented or f"`{n}`" in doc}
        assert named, "the document names no metrics at all"
        missing = sorted(n for n in named if n not in emitted)
        assert not missing, f"the document names metrics main.py does not emit: {missing}"

    def test_every_emitted_metric_is_documented(self):
        """The other direction, which is the half a table usually loses: a new gauge
        lands in main.py and the document stays silent about it."""
        doc = _flat(DOC)
        undocumented = sorted(n for n in _metric_names_emitted() if n not in doc)
        assert not undocumented, f"main.py emits metrics the document does not name: {undocumented}"

    def test_the_readiness_checks_are_the_ones_the_endpoint_returns(self):
        doc = _flat(DOC)
        source = MAIN.read_text(encoding="utf-8")
        for check in ("policy_engine", "rate_limiter", "audit_chain", "tenant_manager"):
            assert check in doc, f"{check} missing from the document"
            assert f'"{check}"' in source, f"{check} no longer a readiness check"
        assert "custody" in doc and '"custody"' in source


class TestTheDocumentDoesNotClaimAnInstrumentItLacks:
    def test_it_says_there_is_no_latency_objective_and_why(self):
        doc = _flat(DOC)
        assert "No latency objective and no throughput objective" in doc
        assert "There is no histogram" in doc

    def test_main_really_has_no_histogram(self):
        """If a histogram is added, the paragraph above becomes false and this fails,
        which is the only way the document finds out."""
        source = MAIN.read_text(encoding="utf-8")
        assert "histogram" not in source.lower()

    def test_it_records_the_refusal_accounting_gap_and_its_closure(self):
        """It said the labels were missing. They are not missing now, and the
        document has to say both: a reader needs to know the identity closed and
        that it was open long enough to be written down."""
        doc = _flat(DOC)
        assert "issue 158" in doc.lower()
        assert "custos_refused_total{kind}" in doc
        assert "now a sum rather than an inequality" in doc


class TestTheDrillsItCitesExist:
    def test_every_drill_the_document_names_is_in_the_tree(self):
        doc = _flat(DOC)
        named = set(re.findall(r"(phase\d+_[a-z_]+\.py)", doc))
        assert named, "the document names no drills"
        missing = sorted(n for n in named if not (DRILLS / n).exists())
        assert not missing, f"the document names drills that do not exist: {missing}"


class TestTheObjectivesSayWhoProducesTheNumber:
    def test_each_marker_is_defined(self):
        doc = _flat(DOC)
        for marker in ("MEASURED", "RUN", "DEFINE ONLY"):
            assert marker in doc, f"marker {marker} missing"

    def test_the_unmeasurable_objectives_name_the_producer(self):
        doc = _flat(DOC)
        # Bypass rate, completeness, decision correctness and erasure across backups
        # are the four the service cannot produce. Each must say who can.
        assert "only visible to whoever operates the executor" in doc
        assert "needs an out-of-band comparison against an earlier anchor" in doc
        assert "needs labelled outcomes from the deployment" in doc
        assert "lives with whoever holds the copies" in doc

    def test_the_durability_objective_does_not_promise_a_rate(self):
        doc = _flat(DOC)
        assert "Neither drill measures a rate" in doc
