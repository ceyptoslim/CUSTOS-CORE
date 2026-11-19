"""
Anchor digest scheme tests (Nov 2026).

The scheme exists because a digest was published with a prose description that
did not reproduce it. A number is only citable if the procedure that produced it
is executable and pinned, so the canonical form lives in
`scripts/anchor_digest.sh` and these tests hold it still.

What is checked here:
1. The canonical form on a fixture whose expected digest is hardcoded, so a
   change to the script or to an independent implementation fails rather than
   silently redefining the number.
2. Determinism across runs.
3. The append-only rule against the epoch 0 record: anchored runs unchanged,
   new runs allowed, a tampered run and a missing run both caught.
4. The record's pinned script digest matches the script in the tree, so a scheme
   change cannot slip in under an old anchor.
"""
# Copyright (C) 2024-2026 Tavares Heath Sr. (doing business as FroLife Productions)
# Licensed under the GNU Affero General Public License v3.0 (AGPL-3.0)

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DIGEST = ROOT / "scripts" / "anchor_digest.sh"
CHECK = ROOT / "scripts" / "check_anchors.sh"
RECORDS = ROOT / "docs" / "red-proof-records"
EPOCH0 = ROOT / "docs" / "design" / "anchor-epoch-0.json"

# Computed once by an implementation independent of the script (python hashing
# "<sha256>  <relpath>" lines sorted bytewise, LF, trailing newline) and pinned.
FIXTURE_EXPECTED = "1a7bbf84ff34ef19e39d74519d7dae98b0945bbc12e04e174ea928ea5b1f6e4a"


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


@pytest.fixture()
def fixture_run(tmp_path):
    d = tmp_path / "run-fixture"
    (d / "sub").mkdir(parents=True)
    (d / "a.txt").write_bytes(b"alpha\n")
    (d / "b.txt").write_bytes(b"beta\n")
    (d / "sub" / "c.json").write_bytes(b'{"k": 1}\n')
    return d


class TestCanonicalForm:
    def test_fixture_matches_the_pinned_value(self, fixture_run):
        out = run(["bash", str(DIGEST), "per-run", str(fixture_run)])
        assert out.returncode == 0, out.stderr
        assert out.stdout.strip() == FIXTURE_EXPECTED, (
            "the canonical form moved; every anchored digest is now unreproducible "
            "without a new epoch"
        )

    def test_independent_implementation_agrees(self, fixture_run):
        lines = sorted(
            f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(fixture_run).as_posix()}"
            for p in fixture_run.rglob("*")
            if p.is_file()
        )
        expected = hashlib.sha256(("\n".join(lines) + "\n").encode()).hexdigest()
        out = run(["bash", str(DIGEST), "per-run", str(fixture_run)])
        assert out.stdout.strip() == expected

    def test_deterministic_across_runs(self):
        first = run(["bash", str(DIGEST), "aggregate", str(RECORDS)]).stdout
        second = run(["bash", str(DIGEST), "aggregate", str(RECORDS)]).stdout
        assert first == second != ""

    def test_what_moves_the_digest_and_what_is_refused(self, fixture_run):
        before = run(["bash", str(DIGEST), "per-run", str(fixture_run)]).stdout

        # Content moves it.
        (fixture_run / "a.txt").write_bytes(b"alpha\n\n")
        after = run(["bash", str(DIGEST), "per-run", str(fixture_run)]).stdout
        assert before != after

        # File mode does not: only bytes are hashed.
        (fixture_run / "a.txt").chmod(0o600)
        assert run(["bash", str(DIGEST), "per-run", str(fixture_run)]).stdout == after

        # A symlink is refused before anything is printed, because `find -type f`
        # skips it while a path resolver follows it, and the two answers differ.
        (fixture_run / "link.txt").symlink_to("a.txt")
        out = run(["bash", str(DIGEST), "per-run", str(fixture_run)])
        assert out.returncode == 3, out.stdout + out.stderr
        assert out.stdout.strip() == "", "a refusal must not emit a digest"
        assert "symlink inside a frozen directory" in out.stderr


class TestEpochRecord:
    def test_record_parses_and_names_every_anchored_run(self):
        rec = json.loads(EPOCH0.read_text())
        assert rec["epoch"] == 0
        assert rec["prev_anchor_hash"] == ""
        assert rec["source_commit"]
        assert set(rec["run_digests"]) == {
            d.name for d in RECORDS.iterdir() if d.is_dir() and d.name.startswith("run-")
        }
        assert len(rec["aggregate"]) == 64

    def test_pinned_script_digest_matches_the_tree(self):
        rec = json.loads(EPOCH0.read_text())
        actual = hashlib.sha256(DIGEST.read_bytes()).hexdigest()
        assert rec["scheme"]["script_sha256"] == actual, (
            "the digest scheme changed; anchor a new epoch rather than editing epoch 0"
        )

    def test_aggregate_matches_the_listing(self):
        rec = json.loads(EPOCH0.read_text())
        assert run(["bash", str(DIGEST), "aggregate", str(RECORDS)]).stdout.strip() == rec["aggregate"]


class TestAppendOnlyRule:
    def test_clean_tree_passes(self):
        out = run(["bash", str(CHECK), str(EPOCH0), str(RECORDS)])
        assert out.returncode == 0, out.stdout + out.stderr
        # The record it compared against is named, and named honestly: a green
        # run against the in-tree copy is not an external verification.
        assert "in-tree reference copy, not independent" in out.stdout, out.stdout

    def test_edited_run_fails(self, tmp_path):
        root = tmp_path / "records"
        root.mkdir()
        shutil.copytree(RECORDS / "run-41768306845", root / "run-41768306845")
        rec = tmp_path / "anchor.json"
        rec.write_text(json.dumps({
            "epoch": 0,
            "run_digests": {"run-41768306845": run(["bash", str(DIGEST), "per-run", str(root / "run-41768306845")]).stdout.strip()},
        }))
        assert run(["bash", str(CHECK), str(rec), str(root)]).returncode == 0
        (root / "run-41768306845" / "MANIFEST.md").write_bytes(b"tampered\n")
        out = run(["bash", str(CHECK), str(rec), str(root)])
        assert out.returncode == 1
        assert "CHANGED" in out.stdout

    def test_new_run_is_allowed(self, tmp_path):
        root = tmp_path / "records"
        root.mkdir()
        shutil.copytree(RECORDS / "run-41768306845", root / "run-41768306845")
        rec = tmp_path / "anchor.json"
        rec.write_text(json.dumps({
            "epoch": 0,
            "run_digests": {"run-41768306845": run(["bash", str(DIGEST), "per-run", str(root / "run-41768306845")]).stdout.strip()},
        }))
        (root / "run-99999999999").mkdir()
        (root / "run-99999999999" / "MANIFEST.md").write_bytes(b"new\n")
        out = run(["bash", str(CHECK), str(rec), str(root)])
        assert out.returncode == 0
        assert "new      run-99999999999" in out.stdout

    def test_missing_anchored_run_fails(self, tmp_path):
        root = tmp_path / "records"
        root.mkdir()
        rec = tmp_path / "anchor.json"
        rec.write_text(json.dumps({"epoch": 0, "run_digests": {"run-41946858235": "0" * 64}}))
        out = run(["bash", str(CHECK), str(rec), str(root)])
        assert out.returncode == 1
        assert "MISSING" in out.stdout

        # An external anchor that cannot be read fails closed. Falling back to
        # the in-tree copy would turn an unreachable anchor into a green run.
        missing = tmp_path / "no-such-anchor.json"
        out = run(["bash", str(CHECK), str(missing), str(root), "--origin", "external"])
        assert out.returncode == 2, out.stdout + out.stderr
        assert "refusing to fall back" in out.stdout + out.stderr


    def test_chain_label_is_earned_not_inferred(self, tmp_path):
        """An external path is not an external anchor until its chain walks to epoch 0."""
        chain = tmp_path / "chain"
        chain.mkdir()
        shutil.copy(EPOCH0, chain / "epoch-0.json")
        h0 = run(["bash", str(DIGEST), "anchor-hash", str(chain / "epoch-0.json")]).stdout.strip()
        rec1 = run(["bash", str(DIGEST), "record", str(RECORDS), "4a24cdb", "1", h0]).stdout
        (chain / "epoch-1.json").write_text(rec1)
        base = ["bash", str(CHECK), str(chain / "epoch-1.json"), str(RECORDS), "--origin", "external"]

        # Chain verified and the source stated: the label may be claimed.
        out = run(base + ["--chain", str(chain), "--chain-source", "custos-anchors@test"])
        assert out.returncode == 0, out.stdout + out.stderr
        assert "external anchor, chain verified to epoch 0" in out.stdout, out.stdout

        # Chain verified but no source stated: still not an external anchor.
        out = run(base + ["--chain", str(chain)])
        assert "external path, chain not verified" in out.stdout, out.stdout

        # A correctly linked epoch that carries a tampered digest must still fail.
        # This is the attack the link alone cannot see: the write token appends a
        # plausible epoch whose digest matches a rewritten tree.
        rec = json.loads(rec1)
        rec["run_digests"]["run-40937305618"] = "0" * 64
        (chain / "epoch-1.json").write_text(json.dumps(rec, indent=2))
        out = run(base + ["--chain", str(chain), "--chain-source", "custos-anchors@test"])
        assert out.returncode == 2, out.stdout + out.stderr
        assert "changes anchored run run-40937305618" in out.stdout + out.stderr

        # A broken link fails rather than degrading quietly.
        rec = json.loads(rec1)
        rec["prev_anchor_hash"] = "0" * 64
        (chain / "epoch-1.json").write_text(json.dumps(rec, indent=2))
        out = run(base + ["--chain", str(chain), "--chain-source", "custos-anchors@test"])
        assert out.returncode == 2, out.stdout + out.stderr
        assert "does not link to epoch" in out.stdout + out.stderr


class TestLineEndingGuard:
    def test_frozen_paths_have_no_text_conversion(self):
        out = run(
            ["git", "check-attr", "text", "--",
             str(RECORDS / "run-40937305618" / "README.md"),
             str(RECORDS / "run-38610363998" / "MANIFEST.md")],
            cwd=ROOT,
        )
        assert out.returncode == 0, out.stderr
        assert out.stdout.count("text: unset") == 2, (
            "a clone with end-of-line conversion would change frozen bytes and break "
            "every digest, including the manifests' own pins"
        )
