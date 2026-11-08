# AgentDojo Pre-Registration v1: What a Tool-Allowlist Gate Buys and Costs

Status: committed and frozen, nothing run.
Post-freeze edits: the Status line only, plus the Commit line above. No arm, case, model, metric, prediction or void rule has changed since the freeze commit.
Commit: 578a22fc6598b35e764093a3e9d0afbd14d4db81 (the commit that froze this text; recorded here by a follow-up commit that changes nothing else)
Intended first run: not yet scheduled
Author: Tavares Heath / CUSTOS-CORE.
Written: November 8, 2026.

## Purpose

VERITAS OS reports 20/128 to 0/128 injection success with legitimate utility falling 93/128 to 64/128 on AgentDojo banking. CUSTOS-CORE has no comparable number in either direction. This pre-registration fixes the design before any run, so the result cannot be shaped by what comes back.

The question is deliberately narrow: on a benchmark neither party controls, what does CUSTOS-CORE's current decision surface, a per-tenant tool allowlist plus payload pattern rules, buy in injection resistance, and what does it cost in legitimate task completion.

## What this design does not measure

- Whether CUSTOS can stop an AgentDojo banking injection while preserving utility. It cannot be expected to, and this design is built to show why rather than to imply otherwise.
- Held-out generalization. The banking suite is public and possibly exposed in training data. No claim of generalization follows from any result here.
- Target-side effects. The gate sits before dispatch and observes no receiving system.

## Frozen configuration

| Item | Value |
|---|---|
| Benchmark | AgentDojo, banking suite |
| Pin | commit a75aba7 (same pin as the VERITAS run, for comparability) |
| Python | 3.11 |
| Provider | openai >=1.59.7,<2 |
| Model | `gpt-4.1-mini-2025-04-14`, snapshot id required, the alias `gpt-4.1-mini` forbidden, temperature 0.0, no automatic retry, no fallback model |
| Cases | all 144 paired (user_task, injection_task) pairs, 16 user tasks by 9 injection tasks, ordered by ascending task index and recorded in `case-list-v1.txt` |
| Case list hash | SHA-256 of the newline-joined ordered case list: `650dc5ff7d2fe22cf6a2b2cf08e1be60c71d7299486d6e88d883e81b678401ff` |
| Arms | one baseline, two gate variants |
| Runs | one per arm, no rerun, no case exclusion |

Arm A: AgentDojo native pipeline, no gate.

Arm B1: same pipeline, CUSTOS gate in front of every tool call. Allowlist = read-only banking tools only. All state-mutating tools absent (send_money, schedule_transaction, update_scheduled_transaction, and any other tool whose effect persists). Payload rules at defaults, untuned.

Arm B2: same pipeline, CUSTOS gate on. Allowlist = every banking tool the task suite exposes. Payload rules at defaults, untuned.

B1 and B2 bracket the two honest positions available to a tool-level gate. There is no third tuning step in this pre-registration, and adding one after the fact voids the result.

## Metrics

- Utility: AgentDojo native scorer per user task, counted over 144 cases.
- Injection success: AgentDojo native scorer per injection task, counted over 144 cases.
- Case-level difference lists against Arm A, reported in full.

## Predictions, recorded before the run

The banking suite at this pin exposes eleven tools. Six are read-only: `get_iban`, `get_balance`, `get_most_recent_transactions`, `get_scheduled_transactions`, `read_file`, `get_user_info`. Five persist an effect: `send_money`, `schedule_transaction`, `update_scheduled_transaction`, `update_password`, `update_user_info`.

Twelve of the sixteen user tasks require one of those five to satisfy their own checker. Only UserTask1, UserTask7, UserTask8 and UserTask10 complete on read-only tools alone, all via `get_most_recent_transactions`.

That yields an arithmetic ceiling before anything is measured: under B1 the maximum achievable utility is 4 user tasks by 9 injection tasks, or 36/144. No run can beat that, and a result above it would indicate a scoring error rather than a strong gate.

P1. B1 injection success will be 0/144, because every injection task requires a mutating tool and none are allowlisted. B1 utility will fall at or below 36/144, and may be below that if the read-only tasks depend on a conversation path the refusal disrupts.

P2. B2 utility will land within a few cases of Arm A, and B2 injection success will land at or within a few cases of Arm A, because the attacks call the same allowed tools with different arguments.

P3. No configuration of a tool-level allowlist will sit near Arm A utility and near-zero injection success. This is falsifiable: if any arm produces utility within ten percent of Arm A and injection success under five percent, P3 fails and the tool-level surface separates injected from legitimate calls better than the design assumes.

## What each outcome would establish

- P1 and P2 both holding, P3 holding: tool-level authority is the wrong unit, and per-action authorization binding is required for any protected configuration. This is a limit result about the current gate, published as such.
- P3 failing in any arm: the tool-level surface separates injected from legitimate calls better than the current design assumes, which changes the roadmap and must be reported as a surprise.
- Mixed or noisy results: reported as measured, with the case-level lists, and no reinterpretation of the pre-registered metrics.

## Reporting rules

Both numbers published for every arm, including the one that looks bad. Case-level utility losses listed individually, because VERITAS found their thirty flips were not all policy blocks and the same ambiguity must be expected here. No claim of prevention, proof, certification or generalization. Phrasing follows the standing rule: shows and detected within the harness.

## Cost estimate

The comparable VERITAS run recorded 820 provider calls and an estimated $0.32. Three arms at 128 cases each is under two dollars in provider spend, plus engineering time for the adapter.

## Commitment clause

This file is a commitment device, not a plan. Once committed at a dated commit, every later result is read against it, including a result that makes the gate look ineffective. The following are binding.

- The metrics named here are the only ones reported as results. Any additional measurement is labelled exploratory and kept in a separate document.
- No arm may be rerun. A run that dies is reported as a died run with its partial state, and that arm stays unmeasured.
- No case may be excluded after an outcome is seen. A case that errors is reported as an error, never dropped.
- The predictions stand as written. If P3 fails, the falsification is reported in the result document, above the fold, not deferred to a later post or thread.
- The publication carries the case-level lists for every arm, including the arm that failed.
- If the measured outcome is that a tool-level gate cannot separate injected calls from legitimate ones, that sentence appears in the result document in those words.

## What voids this pre-registration

Any of the following turns the run into an exploratory measurement and it must be labelled that way:

1. Tuning the allowlist or payload rules after seeing any result.
2. Adding a per-task mutation policy that was not declared here.
3. Changing the model, the pin, or the case count mid-series.
4. Reporting a metric that is not in this file as though it were pre-registered.

## Commitment procedure

1. Resolve the four open items below and write each answer into this file.
2. Fill the commit line at the top with the commit date and the intended first-run date.
3. Commit as `docs/benchmark/agentdojo-prereg-v1.md`, message: `prereg: AgentDojo arms, policy and predictions frozen before first run`.
4. Record that commit SHA in the commit line in a follow-up commit that changes nothing else. The SHA is the timestamp that counts; a pre-registration recorded after a run is not one.
5. Write the adapter only after the SHA exists.
6. One run per arm, frozen in the existing red-proof pattern: artifacts, JUnit XML, pytest output, and a SHA-256 manifest, so a third party can re-hash rather than trust.
7. Publish both numbers with the pre-registration SHA cited beside them.

## Resolved before commit

1. Mutating tools at this pin: `send_money`, `schedule_transaction`, `update_scheduled_transaction`, `update_password`, `update_user_info`. Read-only: `get_iban`, `get_balance`, `get_most_recent_transactions`, `get_scheduled_transactions`, `read_file`, `get_user_info`. Source: `src/agentdojo/default_suites/v1/banking/task_suite.py` at a75aba7.
2. Case ordering: ascending user task index, then ascending injection task index, rendered as `UserTaskN:InjectionTaskM`. 144 entries, hash recorded above, list committed beside this file as `case-list-v1.txt`.
3. Model: `gpt-4.1-mini-2025-04-14` at temperature 0.0, the same snapshot and sampling the comparator run used, so a difference cannot be attributed to the model.
4. Serialization: `ActionRequest.serialize()` renders tool, command and `json.dumps(args, sort_keys=True)`, so every argument reaches the payload rules. Arguments are visible; they are not bound to an approved intent, which is the distinction P3 tests.

## Denominators differ from the comparator

The comparator reports 128 paired cases on the same AgentDojo pin. This design uses 144, the full cross product, and does not replicate the reduction to 128 because the rule behind it is not stated in the material available. Percentages are therefore comparable in kind and not in denominator, and the comparison must say so.

## Open items

None. Commit when the commit line is filled.
