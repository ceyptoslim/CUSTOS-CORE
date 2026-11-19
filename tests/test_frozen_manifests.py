"""
Frozen observation-set integrity guards (Nov 2026).

The red-proof records under docs/red-proof-records/run-*/ are frozen: each
directory holds the uploaded CI artifacts plus a MANIFEST.md that pins every
file by SHA-256. That pin is what lets a reader re-walk the observation set
after GitHub expires the workflow artifacts.

On 17 November 2026 a documentation PR edited run 38610363998's README.md,
which that run's own MANIFEST.md pins at fc9d18d8. Nothing failed: the PR was
green, and the only thing that caught it was a person recomputing hashes by
hand before merge. A frozen set that a passing PR can silently invalidate is
not frozen, so these tests make the pin enforceable.

Rules enforced:
1. Every file inside a frozen run directory is listed in that run's manifest.
2. Every manifest entry whose file is present matches by SHA-256.
3. A manifest entry may name a repository file at a historical commit
   ("... (at <sha>)"). Those are not in the run directory and are skipped
   here; they are verified against the named commit, not against the tree.

The manifests were written by hand over several months and use three shapes:
sha256sum output with paths relative to the run directory, sha256sum output
with paths relative to the repository root, and markdown tables whose paths
are either bare filenames under a heading or run-prefixed. All three are
parsed here, because a guard that quietly skips a format is worse than none.

Adding a file to a frozen directory therefore fails, editing a pinned file
fails, and deleting one fails. New observation sets are added as new run
directories with their own manifests, never by rewriting an old one.
"""
# Copyright (C) 2024-2026 Tavares Heath Sr. (doing business as FroLife Productions)
# Licensed under the GNU Affero General Public License v3.0 (AGPL-3.0)

import hashlib
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RECORDS = ROOT / "docs" / "red-proof-records"

# Files that exist inside a frozen directory but are not pinned by its
# manifest. Each entry is a known gap in that set, not a parser limitation.
# Removing a name from this set is the test for whether the gap was closed.
KNOWN_UNPINNED = set()
# Empty, and it should stay empty. Run 40937305618's README was the only entry
# here; its pin was appended to that manifest on 2026-11-19 and this entry was
# removed in the same commit, which is the test for whether a gap was closed.
# docs/red-proof-records/PIN-GAPS.md carries the record, including that
# manifest's before and after digest.

_DIGEST = re.compile(r"[0-9a-f]{64}")
_SHA256SUM_LINE = re.compile(r"^([0-9a-f]{64})\s+(.+)$")
_BACKTICKED = re.compile(r"`([^`]+)`")
_HEADING = re.compile(r"^#{2,4}\s+`?([A-Za-z0-9._-]+)/?`?\s*$")
_HISTORICAL = re.compile(r"\(at\s+([0-9a-f]{7,40})\)")


def _run_dirs():
    if not RECORDS.is_dir():
        return []
    return sorted(
        p for p in RECORDS.iterdir()
        if p.is_dir() and p.name.startswith("run-") and (p / "MANIFEST.md").is_file()
    )


def _normalize(rel, run_name, heading, title_class, subdirs, run_dir):
    """Reduce a manifest path to one relative to the run directory, or None."""
    rel = rel.strip().strip("`").lstrip("./")
    for prefix in (f"docs/red-proof-records/{run_name}/", f"{run_name}/", "Contents/"):
        if rel.startswith(prefix):
            rel = rel[len(prefix):]

    if "/" not in rel:
        if heading:
            rel = f"{heading}/{rel}"
        elif title_class and title_class in subdirs:
            rel = f"{title_class}/{rel}"
        elif not (run_dir / rel).is_file():
            return None
    return rel

_TITLE_CLASS = re.compile(r"Class\s+`([^`]+)`")


def _parse_manifest(path):
    """Return (entries, historical, unparsed) for one MANIFEST.md.

    entries maps run-relative path -> digest. historical lists repository-file
    pins that carry a commit. unparsed lists digest-bearing lines whose path
    could not be resolved, so a new manifest shape fails loudly instead of
    silently reducing what the guard checks.

    Bare filenames are resolved against what actually exists: the heading
    directory if the heading names one, else the class named in the title,
    else the run directory itself. A bare name that resolves to nothing and
    whose digest is already pinned elsewhere is a cross-reference table and is
    skipped; anything else is reported.
    """
    run_dir = path.parent
    run_name = run_dir.name
    subdirs = {d.name for d in run_dir.iterdir() if d.is_dir()}
    text = path.read_text(encoding="utf-8")

    title = _TITLE_CLASS.search(text.splitlines()[0] if text else "")
    title_class = title.group(1).strip("/") if title else None

    entries, historical, unparsed = {}, [], []
    heading = None
    seen_digests = set()

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue

        h = _HEADING.match(line)
        if h:
            name = h.group(1).strip("/")
            heading = name if name in subdirs else None
            continue
        if line.startswith("#"):
            continue

        digest = None
        rel = None

        m = _SHA256SUM_LINE.match(line)
        if m:
            digest, rel = m.group(1), m.group(2).strip()
        elif line.startswith("|"):
            found = _DIGEST.search(line)
            if not found:
                continue
            digest = found.group(0)
            tokens = [t for t in _BACKTICKED.findall(line) if not _DIGEST.fullmatch(t)]
            if tokens:
                rel = tokens[0].strip()
            else:
                cells = [c.strip().strip("`") for c in line.strip("|").split("|")]
                if cells and not _DIGEST.fullmatch(cells[0]):
                    rel = cells[0]
        else:
            continue

        if digest is None:
            continue

        hist = _HISTORICAL.search(line)
        if hist:
            historical.append((rel or "", digest, hist.group(1)))
            continue

        if rel is None:
            unparsed.append(line)
            continue

        rel = _normalize(rel, run_name, heading, title_class, subdirs, run_dir)
        if rel is None:
            if digest in seen_digests:
                continue
            unparsed.append(line)
            continue

        entries[rel] = digest
        seen_digests.add(digest)

    # A comparison table can restate digests already pinned by the class
    # tables (run 38495005061 has one quoting FactNotebook's Annex D). Those
    # rows add nothing and resolve nowhere, so they are dropped rather than
    # reported, but only when the digest is pinned elsewhere in this manifest.
    unparsed = [line for line in unparsed
                if not (_DIGEST.search(line) and _DIGEST.search(line).group(0) in seen_digests)]

    return entries, historical, unparsed


def _sha256(path):
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def test_frozen_run_directories_exist():
    """The series is present, so a silently emptied records tree fails loudly."""
    assert _run_dirs(), "no frozen run directories with a MANIFEST.md were found"


@pytest.mark.parametrize("run_dir", _run_dirs(), ids=lambda p: p.name)
def test_manifest_parses_completely(run_dir):
    entries, _, unparsed = _parse_manifest(run_dir / "MANIFEST.md")
    assert entries, f"{run_dir.name}: manifest parsed no entries"
    assert not unparsed, (
        f"{run_dir.name}: manifest lines carry a digest but no resolvable path, so the "
        f"guard cannot check them: {unparsed}"
    )


@pytest.mark.parametrize("run_dir", _run_dirs(), ids=lambda p: p.name)
def test_every_manifest_entry_matches_its_file(run_dir):
    entries, _, _ = _parse_manifest(run_dir / "MANIFEST.md")

    mismatches, missing = [], []
    for rel, expected in sorted(entries.items()):
        target = run_dir / rel
        if not target.is_file():
            missing.append(rel)
            continue
        actual = _sha256(target)
        if actual != expected:
            mismatches.append(f"{rel}: manifest {expected[:12]}, file {actual[:12]}")

    assert not missing, f"{run_dir.name}: listed but absent: {missing}"
    assert not mismatches, (
        f"{run_dir.name}: pinned files changed. A frozen set must be superseded by a new "
        f"run directory, not edited. {mismatches}"
    )


@pytest.mark.parametrize("run_dir", _run_dirs(), ids=lambda p: p.name)
def test_every_file_in_a_frozen_directory_is_pinned(run_dir):
    entries, _, _ = _parse_manifest(run_dir / "MANIFEST.md")

    unlisted = []
    for path in sorted(run_dir.rglob("*")):
        if not path.is_file() or path.name == "MANIFEST.md":
            continue
        rel = path.relative_to(run_dir).as_posix()
        if rel not in entries and (run_dir.name, rel) not in KNOWN_UNPINNED:
            unlisted.append(rel)

    assert not unlisted, (
        f"{run_dir.name}: files present but not pinned by the manifest: {unlisted}. "
        f"An unpinned file in a frozen set is invisible to every re-walk."
    )


def test_historical_manifest_entries_name_a_commit():
    """Repo-file pins must carry the commit they were true at, or they cannot be checked."""
    for run_dir in _run_dirs():
        _, historical, _ = _parse_manifest(run_dir / "MANIFEST.md")
        for rel, digest, commit in historical:
            assert re.fullmatch(r"[0-9a-f]{7,40}", commit), (
                f"{run_dir.name}: {rel} names a malformed commit {commit!r}"
            )
            assert re.fullmatch(r"[0-9a-f]{64}", digest), (
                f"{run_dir.name}: {rel} has a malformed digest"
            )
