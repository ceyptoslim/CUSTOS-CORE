"""The exit-class register must keep a shape a stranger can check.

The argument for the register is that exit coverage is comparable across
implementations when the *unit* has a fixed meaning. That holds only while every
entry carries the same fields, uses the same three statuses, and can be traced to
an artifact that exists. All three degrade silently in prose, so they are asserted
here instead.
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
REGISTER = ROOT / "docs/design/EABC-EXIT-CLASS-REGISTER.md"

CLASSES = ["EX-1 suppression", "EX-2 substitution", "EX-3 attribution", "EX-4 coverage"]
REQUIRED_FIELDS = [
    "Boundary.",
    "Failure mode.",
    "Declared status.",
    "Threat model assumed.",
    "Artifact.",
    "Falsification condition.",
]
STATUSES = {"demonstrated-closed", "declared-open", "out-of-scope-by-construction"}


def _sections() -> dict:
    text = REGISTER.read_text(encoding="utf-8")
    parts = re.split(r"\n### ", text)
    return {p.splitlines()[0].strip(): p for p in parts[1:]}


def _field(section: str, label: str) -> str:
    match = re.search(rf"\*\*{re.escape(label)}\*\*\s*(.+?)(?=\n\n|\Z)", section, re.S)
    return match.group(1).strip() if match else ""


def test_vocabulary_is_stable_across_profiles():
    """The list is closed for comparability, not because four is the true number.

    This test prevents a class appearing in one profile and being compared against
    another profile that never heard of it. It cannot tell you the list is complete,
    and the register says so in its own text: adding a class is a deliberate revision
    (see "Revision procedure for a fifth class"), not a local convenience.
    """
    found = list(_sections())
    assert found == CLASSES, (
        f"register classes are {found}, expected {CLASSES}. Changing the vocabulary is allowed, "
        "but only deliberately: update the list, the mapping table and this test in one commit, "
        "and say why the new class names a failure the existing ones cannot. The green build "
        "enforces shape, never completeness."
    )


def _mapping_rows() -> dict:
    text = REGISTER.read_text(encoding="utf-8")
    section = re.search(
        r"## Mapping to EABC v1 properties and evidence requirements(.*?)\n## ", text, re.S
    )
    assert section, "the mapping section is missing"
    rows = {}
    for line in section.group(1).splitlines():
        match = re.match(r"\|\s*`(EX-\d [a-z]+)`\s*\|", line.strip())
        if match:
            rows[match.group(1)] = line
    return rows


@pytest.mark.parametrize("name", CLASSES)
def test_every_class_is_mapped_to_eabc_properties(name):
    """A class with no EABC mapping would be a parallel conformance model."""
    rows = _mapping_rows()
    assert name in rows, f"{name} has no row in the EABC mapping table"
    row = rows[name]
    assert re.search(r"P[1-9]\b", row), f"{name} is mapped to no EABC property"
    cells = [c.strip() for c in row.strip().strip("|").split("|")]
    assert len(cells) >= 5, (
        f"{name} mapping row is missing a column: expected class, properties, evidence, "
        f"existing coverage and what it adds, got {len(cells)} cells"
    )
    assert all(cells[1:]), f"{name} has an empty mapping cell; state what it constrains and adds"


def test_mapping_does_not_introduce_a_parallel_model():
    """The mapping must cite the contract, not scores, levels or arithmetic."""
    text = REGISTER.read_text(encoding="utf-8")
    section = re.search(
        r"## Mapping to EABC v1 properties and evidence requirements(.*?)\n## ", text, re.S
    ).group(1)
    lowered = section.lower()
    forbidden = [w for w in ("conformance level", "weighted total", "aggregate score") if w in lowered]
    assert not forbidden, (
        f"the mapping section introduces aggregation vocabulary {forbidden}. A set of closed "
        "exits does not imply a level; the register makes scope comparable and stops there."
    )
    assert "adds no levels" in lowered, (
        "the mapping section must state in its own words that it introduces no levels, scores "
        "or aggregation — the disclaimer is what keeps it from becoming a parallel model"
    )


def test_revision_procedure_exists():
    text = REGISTER.read_text(encoding="utf-8")
    assert "## Revision procedure for a fifth class" in text, (
        "without a stated revision route, a vocabulary enforced by CI reads as a claim of "
        "exhaustiveness, which it is not"
    )
    assert "Closed for comparability, not for truth" in text, (
        "the register must say in its own words that CI enforces shape, not completeness"
    )


@pytest.mark.parametrize("name", CLASSES)
def test_every_class_declares_the_required_fields(name):
    section = _sections()[name]
    missing = [f for f in REQUIRED_FIELDS if not _field(section, f)]
    assert not missing, f"{name} is missing required fields: {missing}"


@pytest.mark.parametrize("name", CLASSES)
def test_statuses_come_from_the_closed_vocabulary(name):
    section = _sections()[name]
    declared = set(re.findall(r"`([a-z-]+)`", _field(section, "Declared status.")))
    assert declared, f"{name} declares no status in backticks"
    unknown = declared - STATUSES
    assert not unknown, f"{name} uses statuses outside the vocabulary: {sorted(unknown)}"


@pytest.mark.parametrize("name", CLASSES)
def test_closure_claims_cite_existing_artifacts(name):
    section = _sections()[name]
    artifact_field = _field(section, "Artifact.")
    cited = [c for c in re.findall(r"`([^`]+)`", artifact_field) if "/" in c and "://" not in c]
    assert cited, f"{name} cites no repository artifact"
    # GitHub links and run URLs are evidence too, but at least one citation must be
    # a file in this tree that a reader can open offline.
    # Every cited path must exist. A register that cites a file nobody can open is
    # a claim with an address that does not deliver, which is worse than no address.
    missing = [c for c in cited if not (ROOT / c).exists()]
    assert not missing, f"{name} cites artifacts that do not exist: {missing}"


@pytest.mark.parametrize("name", CLASSES)
def test_falsification_conditions_say_something(name):
    condition = _field(_sections()[name], "Falsification condition.")
    assert len(condition) > 60, (
        f"{name} has a falsification condition too short to name a failure: {condition!r}"
    )


def test_out_of_scope_requires_an_architectural_argument():
    """The label most able to hide a missing test must never stand alone."""
    text = REGISTER.read_text(encoding="utf-8")
    assert "out-of-scope-by-construction" in text, (
        "the register no longer demonstrates the out-of-scope standard; the worked example is "
        "the part that shows the label requires an argument"
    )
    argument = re.search(r"## What \"out of scope by construction\" requires(.*?)\n## ", text, re.S)
    assert argument, "the architectural-argument section is missing"
    body = argument.group(1)
    assert "*Architectural argument:*" in body, (
        "out-of-scope entries must carry an explicit architectural argument, not just a status"
    )
    assert "*Falsification condition for the declaration itself:*" in body, (
        "an out-of-scope declaration must say what would show it was mistaken"
    )
