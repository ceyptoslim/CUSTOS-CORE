"""The frozen case list and the installed suite have to agree on how to name a task.

They did not. The pre-registration enumerates cases as ``UserTask0:InjectionTask0``
and AgentDojo 0.1.35 keys the banking suite ``user_task_0`` and
``injection_task_0``, so the first live invocation of Arm A died at the first
lookup with ``KeyError: 'UserTask0'`` after the manifest was written and before a
single case was recorded.

No guard caught it because every existing test stubs the suite: the guards pin
the runner's decisions, and the one test that touches the real package exercises
the pipeline element, not the case resolution between the frozen file and the
suite. So the guard added here is a membership check of exactly that seam, in two
forms, plus the file hash so the translation cannot be mistaken for permission to
edit the frozen list.

The offline form is the one that runs in CI, where the benchmark extra is absent:
it asserts every frozen identifier maps to the shape the suite uses and resolves
against a stand-in keyed the way the real suite is keyed. The real form asserts
the same membership against the installed package and skips when it is missing.
"""
# Copyright (C) 2024-2026 Tavares Heath Sr. (doing business as FroLife Productions)
# Licensed under the GNU Affero General Public License v3.0 (AGPL-3.0)
# See LICENSE file for details. Commercial license available upon request.

import hashlib
import pathlib
import re
import sys
import types

import pytest

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
SCRIPTS = ROOT / "scripts" / "benchmarks"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import run_agentdojo_ab as runner  # noqa: E402

CASE_LIST = ROOT / "docs" / "benchmark" / "case-list-v1.txt"
FROZEN_FILE_SHA256 = "7b4ca3b932d6535430ed9c1ee42b3e545c2ddf4048fddf0a4d34a625a7ad0003"
SUITE_KEY = re.compile(r"^(user_task|injection_task)_(\d+)$")


def _cases():
    return CASE_LIST.read_text().split()


def test_the_frozen_file_still_hashes_to_the_pinned_value():
    # The translation lives in the runner, not in this file. If a future edit
    # rewrites the identifiers in place instead, the pre-registration stops
    # describing the run, so the hash is the guard on that temptation.
    assert hashlib.sha256(CASE_LIST.read_bytes()).hexdigest() == FROZEN_FILE_SHA256
    assert len(_cases()) == 144


@pytest.mark.parametrize(
    ("frozen", "expected"),
    [
        ("UserTask0:InjectionTask0", ("user_task_0", "injection_task_0")),
        ("UserTask7:InjectionTask3", ("user_task_7", "injection_task_3")),
        ("UserTask15:InjectionTask8", ("user_task_15", "injection_task_8")),
        ("user_task_2:injection_task_1", ("user_task_2", "injection_task_1")),
    ],
)
def test_a_frozen_identifier_maps_to_the_suites_vocabulary(frozen, expected):
    assert runner.suite_ids(frozen) == expected


def test_an_identifier_that_is_not_a_case_is_not_guessed_at():
    with pytest.raises(ValueError):
        runner.suite_ids("UserTask0")


def test_every_frozen_case_maps_to_the_shape_the_suite_uses():
    user_ids, injection_ids = set(), set()
    for case in _cases():
        user_id, injection_id = runner.suite_ids(case)
        assert SUITE_KEY.match(user_id), (case, user_id)
        assert SUITE_KEY.match(injection_id), (case, injection_id)
        assert user_id.startswith("user_task_")
        assert injection_id.startswith("injection_task_")
        user_ids.add(user_id)
        injection_ids.add(injection_id)
    assert len(user_ids) == 16
    assert len(injection_ids) == 9
    assert len(_cases()) == len(user_ids) * len(injection_ids)


def test_the_frozen_names_would_not_resolve_without_the_translation():
    # This is the defect, held in place: looked up under its own name, a frozen
    # identifier is absent from a suite keyed the way the real one is.
    suite = {f"user_task_{n}": n for n in range(16)}
    assert "UserTask0" not in suite
    assert runner.suite_ids("UserTask0:InjectionTask0")[0] in suite


def test_every_frozen_case_resolves_against_a_suite_keyed_the_real_way():
    suite = {
        **{f"user_task_{n}": object() for n in range(16)},
        **{f"injection_task_{n}": object() for n in range(9)},
    }
    for case in _cases():
        user_id, injection_id = runner.suite_ids(case)
        assert user_id in suite, case
        assert injection_id in suite, case


def test_the_installed_suite_carries_every_frozen_case():
    pytest.importorskip(
        "agentdojo", reason="benchmark package absent; the offline guards above cover the seam"
    )
    from agentdojo.task_suite.load_suites import get_suite  # noqa: F401

    suite = get_suite("v1", "banking")
    missing = []
    for case in _cases():
        user_id, injection_id = runner.suite_ids(case)
        try:
            suite.get_user_task_by_id(user_id)
            suite.get_injection_task_by_id(injection_id)
        except KeyError:
            missing.append((case, user_id, injection_id))
    assert missing == [], f"the frozen list names cases this suite does not have: {missing[:3]}"


def test_a_case_the_suite_does_not_carry_is_reported_not_looked_up():
    # The real function the runner refuses on, driven against a stand-in that is
    # keyed the way the installed suite is keyed but is missing one task.
    def missing(key):
        raise KeyError(key)

    suite = types.SimpleNamespace(
        get_user_task_by_id=lambda i: None if i == "user_task_0" else missing(i),
        get_injection_task_by_id=lambda i: None,
    )
    absent = runner.missing_tasks(suite, ["UserTask0:InjectionTask0", "UserTask1:InjectionTask1"])
    assert len(absent) == 1
    assert absent[0][0] == "UserTask1:InjectionTask1"
    assert absent[0][1] == "user_task_1 / injection_task_1"
    assert "user_task_1" in absent[0][2]


def test_a_whole_missing_vocabulary_is_reported_as_every_case():
    # What the first live run actually looked like: nothing resolves at all.
    def missing(key):
        raise KeyError(key)

    suite = types.SimpleNamespace(
        get_user_task_by_id=missing, get_injection_task_by_id=missing
    )
    absent = runner.missing_tasks(suite, _cases())
    assert len(absent) == 144
