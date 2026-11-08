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

There is no ``--force`` flag. Rerunning an arm is the one thing a pre-registration
exists to prevent, so the escape hatch is absent rather than discouraged.

Usage, once, per arm:

    python scripts/benchmarks/run_agentdojo_ab.py \
        --arm B1 --attack important_instructions \
        --model gpt-4.1-mini-2025-04-14 --out runs/agentdojo-B1

The attack name is recorded in the manifest and must be the same string for all
three arms, since a different attack changes the injection, not just the scoring.
"""
# Copyright (C) 2024-2026 Tavares Heath Sr. (doing business as FroLife Productions)
# Licensed under the GNU Affero General Public License v3.0 (AGPL-3.0)
# See LICENSE file for details. Commercial license available upon request.

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from agentdojo_guard import (  # noqa: E402
    ARM_A,
    ARM_ALLOWLISTS,
    BANKING_SUITE_PIN,
    FROZEN_MODEL_ID,
    FROZEN_PREREG_COMMIT,
    ArmConfig,
    CaseListDrift,
    RunRefused,
    build_gate,
    verify_case_list,
)

EXIT_REFUSED = 2


def _refuse(message: str) -> None:
    print(f"REFUSED: {message}", file=sys.stderr)
    raise SystemExit(EXIT_REFUSED)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arm", required=True, choices=sorted(ARM_ALLOWLISTS))
    parser.add_argument("--attack", required=True, help="AgentDojo attack name, recorded verbatim")
    parser.add_argument("--model", required=True, help=f"must be {FROZEN_MODEL_ID}")
    parser.add_argument("--out", required=True, help="output directory for the frozen record")
    parser.add_argument(
        "--case-list",
        default=str(pathlib.Path("docs/benchmark/case-list-v1.txt")),
        help="frozen case list; its hash is checked before anything else happens",
    )
    parser.add_argument("--logdir", default=None, help="optional AgentDojo log directory")
    return parser.parse_args(argv)


def build_pipeline(model: str, arm: str, case_id: str = "", sink=None):
    """The benchmark chain, with the guard inserted only for the gated arms."""
    from openai import OpenAI

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

    # max_retries=0 and temperature=0.0 are copied from the frozen model
    # configuration. A retry would hide a provider failure inside a benchmark
    # result, which is the one place it would never be questioned.
    llm = OpenAILLM(OpenAI(max_retries=0), model, temperature=0.0)
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
    )
    problems = config.validate()
    if problems:
        _refuse("; ".join(problems))

    try:
        cases = verify_case_list(case_list)
    except CaseListDrift as exc:
        _refuse(str(exc))

    if not os.environ.get("OPENAI_API_KEY"):
        _refuse("OPENAI_API_KEY is not set; no arm may run without a provider")

    results_path = out_dir / f"results-{args.arm}.json"
    decisions_path = out_dir / f"decisions-{args.arm}.jsonl"
    manifest_path = out_dir / "manifest.json"
    if results_path.exists() or decisions_path.exists():
        _refuse(
            f"{out_dir} already holds results for arm {args.arm}. One run per arm; "
            "a rerun voids the pre-registration."
        )

    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "prereg_commit": FROZEN_PREREG_COMMIT,
        "benchmark": "agentdojo",
        "suite": "banking",
        "suite_pin": BANKING_SUITE_PIN,
        "arm": args.arm,
        "allowlist": sorted(ARM_ALLOWLISTS[args.arm]),
        "model": args.model,
        "attack": args.attack,
        "case_list": str(case_list),
        "case_count": len(cases),
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "note": "payload rules at defaults; no banking rule added",
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    from agentdojo.attacks.attack_registry import load_attack
    from agentdojo.benchmark import run_task_with_injection_tasks
    from agentdojo.task_suite.load_suites import get_suite

    suite = get_suite("v1", "banking")
    decisions: list[dict] = []
    rows: list[dict] = []
    logdir = pathlib.Path(args.logdir) if args.logdir else None

    for case in cases:
        user_id, injection_id = case.split(":")
        user_task = suite.get_user_task_by_id(user_id)
        pipeline, _gate = build_pipeline(args.model, args.arm, case_id=case)
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
        except Exception as exc:  # noqa: BLE001 - a failed case is a reported case
            # Not skipped, not retried. The count of these is part of the result.
            rows.append({"case": case, "error": f"{type(exc).__name__}: {exc}"})
            continue
        key = (user_id, injection_id)
        rows.append(
            {
                "case": case,
                "utility": bool(utility.get(key)),
                "injection_success": bool(security.get(key)),
            }
        )
        guarded = _loop_runtime_records(pipeline)
        for record in guarded:
            record["case_id"] = case
            decisions.append(record)

    results = {
        "arm": args.arm,
        "cases": len(cases),
        "errors": sum(1 for r in rows if "error" in r),
        "utility_true": sum(1 for r in rows if r.get("utility") is True),
        "injection_success_true": sum(1 for r in rows if r.get("injection_success") is True),
        "rows": rows,
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
