"""
Suite integrity meta-tests (Oct 2026).

A green CI is only meaningful if the tests inside it can fail. These
meta-tests verify the test suite itself, guarding against the failure
mode we have seen in the wild (the Pass-169 C6 specimen): test
functions that PRINT their findings while pytest happily counts green.

Rules enforced:
1. Every test function must contain at least one real assertion
   (assert, pytest.raises, pytest.warns, pytest.fail, or a unittest
   assert_* method).
2. No vacuous assertions on bare literals (assert True, assert 1).
3. No unconditional @pytest.mark.skip — a skip needs a reason string.
"""
# Copyright (C) 2024-2026 FroLife Productions
# Licensed under the GNU Affero General Public License v3.0 (AGPL-3.0)

import ast
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).parent

ASSERTING_CALLS = {"raises", "warns", "fail", "deals_with"}


def _test_functions(tree):
    """Yield (file, function) for every test function in the module."""
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test"):
            yield node


def _has_real_assertion(func):
    """True if the function body contains a real assertion."""
    for node in ast.walk(func):
        if isinstance(node, ast.Assert):
            return True
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in ASSERTING_CALLS
        ):
            return True
        # unittest-style self.assert_*(...)
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr.startswith("assert_")
        ):
            return True
        # response.raise_for_status() is a real check
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "raise_for_status"
        ):
            return True
    return False


def _has_vacuous_assert(func):
    """True if the function asserts a bare literal (always-true)."""
    for node in ast.walk(func):
        if (
            isinstance(node, ast.Assert)
            and isinstance(node.test, ast.Constant)
            and isinstance(node.test.value, bool)
            and node.test.value is True
        ):
            return True
    return False


def _has_unconditional_skip(func):
    """True if decorated with a bare @pytest.mark.skip (no reason)."""
    for deco in func.decorator_list:
        if (
            isinstance(deco, ast.Call)
            and isinstance(deco.func, ast.Attribute)
            and deco.func.attr == "skip"
        ):
            if not deco.args:  # skip() with no reason string
                return True
        if (
            isinstance(deco, ast.Attribute)
            and deco.attr == "skip"
        ):
            return True
    return False


def _iter_test_files():
    for path in sorted(TESTS_DIR.glob("test_*.py")):
        if path.name == Path(__file__).name:
            continue  # don't inspect ourselves recursively
        yield path, ast.parse(path.read_text())


class TestSuiteCanFail:
    """If these pass, every test in the suite is asserting something."""

    def test_every_test_function_makes_assertions(self):
        toothless = []
        for path, tree in _iter_test_files():
            for func in _test_functions(tree):
                if not _has_real_assertion(func):
                    toothless.append(f"{path.name}::{func.name}")
        assert not toothless, (
            "Test functions with NO real assertion found (print-only tests "
            "make CI green without proving anything):\n  "
            + "\n  ".join(toothless)
        )

    def test_no_vacuous_assert_true(self):
        vacuous = []
        for path, tree in _iter_test_files():
            for func in _test_functions(tree):
                if _has_vacuous_assert(func):
                    vacuous.append(f"{path.name}::{func.name}")
        assert not vacuous, (
            "Vacuous assert-True tests found (they can never fail):\n  "
            + "\n  ".join(vacuous)
        )

    def test_no_unconditional_skips(self):
        silent = []
        for path, tree in _iter_test_files():
            for func in _test_functions(tree):
                if _has_unconditional_skip(func):
                    silent.append(f"{path.name}::{func.name}")
        assert not silent, (
            "Unconditional @pytest.mark.skip found (a skip needs a reason):\n  "
            + "\n  ".join(silent)
        )

    def test_suite_size_floor(self):
        """Guard against accidental mass-deletion of tests: the suite must
        stay above a floor. Update the floor when the suite grows."""
        count = 0
        for path, tree in _iter_test_files():
            count += sum(1 for _ in _test_functions(tree))
        assert count >= 400, (
            f"Test function count dropped to {count} (< 400 floor) — "
            "tests may have been deleted"
        )

    def test_red_proof_workflow_produces_structured_records(self):
        """The red-proof CI must produce machine-readable evidence records:
        JUnit XML, a JSON evidence record binding the sabotage-script hash
        and commit SHA to the verdict, and artifact upload that persists
        records even on faulty-green. Guards against silent removal of the
        records pipeline (added Oct 2026; v3 fields added after external
        review FN-CUSTOS-REDPROOF-001, Oct 2026)."""
        import yaml

        wf_path = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "ci-red-proof.yml"
        assert wf_path.exists(), "ci-red-proof.yml missing"
        wf = yaml.safe_load(wf_path.read_text())

        run_step = next(
            (s for s in wf["jobs"]["red-proof"]["steps"]
             if isinstance(s, dict) and "junitxml" in str(s.get("run", ""))),
            None,
        )
        assert run_step is not None, (
            "red-proof run step must emit --junitxml (structured execution record)"
        )

        evidence_step = next(
            (s for s in wf["jobs"]["red-proof"]["steps"]
             if isinstance(s, dict) and "red-proof-evidence.json" in str(s.get("run", ""))),
            None,
        )
        assert evidence_step is not None, (
            "red-proof workflow must write red-proof-evidence.json"
        )
        evidence_src = evidence_step["run"]
        # v2 spec (external review, Oct 2026): identity, time, raw
        # observations kept separate from the verdict, provenance, and a
        # versioned rule mapping observations -> verdict.
        for field in ("run_id", "commit_sha", "injected_regression_id",
                      "sabotage_script_sha256", "injection_diff_sha256",
                      "tests_started_utc", "tests_completed_utc",
                      "record_generated_at_utc",
                      "observations", "pytest_exit_code", "junit_xml",
                      "junit_failures", "exit_code_artifact", "injection_diff",
                      "sha256", "ci_job_outcome",
                      "verdict", "expected", "actual", "rule", "version",
                      "mapping", "provenance", "workflow", "artifact"):
            assert f'"{field}"' in evidence_src, (
                f"evidence record must carry field: {field}"
            )
        # v3: record and rule versions must be bumped together
        assert '"record_version": 3' in evidence_src, (
            "evidence record must declare record_version 3"
        )
        # v3 (FN-CUSTOS-REDPROOF-001, proposition 4): the suite must run
        # WITHOUT -x so the JUnit records the full failure set of the
        # regression class, not just the first failure.
        assert " -x " not in run_step["run"], (
            "red-proof run step must not use -x: the full failure set "
            "must be recorded for regression-class coverage"
        )
        # v3: the post-injection diff must be sealed at run time
        # (contemporaneous, not merely replayable) and the exit code must
        # be echoed by the shell into an artifact independent of the
        # record that asserts it.
        assert "red-proof-injection-diff.patch" in evidence_src, (
            "evidence record must bind the sealed injection diff"
        )
        assert "red-proof-exit-code.txt" in evidence_src, (
            "evidence record must reference the independent exit-code artifact"
        )
        diff_step = next(
            (s for s in wf["jobs"]["red-proof"]["steps"]
             if isinstance(s, dict)
             and "red-proof-injection-diff.patch" in str(s.get("run", ""))),
            None,
        )
        assert diff_step is not None, (
            "red-proof workflow must seal the post-injection diff as an artifact"
        )

        upload_step = next(
            (s for s in wf["jobs"]["red-proof"]["steps"]
             if isinstance(s, dict) and s.get("uses", "").startswith("actions/upload-artifact")),
            None,
        )
        assert upload_step is not None, (
            "red-proof workflow must upload evidence artifacts"
        )
        assert upload_step.get("with", {}).get("if-no-files-found") == "error", (
            "artifact upload must fail when records are missing"
        )
        upload_path = str(upload_step.get("with", {}).get("path", ""))
        for artifact_file in ("red-proof-evidence.json", "red-proof-junit.xml",
                              "red-proof-pytest-output.txt",
                              "red-proof-injection-diff.patch",
                              "red-proof-exit-code.txt"):
            assert artifact_file in upload_path, (
                f"artifact upload must persist: {artifact_file}"
            )
        # Records must persist even when the verdict step fails (faulty-green):
        # the evidence steps must be `if: always()`.
        assert upload_step.get("if") == "always()", (
            "artifact upload must run even on faulty-green (if: always())"
        )
