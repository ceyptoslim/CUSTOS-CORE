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
