"""Run one AgentDojo banking arm and freeze what came back.

This runner refuses more often than it runs, on purpose. The pre-registration
(``docs/benchmark/agentdojo-prereg-v1.md`` at ``578a22f``) fixes the arms, the case
list, the model and the rule that there is one run per arm with no exclusions, so
every departure from that is an exit code rather than a judgement call:

    2  the case list on disk is not the frozen list
    2  the model is an alias, or is not the frozen snapshot
    2  the attack is not declared (it is deliberately not defaulted)
    2  results for this arm already exist in the output directory
    2  no provider key in the environment
    2  a partial run exists and ``--resume`` was not given
    2  the journal on disk belongs to a different arm, model, attack or case list
    3  the provider kept failing after the retry budget (progress is in the journal)
    3  the provider's daily quota is spent and the sitting cannot finish
    3  the run ended with cases still unrecorded
    4  the provider served a second model version under one name; series void

Exit 3 is not a result. It means the provider, not the gate, stopped the run:
nothing was written to ``results`` or ``decisions``, the journal holds every case
that did complete, and ``--resume`` continues from there under the same identity
digest. Free-tier quotas make this the ordinary path rather than the exceptional
one, and a quota wall scored as a failed case would have entered the frozen record
as an observation about the gate.

There is no ``--force`` flag. Rerunning an arm is the one thing a pre-registration
exists to prevent, so the escape hatch is absent rather than discouraged. Resuming
is not rerunning: it replays only cases with no journal entry and refuses the
moment the identity differs.

Usage, once, per arm:

    python scripts/benchmarks/run_agentdojo_ab.py \
        --arm B1 --attack important_instructions \
        --model gpt-4.1-mini-2025-04-14 --out runs/agentdojo-B1

    python scripts/benchmarks/run_agentdojo_ab.py --provider google \
        --arm B1 --attack important_instructions \
        --model gemini-3.6-flash --out runs/agentdojo-B1-gemini

The provider decides which pre-registration the run is bound to, which model id is
accepted, and which arms exist. The Gemini series runs A and B1 only; v2 omits B2
as a cost decision made before any measurement.

The attack name is recorded in the manifest and must be the same string for all
three arms, since a different attack changes the injection, not just the scoring.
"""
# Copyright (C) 2024-2026 Tavares Heath Sr. (doing business as FroLife Productions)
# Licensed under the GNU Affero General Public License v3.0 (AGPL-3.0)
# See LICENSE file for details. Commercial license available upon request.

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import sys
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from agentdojo_resilience import (  # noqa: E402
    EXIT_INTERRUPTED,
    Journal,
    JournalConflict,
    JournalCorrupt,
    QuotaExhausted,
    RetryPolicy,
    RetryingQuery,
    RunInterrupted,
    is_auth_failure,
    is_transient,
)

from agentdojo_guard import (  # noqa: E402
    ARM_A,
    ARM_ALLOWLISTS,
    BANKING_SUITE_PIN,
    PREREG_BY_PROVIDER,
    PROVIDER_KEY_ENV,
    PROVIDER_MODELS,
    PROVIDER_THINKING_BUDGET,
    ArmConfig,
    CaseListDrift,
    RunRefused,
    build_gate,
    verify_case_list,
)

EXIT_REFUSED = 2
EXIT_VOID = 4


def _refuse(message: str) -> None:
    print(f"REFUSED: {message}", file=sys.stderr)
    raise SystemExit(EXIT_REFUSED)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arm", required=True, choices=sorted(ARM_ALLOWLISTS))
    parser.add_argument("--attack", required=True, help="AgentDojo attack name, recorded verbatim")
    parser.add_argument(
        "--provider",
        default="openai",
        choices=sorted(PROVIDER_MODELS),
        help="which pinned provider this arm runs against (default openai)",
    )
    parser.add_argument(
        "--model",
        required=True,
        help=f"the pinned model for --provider: {PROVIDER_MODELS['openai']} or "
        f"{PROVIDER_MODELS['google']}",
    )
    parser.add_argument("--out", required=True, help="output directory for the frozen record")
    parser.add_argument(
        "--case-list",
        default=str(pathlib.Path("docs/benchmark/case-list-v1.txt")),
        help="frozen case list; its hash is checked before anything else happens",
    )
    parser.add_argument("--logdir", default=None, help="optional AgentDojo log directory")
    parser.add_argument(
        "--resume",
        action="store_true",
        help="continue a run interrupted at exit 3; refuses if the identity changed",
    )
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=5,
        help="provider attempts per model call before the run is interrupted (default 5)",
    )
    parser.add_argument(
        "--base-delay",
        type=float,
        default=2.0,
        help="first backoff delay in seconds, doubled per attempt (default 2.0)",
    )
    parser.add_argument(
        "--max-delay",
        type=float,
        default=60.0,
        help="ceiling for a single backoff delay in seconds (default 60.0)",
    )
    return parser.parse_args(argv)


def build_pipeline(
    model: str,
    arm: str,
    case_id: str = "",
    sink=None,
    policy=None,
    provider: str = "openai",
    recorder=None,
):
    """The benchmark chain, with the guard inserted only for the gated arms.

    ``policy`` wraps the model element, never the tool executor: a retried model
    call re-asks the same question, while a retried tool execution would re-run a
    decision the gate already made and record its consequences twice.
    """
    from agentdojo.agent_pipeline import (
        AgentPipeline,
        InitQuery,
        OpenAILLM,
        SystemMessage,
        ToolsExecutionLoop,
        ToolsExecutor,
    )
    from agentdojo.agent_pipeline.agent_pipeline import load_system_message
    from agentdojo.agent_pipeline.tool_execution import tool_result_to_str

    from agentdojo_element import GuardedRuntimeElement

    # temperature 0.0 and no provider-side retry in the client are copied from the
    # frozen model configuration. A retry would hide a provider failure inside a
    # benchmark result, which is the one place it would never be questioned. Each
    # provider gets the closest available construction of that same rule.
    if provider == "google":
        from agentdojo_element import build_google_llm

        if recorder is None:
            raise RunRefused("the google provider records model versions; none was supplied")
        llm = build_google_llm(
            model,
            os.environ[PROVIDER_KEY_ENV["google"]],
            recorder,
            PROVIDER_THINKING_BUDGET["google"],
        )
    else:
        from openai import OpenAI

        llm = OpenAILLM(OpenAI(max_retries=0), model, temperature=0.0)
    if policy is not None:
        llm = RetryingQuery(llm, policy, case_id=case_id, name=f"retrying-{model}")
    loop_elements = []
    gate = None
    if arm != ARM_A:
        gate, _manager = build_gate(arm)
        loop_elements.append(
            GuardedRuntimeElement(gate, arm, case_id=case_id, sink=sink)
        )
    loop_elements.extend([ToolsExecutor(tool_result_to_str), llm])

    pipeline = AgentPipeline(
        [
            SystemMessage(load_system_message("default")),
            InitQuery(),
            llm,
            ToolsExecutionLoop(loop_elements),
        ]
    )
    pipeline.name = model if arm == ARM_A else f"{model}-custos-{arm}"
    return pipeline, gate


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    case_list = pathlib.Path(args.case_list)
    out_dir = pathlib.Path(args.out)

    config = ArmConfig(
        arm=args.arm,
        model=args.model,
        attack=args.attack,
        case_list=case_list,
        out_dir=out_dir,
        provider=args.provider,
    )
    problems = config.validate()
    if problems:
        _refuse("; ".join(problems))

    try:
        cases = verify_case_list(case_list)
    except CaseListDrift as exc:
        _refuse(str(exc))

    key_env = PROVIDER_KEY_ENV[args.provider]
    if not os.environ.get(key_env):
        _refuse(f"{key_env} is not set; no arm may run without a provider")

    results_path = out_dir / f"results-{args.arm}.json"
    decisions_path = out_dir / f"decisions-{args.arm}.jsonl"
    manifest_path = out_dir / "manifest.json"
    if results_path.exists() or decisions_path.exists():
        _refuse(
            f"{out_dir} already holds results for arm {args.arm}. One run per arm; "
            "a rerun voids the pre-registration."
        )

    binding = Journal.binding(
        arm=args.arm,
        provider=args.provider,
        model=args.model,
        attack=args.attack,
        case_list_sha256=_file_sha256(case_list),
        case_count=len(cases),
        allowlist=ARM_ALLOWLISTS[args.arm],
        prereg_commit=PREREG_BY_PROVIDER[args.provider],
        suite_pin=BANKING_SUITE_PIN,
    )
    journal = Journal(out_dir / f"journal-{args.arm}.jsonl")
    completed: dict[str, dict] = {}

    if journal.exists():
        if not args.resume:
            _refuse(
                f"{journal.path} holds a partial run for arm {args.arm}. Pass --resume "
                "to continue it; a fresh start would discard recorded cases and, with "
                "one run per arm, the arm."
            )
        try:
            completed = journal.open_resume(binding)
            _verify_manifest(manifest_path, binding)
        except (JournalConflict, JournalCorrupt) as exc:
            _refuse(str(exc))
        print(
            f"resuming arm {args.arm}: {len(completed)}/{len(cases)} cases already recorded",
            file=sys.stderr,
        )
    else:
        if args.resume:
            _refuse(f"--resume was given but {journal.path} does not exist; nothing to resume")
        out_dir.mkdir(parents=True, exist_ok=True)
        manifest = {
            "prereg_commit": PREREG_BY_PROVIDER[args.provider],
            "benchmark": "agentdojo",
            "suite": "banking",
            "suite_pin": BANKING_SUITE_PIN,
            "arm": args.arm,
            "allowlist": sorted(ARM_ALLOWLISTS[args.arm]),
            "provider": args.provider,
            "model": args.model,
            "thinking_budget": PROVIDER_THINKING_BUDGET[args.provider],
            "temperature": 0.0,
            "attack": args.attack,
            "case_list": str(case_list),
            "case_count": len(cases),
            "case_list_sha256": binding["case_list_sha256"],
            "journal_sha256": Journal.digest(binding),
            "started_utc": datetime.now(timezone.utc).isoformat(),
            "note": "payload rules at defaults; no banking rule added",
        }
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        try:
            journal.start(binding)
        except JournalConflict as exc:
            _refuse(str(exc))

    from agentdojo.attacks.attack_registry import load_attack
    from agentdojo.benchmark import run_task_with_injection_tasks
    from agentdojo.task_suite.load_suites import get_suite

    suite = get_suite("v1", "banking")
    logdir = pathlib.Path(args.logdir) if args.logdir else None
    pending = [case for case in cases if case not in completed]
    # Only the Google path has a version to record. The recorder lives out here
    # rather than inside the pipeline because the void rule is a property of the
    # series, not of a case, and the import stays inside the branch so the OpenAI
    # path does not need the benchmark package to be importable.
    recorder = None
    if args.provider == "google":
        from agentdojo_element import ModelVersionRecorder

        recorder = ModelVersionRecorder()

    for position, case in enumerate(pending, start=1):
        user_id, injection_id = case.split(":")
        user_task = suite.get_user_task_by_id(user_id)
        policy = RetryPolicy(
            max_attempts=args.max_attempts,
            base_delay=args.base_delay,
            max_delay=args.max_delay,
            on_retry=_retry_recorder(journal, case),
        )
        pipeline, _gate = build_pipeline(
            args.model,
            args.arm,
            case_id=case,
            policy=policy,
            provider=args.provider,
            recorder=recorder,
        )
        attack = load_attack(args.attack, suite, pipeline)
        try:
            utility, security = run_task_with_injection_tasks(
                suite,
                pipeline,
                user_task,
                attack,
                logdir=logdir,
                force_rerun=False,
                injection_tasks=[injection_id],
            )
        except QuotaExhausted as exc:
            journal.append_abort(
                "provider_quota_exhausted",
                case_id=case,
                quota=exc.quota,
                attempts=exc.attempts,
                detail=str(exc),
            )
            print(
                "INTERRUPTED: the provider's daily quota is spent. Nothing was scored "
                f"for {case}. {len(completed)}/{len(cases)} cases are in {journal.path}. "
                "Continue with the same command plus --resume when the quota resets; "
                "this is an interruption, not a void.",
                file=sys.stderr,
            )
            return EXIT_INTERRUPTED
        except RunInterrupted as exc:
            journal.append_abort(
                "provider_retry_exhausted", case_id=case, attempts=exc.attempts, detail=str(exc)
            )
            print(_resume_hint(args, journal, len(completed), len(cases)), file=sys.stderr)
            return EXIT_INTERRUPTED
        except Exception as exc:  # noqa: BLE001 - classification decides the outcome
            detail = f"{type(exc).__name__}: {exc}"
            if is_auth_failure(exc):
                journal.append_abort("provider_auth_failure", case_id=case, detail=detail)
                _refuse(
                    f"provider rejected the credentials at case {case} ({detail}). No "
                    "case was scored: a bad key would otherwise write 144 error rows "
                    "and call it a result."
                )
            if is_transient(exc):
                journal.append_abort("provider_transient", case_id=case, detail=detail)
                print(_resume_hint(args, journal, len(completed), len(cases)), file=sys.stderr)
                return EXIT_INTERRUPTED
            # A genuine failure of this case. Not skipped, not retried: the count of
            # these is part of the result.
            row = {"case": case, "error": detail}
            journal.append_case(case, row, [])
            completed[case] = {"row": row, "decisions": []}
            print(f"[{len(completed)}/{len(cases)}] {case}: error {type(exc).__name__}", file=sys.stderr)
            if _void_on_mixed_versions(recorder, journal):
                return EXIT_VOID
            continue
        key = (user_id, injection_id)
        row = {
            "case": case,
            "utility": bool(utility.get(key)),
            "injection_success": bool(security.get(key)),
        }
        decisions = []
        for record in _loop_runtime_records(pipeline):
            record["case_id"] = case
            decisions.append(record)
        journal.append_case(case, row, decisions)
        completed[case] = {"row": row, "decisions": decisions}
        print(
            f"[{len(completed)}/{len(cases)}] {case}: utility {row['utility']}, "
            f"injection {row['injection_success']}",
            file=sys.stderr,
        )
        if _void_on_mixed_versions(recorder, journal):
            return EXIT_VOID

    missing = [case for case in cases if case not in completed]
    if missing:
        print(
            f"arm {args.arm} ended with {len(missing)} cases unrecorded; no results file "
            "was written. Resume with --resume to finish it.",
            file=sys.stderr,
        )
        return EXIT_INTERRUPTED

    # The journal is the record. These two files are views of it, rebuilt in case
    # order so a resumed run writes exactly what an uninterrupted run would have.
    rows = [completed[case]["row"] for case in cases]
    decisions = [record for case in cases for record in completed[case]["decisions"]]
    _header, entries = journal.read()
    interruptions = [entry for entry in entries if entry.get("type") in ("abort", "event")]
    results = {
        "arm": args.arm,
        "provider": args.provider,
        "model": args.model,
        "model_versions": recorder.counts() if recorder is not None else {},
        "cases": len(cases),
        "errors": sum(1 for r in rows if "error" in r),
        "utility_true": sum(1 for r in rows if r.get("utility") is True),
        "injection_success_true": sum(1 for r in rows if r.get("injection_success") is True),
        "interruptions": len(interruptions),
        "interruption_events": interruptions,
        "rows": rows,
        "journal_sha256": Journal.digest(binding),
        "finished_utc": datetime.now(timezone.utc).isoformat(),
    }
    results_path.write_text(json.dumps(results, indent=2, sort_keys=True) + "\n")
    with decisions_path.open("w") as handle:
        for record in decisions:
            handle.write(json.dumps(record, sort_keys=True) + "\n")

    print(
        f"arm {args.arm}: utility {results['utility_true']}/{results['cases']}, "
        f"injection success {results['injection_success_true']}/{results['cases']}, "
        f"errors {results['errors']}"
    )
    return 0


def _void_on_mixed_versions(recorder, journal: Journal) -> bool:
    """Stop a series the moment the provider serves a second model version.

    Prereg v2 pins the Gemini model by name, and a name is an alias. One series can
    only describe one model, so the second version is the end of it: the journal
    records why, and the runner returns 4 rather than writing a result that would
    read as though a single model produced it.
    """
    if recorder is None or not recorder.mixed():
        return False
    versions = recorder.counts()
    journal.append_abort("model_version_changed", versions=recorder.versions(), counts=versions)
    print(
        f"VOID: the provider served more than one model version under {recorder.versions()!r} "
        f"({versions}). The series describes no single model and stops here; prereg v2 "
        "voids it. No results file was written.",
        file=sys.stderr,
    )
    return True


def _file_sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


def _verify_manifest(path: pathlib.Path, binding: dict) -> None:
    """The manifest and the journal must describe the same run."""
    if not path.exists():
        raise JournalConflict(f"{path} is missing; a journal without a manifest is not resumable")
    manifest = json.loads(path.read_text())
    comparisons = {
        "arm": binding["arm"],
        "provider": binding["provider"],
        "model": binding["model"],
        "attack": binding["attack"],
        "case_count": binding["case_count"],
        "suite_pin": binding["suite_pin"],
        "prereg_commit": binding["prereg_commit"],
        "case_list_sha256": binding["case_list_sha256"],
    }
    for field_name, expected in comparisons.items():
        if manifest.get(field_name) != expected:
            raise JournalConflict(
                f"{path} records {field_name}={manifest.get(field_name)!r} but this "
                f"invocation expects {expected!r}; refusing to resume across a changed run"
            )


def _retry_recorder(journal: Journal, case: str):
    """Every retry lands in the journal before the delay is slept."""

    def record(attempt: int, delay: float, exc: BaseException) -> None:
        journal.append_event(
            "retry",
            case_id=case,
            attempt=attempt,
            delay_s=round(delay, 3),
            error=f"{type(exc).__name__}: {exc}",
        )
        print(f"  retry {attempt} for {case} in {delay:.1f}s ({type(exc).__name__})", file=sys.stderr)

    return record


def _resume_hint(args: argparse.Namespace, journal: Journal, done: int, total: int) -> str:
    return (
        f"INTERRUPTED: provider failure, not a case result. {done}/{total} cases are in "
        f"{journal.path} and nothing was written to results. Continue with the same "
        "command plus --resume once the provider will serve again."
    )


def _loop_runtime_records(pipeline) -> list[dict]:
    """Pull the decision records out of whichever loop element wrapped the runtime.

    The wrapper is created inside ``query`` on the first iteration, so the records
    live on the runtime rather than on the element that made it. Reading them off
    the element would return an empty list and a result that looked clean because
    nothing was recorded.
    """
    for element in getattr(pipeline, "elements", []):
        for inner in getattr(element, "elements", []):
            runtime = getattr(inner, "_runtime", None)
            if runtime is not None and hasattr(runtime, "record_decisions"):
                return runtime.record_decisions()
    return []


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RunRefused as exc:
        _refuse(str(exc))
