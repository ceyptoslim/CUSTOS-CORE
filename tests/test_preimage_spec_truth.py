"""The written preimage formula must match the one the code computes.

Three times in two days a second copy of the record-hash preimage drifted from
the canonical one:

  1. `custos/custody.py` recomputed it from six fields and reported
     CONTRADICTION for stores that were fine (fixed in #72).
  2. `scripts/red-proof/custody_attack.py` carried its own stale copy, so the
     "consistent rewrite" attack was caught one layer early and reported
     FAULTY-GREEN (fixed in #76).
  3. `docs/design/EABC-PROFILE.md` published a formula missing `binding` and
     `trace_id`, which an independent implementer would have copied (#78).

Unit tests caught none of these, because each copy was internally consistent.
The guard below does not re-derive the preimage either: it intercepts the dict
the implementation actually passes to `json.dumps` and compares that against the
field list published in the profile. Interception, not duplication, is the point.
"""
import re
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import custos.audit as audit

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "docs/design/EABC-PROFILE.md"

# Every field the emitter can write, so the captured payload is maximal.
FULL_RECORD = {
    "timestamp": "2026-10-29T19:00:00Z",
    "client_id": "client-a",
    "action": "payment_transfer",
    "triggered_rule": "rule-allow",
    "reason": "allowed by policy",
    "content_hash": "abc123",
    "policy_digest": "def456",
    "tenant_id": "tenant-a",
    "binding_version": 1,
    "trace_id": "trace-xyz",
}


def _capture_preimage() -> dict:
    """Return the dict the implementation hands to json.dumps. Never rebuilt here."""
    captured = {}

    def spy(payload, *args, **kwargs):
        captured["payload"] = payload
        return "{}"

    with mock.patch.object(audit, "json", SimpleNamespace(dumps=spy)):
        audit.compute_record_hash(FULL_RECORD, "prev-hash")

    assert "payload" in captured, (
        "compute_record_hash did not call json.dumps on a dict — the preimage may "
        "have been refactored. Update this guard rather than deleting it."
    )
    return captured["payload"]


def _documented_fields() -> tuple:
    """Parse the published formula into (required, optional) field names."""
    text = PROFILE.read_text(encoding="utf-8")
    matches = re.findall(r"canonical_json\{(.*?)\}", text, re.S)
    assert len(matches) == 1, (
        f"EABC-PROFILE.md must publish exactly one preimage formula, found {len(matches)}"
    )
    body = matches[0]
    optional = set()
    for group in re.findall(r"\[(.*?)\]", body, re.S):
        for name in group.split(","):
            name = name.strip()
            if name:
                optional.add(name)
    required = {
        name.strip()
        for name in re.sub(r"\[.*?\]", "", body, flags=re.S).split(",")
        if name.strip()
    }
    return required, optional


def test_documented_preimage_matches_implementation():
    required, optional = _documented_fields()
    actual = set(_capture_preimage())

    documented = required | optional
    missing_from_docs = actual - documented
    documented_but_absent = documented - actual

    assert not missing_from_docs, (
        "The implementation hashes fields the published formula does not mention: "
        f"{sorted(missing_from_docs)}. An independent implementer reading "
        "docs/design/EABC-PROFILE.md would compute a different hash than the emitter."
    )
    assert not documented_but_absent, (
        "The published formula lists fields the implementation never hashes: "
        f"{sorted(documented_but_absent)}. The document is describing a preimage that "
        "does not exist."
    )


def test_conditional_fields_match_their_marker():
    """`binding` and `trace_id` appear together, only at binding version >= 1."""
    legacy = dict(FULL_RECORD)
    legacy.pop("binding_version")
    captured = {}

    def spy(payload, *args, **kwargs):
        captured["payload"] = payload
        return "{}"

    with mock.patch.object(audit, "json", SimpleNamespace(dumps=spy)):
        audit.compute_record_hash(legacy, "prev-hash")

    payload = captured["payload"]
    assert "binding" not in payload, "a version-0 record must not carry a binding marker"
    assert "trace_id" not in payload, (
        "trace_id must not enter the version-0 preimage; legacy records must hash "
        "byte-identically to their original definition"
    )


# Field names that only appear together inside a record-hash preimage.
PREIMAGE_FIELDS = {
    "timestamp",
    "client_id",
    "action",
    "triggered_rule",
    "reason",
    "content_hash",
    "previous_hash",
}


def _builds_preimage(path: Path) -> bool:
    """True if the file contains a dict literal assembling the preimage itself.

    Detection is structural (AST), not textual: `custody.py` legitimately reads
    `rec.get("previous_hash")` while re-walking a chain, and a grep for the field
    name cannot tell reading from re-deriving.
    """
    import ast

    tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        keys = {
            k.value
            for k in node.keys
            if isinstance(k, ast.Constant) and isinstance(k.value, str)
        }
        # `previous_hash`/`content_hash` are the discriminating fields: a
        # decision-result dict may share generic names like `action` and `reason`,
        # but only a preimage chains the previous digest against the content hash.
        if not keys & {"previous_hash", "content_hash"}:
            continue
        if len(keys & PREIMAGE_FIELDS) >= 3:
            return True
    return False


def test_no_second_preimage_implementation():
    """No module outside the canonical one may build the preimage itself."""
    offenders = []
    candidates = list((ROOT / "custos").rglob("*.py")) + list((ROOT / "scripts").rglob("*.py"))
    for path in candidates:
        if path == ROOT / "custos/audit.py":
            continue
        if _builds_preimage(path):
            offenders.append(str(path.relative_to(ROOT)))
    assert not offenders, (
        "Modules appear to construct the record-hash preimage themselves: "
        f"{offenders}. Import compute_record_hash instead — every duplicate copy so "
        "far has gone stale and produced a false verdict."
    )


def test_custody_and_attacker_import_the_canonical_hash():
    """The two consumers whose duplicate copies caused real failures."""
    custody = (ROOT / "custos/custody.py").read_text(encoding="utf-8")
    attacker = (ROOT / "scripts/red-proof/custody_attack.py").read_text(encoding="utf-8")
    assert "from custos.audit import" in custody and "compute_record_hash" in custody, (
        "custos/custody.py must import the canonical hash definition"
    )
    assert "compute_record_hash" in attacker, (
        "scripts/red-proof/custody_attack.py must import the canonical hash definition; "
        "a private copy made the attack weaker than the verifier (#76)"
    )
