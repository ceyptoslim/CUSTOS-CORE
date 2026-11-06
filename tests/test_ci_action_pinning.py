"""
Every action a workflow runs is pinned to a commit, not to a moving tag.

The failure this prevents: a major-version tag such as `v4` is a branch
pointer the upstream repository moves whenever it ships. A workflow that
says `@v4` therefore executes whatever code that tag points at on the day
it runs, which is a supply-chain change no commit in this repository
records. The committee reviewing this project asked for the pins; this
test is what keeps them from drifting back.
"""

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"

# `uses: owner/repo[/path]@ref`. A ref is acceptable only as a full 40-hex
# commit sha; local actions (./...) and docker:// references are out of scope
# because neither resolves through a mutable upstream tag.
USES_RE = re.compile(r"^\s*-?\s*uses:\s*(\S+)", re.M)
SHA_RE = re.compile(r"^[^@]+@([0-9a-f]{40})$")
FLOATING_RE = re.compile(r"^[^@]+@v\d+(\.\d+)*$")


def _uses():
    files = sorted(WORKFLOWS.glob("*.yml"))
    assert files, "no workflow files found, so this guard would pass vacuously"
    found = []
    for path in files:
        for raw in USES_RE.findall(path.read_text(encoding="utf-8")):
            found.append((path.name, raw.strip().strip("\"'")))
    assert found, "no uses: entries found in any workflow"
    return found


def test_every_external_action_is_pinned_to_a_commit():
    unpinned = []
    for name, ref in _uses():
        if ref.startswith("./") or ref.startswith("docker://"):
            continue
        if SHA_RE.match(ref):
            continue
        unpinned.append(f"{name}: {ref}")
    assert not unpinned, "workflow actions not pinned to a commit sha:\n  " + "\n  ".join(unpinned)


def test_no_action_reference_floats_on_a_version_tag():
    floating = [f"{n}: {r}" for n, r in _uses() if FLOATING_RE.match(r)]
    assert not floating, "workflow actions still reference a moving tag:\n  " + "\n  ".join(floating)


def test_each_pinned_line_records_the_release_it_resolves_to():
    """A bare sha is unreadable to a reviewer, so the version must ride along."""
    missing = []
    for path in sorted(WORKFLOWS.glob("*.yml")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if "uses:" not in line or "actions/" not in line:
                continue
            if not re.search(r"@[0-9a-f]{40}\b", line):
                continue
            if not re.search(r"#\s*v\d+\.\d+\.\d+", line):
                missing.append(f"{path.name}: {line.strip()}")
    assert not missing, "pinned action lines without a release comment:\n  " + "\n  ".join(missing)
