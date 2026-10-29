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


def test_vocabulary_is_closed():
    """A new class must be a deliberate contract change, not a local invention."""
    found = list(_sections())
    assert found == CLASSES, (
        f"register classes are {found}, expected {CLASSES}. Adding a class locally makes two "
        "profiles incomparable; propose it to the contract first."
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
