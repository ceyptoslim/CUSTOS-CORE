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
REQUIRED = {"id", "name", "effect", "status", "assertion", "enforcement_point",
            "evidence", "binding_fields", "falsification_condition", "detection_signal"}


def flat_doc() -> str:
    """The doc with wrapping removed, so prose checks do not depend on line breaks."""
    return " ".join(DOC.read_text(encoding="utf-8").split()).lower()


@pytest.fixture(scope="module")
def inv():
    return yaml.safe_load(INVENTORY.read_text(encoding="utf-8"))


def test_inventory_and_doc_exist():
    assert INVENTORY.is_file()
    assert DOC.is_file()


def test_schema_version_is_pinned(inv):
    assert inv["inventory"]["schema"] == 2


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


def test_every_row_states_an_assertion_and_a_falsification_condition(inv):
    for row in inv["paths"]:
        assert len(row["assertion"].strip()) > 30, f"{row['id']} asserts nothing checkable"
        assert len(row["falsification_condition"].strip()) > 40, f"{row['id']} falsification too thin"


def test_falsification_is_not_a_detection_signal(inv):
    """A signal that something happened is not an observation that the claim is false."""
    for row in inv["paths"]:
        assert row["falsification_condition"].strip() != row["detection_signal"].strip(), (
            f"{row['id']} uses one text for both"
        )


def test_unmediated_rows_are_falsified_by_enumeration_not_by_an_effect(inv):
    """EX-4 asserts that a path exists. Only showing every path is mediated refutes it."""
    rows = [r for r in inv["paths"] if r["status"] == "unmediated-declared"]
    assert rows, "EX-4 must stay a declared row"
    for row in rows:
        text = row["falsification_condition"].lower()
        assert "every path" in text, f"{row['id']} does not require enumeration to falsify"
        assert "mediate" in text, f"{row['id']} does not require mediation to be shown"
        detected = row["detection_signal"].lower()
        assert "finding" in detected or "investigate" in detected, (
            f"{row['id']} presents its detection signal as a falsifier"
        )


def test_protected_effect_is_defined_before_anything_is_excluded(inv):
    """An exclusion is unfalsifiable until a reviewer knows what is protected."""
    effect = inv["protected_effect"]
    assert len(effect["statement"].strip()) > 60
    assert effect["in_scope"], "no in-scope classes"
    assert effect["out_of_scope"], "no out-of-scope classes"
    for item in effect["out_of_scope"]:
        assert item.get("class", "").strip()
        assert item.get("why", "").strip(), f"{item.get('class')} excluded without a reason"


def test_scope_states_what_the_declaration_covers(inv):
    scope = inv["scope"]
    assert len(scope["covers"].strip()) > 40
    assert scope["excludes"]
    assert "attestation" in scope["completeness"]


def test_out_of_scope_rows_are_covered_by_the_definition(inv):
    """P5 is only reviewable if the protected effect excludes it explicitly."""
    excluded = " ".join(i["class"].lower() for i in inv["protected_effect"]["out_of_scope"])
    assert "custody" in excluded or "anchoring" in excluded


def test_binding_is_declared_implemented_but_not_established(inv):
    binding = inv["binding"]
    assert binding["mechanism_status"] == "implemented"
    assert binding["established_at_runtime"] is False
    assert (ROOT / binding["mechanism"]).exists(), "named mechanism does not exist"
    said = binding["how_a_reviewer_tells"].lower()
    assert "establishes no" in said or "establishes nothing" in said


def test_payload_coverage_names_descriptors_runtime_credential_and_config(inv):
    coverage = inv["binding"]["payload_coverage"]
    assert "input schema" in coverage["tool_identity"].lower()
    assert "runtime" in coverage["credential"].lower()
    assert "secret_config_fields" in coverage["config"]


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


def test_the_doc_defines_the_protected_effect_before_the_rows():
    """A reviewer must be able to judge an exclusion from the document alone."""
    text = DOC.read_text(encoding="utf-8")
    assert "## What is protected, and against what" in text
    assert "durability of evidence, not an agent action" in flat_doc()


def test_the_doc_separates_falsification_from_detection():
    text = DOC.read_text(encoding="utf-8")
    assert "## Falsification is not detection" in text
    assert "detection signal" in flat_doc()
    assert "consistent with exactly the world the row asserts" in flat_doc()


def test_the_doc_keeps_implemented_and_established_apart():
    text = DOC.read_text(encoding="utf-8")
    assert "## Implemented mechanism versus established binding" in text
    assert "establishes no record for anything" in flat_doc()
    assert "unwired" in flat_doc()


def test_the_doc_requires_capability_coverage_not_just_names():
    text = flat_doc()
    assert "tool_descriptor_digest" in text
    assert "input schema" in text
    assert "runtime-connection" in text
    assert "secret_config_fields" in text


def test_the_payload_fields_in_the_doc_match_the_module():
    """Documentation that lists a payload the code does not build is a claim, not evidence."""
    sys.path.insert(0, str(ROOT))
    from custos.deployment_binding import build_payload

    payload = build_payload(
        deployment_id="d",
        build_commit="abc1234",
        transport="stdio",
        upstream_command="up",
        tool_descriptors=[{"name": "t"}],
        runtime_credential="token",
        config={"timeout": 1, "CUSTOS_JWT": "secret"},
        entry_ids=["P1"],
    )
    text = DOC.read_text(encoding="utf-8")
    for field in payload:
        assert field in text, f"doc omits payload field {field}"
