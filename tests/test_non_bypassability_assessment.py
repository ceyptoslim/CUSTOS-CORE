"""Guards on the deployment-level non-bypassability assessment.

The assessment commits to a verdict, and a verdict that survives the inventory changing
underneath it is worse than no verdict. These tests do not decide whether the deployment
conforms. They check that the document still answers the inventory it was written against,
so a row flipping from `unmediated-declared` to `mediated` forces the verdict to be
revisited instead of leaving a negative finding standing on evidence that no longer exists.
"""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "docs" / "design" / "path-inventory.yaml"
ASSESSMENT = ROOT / "docs" / "design" / "NON-BYPASSABILITY-ASSESSMENT.md"
INVENTORY_DOC = ROOT / "docs" / "design" / "EXECUTION-PATH-INVENTORY.md"


def flat(path: Path) -> str:
    """Wrapping removed, so prose checks do not depend on line breaks."""
    return " ".join(path.read_text(encoding="utf-8").split())


@pytest.fixture(scope="module")
def rows():
    data = yaml.safe_load(INVENTORY.read_text(encoding="utf-8"))
    return {row["id"]: row for row in data["paths"]}


@pytest.fixture(scope="module")
def assessment():
    return flat(ASSESSMENT).lower()


class TestVerdictFollowsTheInventory:
    def test_declared_bypass_row_exists(self, rows):
        """The DOES_NOT_CONFORM verdict rests on a row that says a bypass exists."""
        bypasses = [
            rid for rid, row in rows.items()
            if row["status"] == "unmediated-declared"
        ]
        assert bypasses, (
            "the assessment records a known bypass; the inventory now declares none, so "
            "the verdict must be re-derived rather than inherited"
        )

    def test_assessment_states_does_not_conform(self, assessment):
        assert "does_not_conform" in assessment, (
            "a known bypass path capable of the protected effect settles the verdict; "
            "the document must say so explicitly rather than imply it"
        )

    def test_e1_verdict_is_the_negative_one(self, assessment):
        """The verdict is asserted where a reader looks for it, not only in passing."""
        assert "verdict for `e1`: does_not_conform" in assessment.lower(), (
            "the E1 verdict must be stated in the heading form the vocabulary calls for"
        )

    def test_e2_is_declared_outside_the_scale(self, assessment):
        """No path produces E2 here, so it must not be recorded as either verdict."""
        assert "verdict for `e2`: not assessed" in assessment.lower()

    def test_conformance_is_never_the_verdict_for_an_effect_here(self, assessment):
        for effect in ("e1", "e2"):
            assert f"verdict for `{effect}`: conforms" not in assessment.lower()


class TestCompletenessStaysOpen:
    def test_completeness_is_declared_not_established(self, assessment):
        assert "not established" in assessment

    def test_inventory_also_says_attestation_not_derivation(self):
        assert "attestation, not a derivation" in flat(INVENTORY_DOC).lower()


class TestAssessmentStaysBoundToDeclaredPaths:
    def test_every_referenced_path_is_a_declared_row(self, rows, assessment):
        """A verdict about a path the inventory does not declare would be unanchored."""
        referenced = {
            token.rstrip(".:,")
            for token in assessment.split()
            if len(token) > 1 and token[0] in "Pp" and token[1:].isdigit()
        }
        assert referenced, "the assessment should name the paths it judged"
        unknown = {token.upper() for token in referenced} - set(rows)
        assert not unknown, f"assessment names undeclared paths: {sorted(unknown)}"


class TestAvailabilityIsADistinctEvidenceState:
    """A hypothetical bypass is not a bypass, so the document must say which it has."""

    def test_both_states_are_defined(self, assessment):
        assert "`declared`" in assessment
        assert "`demonstrated`" in assessment

    def test_a_declared_bypass_row_names_what_it_was_demonstrated_against(self, rows):
        """A bypass claim must carry its shape, or a specimen becomes a universal claim."""
        for rid, row in rows.items():
            if row["status"] == "unmediated-declared":
                assert row.get("availability_scope"), (
                    f"{rid} asserts a bypass without saying what environment it was "
                    "demonstrated in, which lets the claim travel further than the evidence"
                )

    def test_the_demonstration_is_executable_and_named(self, assessment):
        """If the verdict rests on an observation, the observation has to be runnable."""
        assert "tests/test_unmediated_path_demonstrated.py" in assessment
        assert (ROOT / "tests" / "test_unmediated_path_demonstrated.py").exists()
