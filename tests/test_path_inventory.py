"""Guards on the path inventory: the declaration must stay checkable.

These tests do not check that the inventory is true. They check that it is the shape a
reviewer can falsify: statuses from the closed vocabulary, evidence that exists, a
falsification condition per row, and the EX-4 limit stated rather than implied.
"""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "docs" / "design" / "path-inventory.yaml"
DOC = ROOT / "docs" / "design" / "EXECUTION-PATH-INVENTORY.md"

STATUSES = {
    "mediated",
    "not-effect-producing",
    "not-present",
    "unmediated-declared",
    "out-of-scope-by-construction",
}
REQUIRED = {"id", "name", "effect", "status", "enforcement_point", "evidence",
            "binding_fields", "falsification"}


@pytest.fixture(scope="module")
def inv():
    return yaml.safe_load(INVENTORY.read_text(encoding="utf-8"))


def test_inventory_and_doc_exist():
    assert INVENTORY.is_file()
    assert DOC.is_file()


def test_schema_version_is_pinned(inv):
    assert inv["inventory"]["schema"] == 1


def test_every_row_carries_the_required_fields(inv):
    for row in inv["paths"]:
        missing = REQUIRED - set(row)
        assert not missing, f"{row.get('id')} missing {missing}"


def test_statuses_come_from_the_closed_vocabulary(inv):
    for row in inv["paths"]:
        assert row["status"] in STATUSES, f"{row['id']} uses an invented status"


def test_ids_are_unique_and_contiguous(inv):
    ids = [r["id"] for r in inv["paths"]]
    assert len(ids) == len(set(ids))
    assert ids == [f"P{i}" for i in range(1, len(ids) + 1)]


def test_every_cited_evidence_path_exists(inv):
    """A row whose evidence is a filename that does not exist is a claim, not evidence."""
    missing = []
    for row in inv["paths"]:
        for item in row["evidence"]:
            path = item.split(" (")[0].strip()
            if path.endswith(".py") or path.endswith(".md"):
                if not (ROOT / path).exists() and not (ROOT / "docs" / "design" / path).exists():
                    if not (ROOT / Path(path).name).exists():
                        missing.append(f"{row['id']} -> {path}")
    assert not missing, f"cited evidence not found: {missing}"


def test_mediated_rows_name_an_enforcement_point_and_evidence(inv):
    for row in inv["paths"]:
        if row["status"] == "mediated":
            assert row["enforcement_point"].strip()
            assert row["evidence"], f"{row['id']} claims mediation with no evidence"


def test_every_row_states_a_falsification_condition(inv):
    for row in inv["paths"]:
        assert len(row["falsification"].strip()) > 40, f"{row['id']} falsification too thin"


def test_the_unmediated_path_is_declared_not_hidden(inv):
    """EX-4 must appear as a row, so a reviewer sees the hole without reading a caveat."""
    statuses = {r["status"] for r in inv["paths"]}
    assert "unmediated-declared" in statuses


def test_the_inventory_declares_its_own_limit(inv):
    limit = inv["inventory"]["limit"].lower()
    assert "never connects" in limit or "cannot be enumerated" in limit


def test_the_doc_separates_the_three_claims():
    text = DOC.read_text(encoding="utf-8").lower()
    for claim in ("declared path coverage", "path mediation", "deployment binding"):
        assert claim in text
    assert "does not establish" in text


def test_the_doc_does_not_claim_completeness():
    text = DOC.read_text(encoding="utf-8").lower()
    assert "completeness" in text
    assert "green diff is consistent with a complete declaration" in text
