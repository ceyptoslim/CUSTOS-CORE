"""The benchmark runner survives a provider wall without corrupting the record.

Three claims are guarded here, and each one is a defect that was repaired rather
than a feature that was added.

The first is that a provider quota error is not scored. The runner turns a case's
exception into a row carrying ``error``, and the pre-registration allows no
exclusions, so a 429 used to become a permanent observation about the gate. The
test drives a 429 through the runner and asserts the exit is 3, that no results
file exists, and that the journal records an abort rather than a case.

The second is that progress survives the interruption. The journal is appended and
fsynced per case, so an interrupted arm can be resumed instead of discarded, and a
resumed arm must produce the same files an uninterrupted arm would have produced.
That equality is asserted against a clean run rather than described.

The third is that resumption cannot silently change the experiment. A journal
bound to one arm, model, attack and case list refuses to continue as another.

The runner's AgentDojo imports are stubbed, so all of this runs in CI where the
benchmark package is an optional extra. The real pipeline is covered by
``tests/test_agentdojo_element.py``, which skips when the package is absent.
"""
# Copyright (C) 2024-2026 Tavares Heath Sr. (doing business as FroLife Productions)
# Licensed under the GNU Affero General Public License v3.0 (AGPL-3.0)
# See LICENSE file for details. Commercial license available upon request.

import importlib.util
import json
import pathlib
import random
import sys
import types

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
RESILIENCE_PATH = ROOT / "scripts" / "benchmarks" / "agentdojo_resilience.py"
RUNNER_PATH = ROOT / "scripts" / "benchmarks" / "run_agentdojo_ab.py"
CASE_LIST = ROOT / "docs" / "benchmark" / "case-list-v1.txt"
FROZEN_MODEL = "gpt-4.1-mini-2025-04-14"


class _StatusError(Exception):
    def __init__(self, message: str, status_code: int):
        super().__init__(message)
        self.status_code = status_code


def _load(path: pathlib.Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def resilience():
    return _load(RESILIENCE_PATH, "agentdojo_resilience_under_test")


@pytest.fixture()
def runner(resilience, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "scripts" / "benchmarks"))
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    module = _load(RUNNER_PATH, "run_agentdojo_ab_under_test")
    module.build_pipeline = lambda model, arm, case_id="", sink=None, policy=None, **kwargs: (
        types.SimpleNamespace(elements=[]),
        None,
    )
    return module


def _stub_agentdojo(monkeypatch, behaviour):
    """Minimal AgentDojo surface: the suite hands back the ids it was asked for."""
    calls: list[str] = []

    def get_suite(version, suite_name):
        suite = types.SimpleNamespace()

        def get_user_task_by_id(user_task_id):
            return types.SimpleNamespace(id=user_task_id)

        suite.get_user_task_by_id = get_user_task_by_id
        # The runner checks both ids against the suite before it spends a call, so
        # the stub carries both lookups the installed suite carries.
        suite.get_injection_task_by_id = lambda injection_task_id: types.SimpleNamespace(
            id=injection_task_id
        )
        return suite

    def run_task_with_injection_tasks(
        suite, pipeline, user_task, attack, logdir=None, force_rerun=False, injection_tasks=None
    ):
        case = f"{user_task.id}:{injection_tasks[0]}"
        calls.append(case)
        behaviour(case)
        key = (user_task.id, injection_tasks[0])
        return {key: True}, {key: False}

    modules = {
        "agentdojo": types.ModuleType("agentdojo"),
        "agentdojo.attacks": types.ModuleType("agentdojo.attacks"),
        "agentdojo.attacks.attack_registry": types.ModuleType("agentdojo.attacks.attack_registry"),
        "agentdojo.benchmark": types.ModuleType("agentdojo.benchmark"),
        "agentdojo.task_suite": types.ModuleType("agentdojo.task_suite"),
        "agentdojo.task_suite.load_suites": types.ModuleType("agentdojo.task_suite.load_suites"),
    }
    modules["agentdojo.attacks.attack_registry"].load_attack = lambda attack, suite, pipeline: object()
    modules["agentdojo.benchmark"].run_task_with_injection_tasks = run_task_with_injection_tasks
    modules["agentdojo.task_suite.load_suites"].get_suite = get_suite
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)
    return calls


def _argv(out: pathlib.Path, *extra: str) -> list[str]:
    return [
        "--arm",
        "B1",
        "--attack",
        "important_instructions",
        "--model",
        FROZEN_MODEL,
        "--out",
        str(out),
        "--base-delay",
        "0",
        "--max-delay",
        "0",
        *extra,
    ]


# ---------------------------------------------------------------- classification


def test_provider_wall_is_classified_and_hard_failure_is_not(resilience):
    assert resilience.is_transient(_StatusError("slow down", 429)) is True
    assert resilience.is_transient(_StatusError("upstream", 503)) is True
    assert resilience.is_transient(ValueError("model produced nonsense")) is False
    assert resilience.is_auth_failure(_StatusError("bad key", 401)) is True
    assert resilience.is_transient(_StatusError("bad key", 401)) is False


def test_backoff_retries_the_provider_and_records_each_attempt(resilience):
    sleeps: list[float] = []
    recorded: list[tuple[int, float]] = []
    attempts = {"n": 0}

    def operation():
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise _StatusError("quota", 429)
        return "ok"

    policy = resilience.RetryPolicy(
        max_attempts=5,
        base_delay=1.0,
        max_delay=10.0,
        sleep=sleeps.append,
        rng=random.Random(0),
        on_retry=lambda attempt, delay, exc: recorded.append((attempt, round(delay, 3))),
    )
    assert policy.run(operation, case_id="x") == "ok"
    assert attempts["n"] == 3
    assert len(sleeps) == 2 and len(recorded) == 2
    assert recorded[0][1] > 0


def test_backoff_does_not_retry_a_case_level_failure(resilience):
    sleeps: list[float] = []
    attempts = {"n": 0}

    def operation():
        attempts["n"] += 1
        raise ValueError("tool argument invalid")

    policy = resilience.RetryPolicy(max_attempts=5, base_delay=1.0, sleep=sleeps.append)
    with pytest.raises(ValueError):
        policy.run(operation)
    assert attempts["n"] == 1 and sleeps == []


def test_exhausted_budget_raises_an_interruption_not_a_result(resilience):
    sleeps: list[float] = []
    policy = resilience.RetryPolicy(max_attempts=3, base_delay=1.0, sleep=sleeps.append)

    def operation():
        raise _StatusError("quota", 429)

    with pytest.raises(resilience.RunInterrupted) as excinfo:
        policy.run(operation, case_id="c1")
    assert excinfo.value.exit_code == 3
    assert excinfo.value.attempts == 3
    assert len(sleeps) == 2


# ---------------------------------------------------------------------- journal


def _binding(resilience, **overrides):
    payload = {
        "arm": "B1",
        "model": FROZEN_MODEL,
        "attack": "important_instructions",
        "case_list_sha256": "a" * 64,
        "case_count": 2,
        "allowlist": ["send_money"],
        "prereg_commit": "0" * 40,
        "suite_pin": "1" * 40,
    }
    payload.update(overrides)
    return resilience.Journal.binding(**payload)


def test_journal_resumes_only_its_own_run(resilience, tmp_path):
    journal = resilience.Journal(tmp_path / "journal-B1.jsonl")
    binding = _binding(resilience)
    journal.start(binding)
    journal.append_case("user_task_0:injection_task_0", {"case": "user_task_0:injection_task_0"})

    completed = journal.open_resume(binding)
    assert list(completed) == ["user_task_0:injection_task_0"]

    with pytest.raises(resilience.JournalConflict):
        journal.open_resume(_binding(resilience, attack="injecagent"))
    with pytest.raises(resilience.JournalConflict):
        journal.open_resume(_binding(resilience, model="gpt-4.1"))


def test_journal_refuses_a_second_start(resilience, tmp_path):
    journal = resilience.Journal(tmp_path / "journal-B1.jsonl")
    journal.start(_binding(resilience))
    with pytest.raises(resilience.JournalConflict):
        journal.start(_binding(resilience))


def test_a_torn_journal_line_is_loud_rather_than_silent(resilience, tmp_path):
    path = tmp_path / "journal-B1.jsonl"
    journal = resilience.Journal(path)
    binding = _binding(resilience)
    journal.start(binding)
    journal.append_case("user_task_0:injection_task_0", {"case": "user_task_0:injection_task_0"})
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"type": "case", "case_id": "user_task_0:injection_ta')

    with pytest.raises(resilience.JournalCorrupt):
        journal.read()


# ----------------------------------------------------------------------- runner


def test_a_quota_error_is_not_scored_as_a_case(runner, monkeypatch, tmp_path):
    calls = _stub_agentdojo(monkeypatch, lambda case: (_ for _ in ()).throw(_StatusError("quota", 429)))
    code = runner.main(_argv(tmp_path))
    assert code == 3
    assert not (tmp_path / "results-B1.json").exists()
    assert not (tmp_path / "decisions-B1.jsonl").exists()
    journal = (tmp_path / "journal-B1.jsonl").read_text().splitlines()
    entries = [json.loads(line) for line in journal]
    assert all(entry["type"] != "case" for entry in entries)
    assert any(entry["type"] == "abort" and entry["reason"] == "provider_transient" for entry in entries)
    assert len(calls) == 1


def test_a_bad_key_refuses_before_any_case_is_scored(runner, monkeypatch, tmp_path):
    _stub_agentdojo(monkeypatch, lambda case: (_ for _ in ()).throw(_StatusError("invalid_api_key", 401)))
    with pytest.raises(SystemExit) as excinfo:
        runner.main(_argv(tmp_path))
    assert excinfo.value.code == 2
    assert not (tmp_path / "results-B1.json").exists()
    entries = [json.loads(line) for line in (tmp_path / "journal-B1.jsonl").read_text().splitlines()]
    assert any(entry["type"] == "abort" and entry["reason"] == "provider_auth_failure" for entry in entries)


def test_a_case_level_error_is_still_a_recorded_row(runner, monkeypatch, tmp_path):
    def behaviour(case):
        # The stub reports the suite's own vocabulary, which is also what the real
        # suite reports; the frozen list's spelling never reaches this call.
        if case.startswith("user_task_0:"):
            raise ValueError("tool argument invalid")

    _stub_agentdojo(monkeypatch, behaviour)
    assert runner.main(_argv(tmp_path)) == 0
    results = json.loads((tmp_path / "results-B1.json").read_text())
    assert results["cases"] == 144
    # UserTask0 carries nine injection pairs, so the nine failures are nine rows
    # rather than one case retried: a case-level failure is data, not an outage.
    assert results["errors"] == 9
    assert results["rows"][0]["error"].startswith("ValueError")
    assert results["utility_true"] == 144 - 9


def test_interrupted_arm_resumes_to_the_same_record_as_a_clean_arm(runner, monkeypatch, tmp_path):
    clean_dir = tmp_path / "clean"
    _stub_agentdojo(monkeypatch, lambda case: None)
    assert runner.main(_argv(clean_dir)) == 0
    clean = json.loads((clean_dir / "results-B1.json").read_text())

    interrupted_dir = tmp_path / "interrupted"
    state = {"n": 0}

    def fails_after_five(case):
        state["n"] += 1
        if state["n"] > 5:
            raise _StatusError("quota", 429)

    _stub_agentdojo(monkeypatch, fails_after_five)
    assert runner.main(_argv(interrupted_dir)) == 3
    assert not (interrupted_dir / "results-B1.json").exists()
    recorded = [
        json.loads(line)
        for line in (interrupted_dir / "journal-B1.jsonl").read_text().splitlines()
    ]
    assert sum(1 for entry in recorded if entry["type"] == "case") == 5

    _stub_agentdojo(monkeypatch, lambda case: None)
    assert runner.main(_argv(interrupted_dir, "--resume")) == 0
    resumed = json.loads((interrupted_dir / "results-B1.json").read_text())
    assert resumed["rows"] == clean["rows"]
    assert resumed["utility_true"] == clean["utility_true"]
    assert resumed["injection_success_true"] == clean["injection_success_true"]


def test_a_partial_arm_refuses_to_restart_without_resume(runner, monkeypatch, tmp_path):
    state = {"n": 0}

    def fails_after_two(case):
        state["n"] += 1
        if state["n"] > 2:
            raise _StatusError("quota", 429)

    _stub_agentdojo(monkeypatch, fails_after_two)
    assert runner.main(_argv(tmp_path)) == 3
    with pytest.raises(SystemExit) as excinfo:
        runner.main(_argv(tmp_path))
    assert excinfo.value.code == 2


def test_resume_refuses_when_the_attack_changed(runner, monkeypatch, tmp_path):
    state = {"n": 0}

    def fails_after_one(case):
        state["n"] += 1
        if state["n"] > 1:
            raise _StatusError("quota", 429)

    _stub_agentdojo(monkeypatch, fails_after_one)
    assert runner.main(_argv(tmp_path)) == 3

    argv = _argv(tmp_path, "--resume")
    argv[argv.index("--attack") + 1] = "injecagent"
    with pytest.raises(SystemExit) as excinfo:
        runner.main(argv)
    assert excinfo.value.code == 2
