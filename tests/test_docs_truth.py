"""Documentation truth guards.

The failure this prevents is specific and recent: README advertised "550 passed"
while the suite was at 571, and its own claims table stated a different coverage
figure than its header. Every number was plausible; two of them were wrong.

Static checks (always run, environment independent):

  1. There is one canonical test count, and NOTICE plus the README claims table
     agree with the README verified line.
  2. The verified line carries a date and a commit, because "571 passed" without
     a commit is a claim with no address.
  3. No other document states a competing *current* count. Historical statements
     (CHANGELOG releases, dated essays, frozen red-proof records) are exempt by
     design: retro-editing those would falsify the record.

Optional live check (skipped unless CUSTOS_TEST_COUNT_STRICT=1): the canonical
count must match the suite actually collected and passed in THIS environment. It
is opt-in because collection differs by environment (the red-proof workflow
collects integration tests that local runs skip), and a guard that fails for
environmental reasons teaches people to ignore guards.
"""
import os
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# Documents whose counts describe the current state and must agree.
CURRENT_DOCS = [
    "README.md",
    "NOTICE.md",
    "ARCHITECTURE.md",
]

# Historical or machine-generated records: exempt from the drift check.
EXEMPT_PREFIXES = (
    "CHANGELOG.md",
    "docs/essays/",
    "docs/history/",
    "docs/red-proof-records/",
    "docs/benchmarks/",
)

PASSED_RE = re.compile(r"\*\*Tests:\*\*\s*(\d+)\s+passed,\s*(\d+)\s+skipped")
COVERAGE_RE = re.compile(r"\*\*Coverage:\*\*\s*(\d+)%")
VERIFIED_RE = re.compile(
    r"\*\*Verified:\*\*\s*(\d{4}-\d{2}-\d{2}).*?\(`([0-9a-f]{7,40})`\)"
)
NOTICE_RE = re.compile(r"Test suite \((\d+) tests")
CLAIMS_ROW_RE = re.compile(r'"(\d+) tests, (\d+)% coverage"')
GENERIC_COUNT_RE = re.compile(r"(\d{3,5})\s+(?:passed|tests)\b")


def _read(rel: str) -> str:
    path = ROOT / rel
    if not path.exists():
        pytest.skip(f"{rel} not present in this checkout")
    return path.read_text(encoding="utf-8")


def _canonical_count() -> int:
    match = PASSED_RE.search(_read("README.md"))
    assert match, "README verified line must state '<N> passed, <M> skipped'"
    return int(match.group(1))


def test_readme_verified_line_is_dated_and_addressed():
    readme = _read("README.md")
    match = VERIFIED_RE.search(readme)
    assert match, (
        "README verified line must include a date and a commit SHA, e.g. "
        "**Verified:** 2026-10-29 live run on `main` (`dabc2ca`)"
    )
    date, sha = match.group(1), match.group(2)
    assert len(sha) >= 7
    # A date in the future means someone typed it instead of measuring it.
    today = subprocess.run(
        ["date", "-u", "+%Y-%m-%d"], capture_output=True, text=True, check=False
    ).stdout.strip()
    if today:
        assert date <= today, f"README verified date {date} is in the future"


def test_notice_agrees_with_readme():
    canonical = _canonical_count()
    notice = _read("NOTICE.md")
    match = NOTICE_RE.search(notice)
    assert match, "NOTICE.md must state 'Test suite (<N> tests, ...)'"
    assert int(match.group(1)) == canonical, (
        f"NOTICE.md says {match.group(1)} tests, README says {canonical}. "
        "One of them is stale."
    )


def test_readme_claims_table_agrees_with_header():
    readme = _read("README.md")
    canonical = _canonical_count()
    cov_header = COVERAGE_RE.search(readme)
    assert cov_header, "README verified line must state coverage"
    rows = CLAIMS_ROW_RE.findall(readme)
    assert rows, "README claims table must include the CUSTOS-CORE row"
    count, cov_row = rows[0]
    assert int(count) == canonical, (
        f"claims table says {count} tests, header says {canonical}"
    )
    assert cov_row == cov_header.group(1), (
        f"claims table says {cov_row}% coverage, header says {cov_header.group(1)}%. "
        "The header and the claims table contradicted each other once already."
    )


def test_no_competing_current_counts_elsewhere():
    """Any other current doc that states a count must state the canonical one."""
    canonical = _canonical_count()
    offenders = []
    for path in ROOT.rglob("*.md"):
        rel = path.relative_to(ROOT).as_posix()
        if rel in CURRENT_DOCS or rel.startswith(EXEMPT_PREFIXES):
            continue
        if rel.startswith(".git/"):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for number in GENERIC_COUNT_RE.findall(text):
            if int(number) != canonical:
                offenders.append(f"{rel}: claims {number} (canonical {canonical})")
    assert not offenders, (
        "Documents state a test count that disagrees with README:\n  "
        + "\n  ".join(offenders)
        + "\nIf the number is historical, move the claim under a dated heading "
        "(CHANGELOG, docs/essays, docs/history) so it is exempt by design."
    )


@pytest.mark.skipif(
    os.getenv("CUSTOS_TEST_COUNT_STRICT") != "1",
    reason="live count check is environment dependent; set CUSTOS_TEST_COUNT_STRICT=1 to enable",
)
def test_canonical_count_matches_this_environment():
    """Opt-in: README's number must match what this environment actually passes."""
    canonical = _canonical_count()
    out = subprocess.run(
        ["python3", "-m", "pytest", "--collect-only", "-q"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    collected = sum(1 for line in out.splitlines() if "::" in line)
    assert collected >= canonical, (
        f"README claims {canonical} passed but only {collected} tests collect. "
        "The documented number is ahead of the suite."
    )
