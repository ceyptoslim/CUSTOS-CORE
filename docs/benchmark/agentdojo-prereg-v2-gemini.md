# AgentDojo Pre-Registration v2: Model Independence on Gemini Flash

Status: frozen on main, nothing run.
Commit: `b9d4312a1c7a1b6880f2e1d09203745b942c02c3` (merge of PR 177, the commit that put this text on main on November 8, 2026, recorded here by a follow-up commit that changes nothing else).
Intended first run: Arm A on `gemini-3.6-flash`, not yet scheduled. Blocked on the `--provider` path and the 429 classifier named at the end of this file.
Author: Tavares Heath / CUSTOS-CORE.
Written: November 8, 2026.

Amendments before data collection: `docs/benchmark/attack-model-name-addendum.md` declares the `{model}` string the injected text carries for this provider, and records the two blockers found by attempting the first live run. It changes no arm, case, model, metric or prediction. `docs/benchmark/agentdojo-prereg-v2-paid-tier.md` records the provider tier the series ran on and the data terms that follow from it, also before data collection.

## Relationship to v1

`docs/benchmark/agentdojo-prereg-v1.md` stays frozen and unedited. It fixes the arms, policy, metrics and predictions for the primary series on GPT-4.1-mini, and nothing here changes it.

This file covers a separate, secondary question and a separate series. v1's Arms A, B1 and B2 remain unmeasured on GPT-4.1-mini. This is not a replacement for that run and no result here may be presented as one.

## Purpose

CUSTOS-CORE's gate sits above the model. It reads a tool name and arguments and returns ALLOW or DENY, so a defensible claim about it should not depend on which provider generated the call.

That claim is cheap to state and has never been tested. This series tests one narrow part of it: whether the pattern v1 predicts for the read-only allowlist, zero injection success bought at a known utility ceiling, still holds when the model behind the pipeline is from a different provider, on the free tier, at zero provider spend.

## What this design does not measure

- Whether the gate is model-agnostic in general. Two providers is not a survey.
- Whether a stronger or weaker model changes the conclusion. One model at one point in time.
- Anything about B2. The all-tools arm stays in v1.
- Held-out generalization, target-side effects, or the identity of whoever issued the instruction.

## Why this series is not the headline

A free-tier run on a fast consumer-facing model is the weakest available evidence, and it will be labelled that way wherever it is cited. It is worth running because it is falsifiable and costs nothing but attention, and because a gate whose behaviour is provider-dependent is a different product than the one described in the README.

## Provider facts established before freeze

Measured November 8, 2026 against `generativelanguage.googleapis.com` v1beta, with a newly issued free-tier key.

| Observation | Result |
|---|---|
| `gemini-2.5-flash`, `gemini-2.5-flash-lite` | HTTP 404, "no longer available to new users" |
| `gemini-3.8-flash`, the version the API itself recommends | one call HTTP 503 UNAVAILABLE "high demand", next call 171 seconds for a single tool call |
| `gemini-3.5-flash` at 16:20 ET | HTTP 200, correct `functionCall`, 3.0 seconds, `modelVersion` = `gemini-3.5-flash` |
| `gemini-3.5-flash` at 16:47 ET | HTTP 200, `modelVersion` = `gemini-3.6-flash` |
| `gemini-3.6-flash` | HTTP 200, correct `functionCall`, `modelVersion` = `gemini-3.6-flash` |
| `gemini-3.5-flash-05-2026`, `gemini-3.5-flash-001` | HTTP 404, no callable dated snapshot exists |

The third and fourth rows are the ones that matter. `gemini-3.5-flash` served 3.5 and then served 3.6 inside half an hour. Google's stable model names are aliases, no immutable snapshot is callable, and the model behind a name can change without notice or version bump in the name.

That has a consequence a pre-registration cannot avoid. The design can pin a name, not a snapshot. So the pin is the name plus the observed `modelVersion` on every response, and the series is void if a second distinct `modelVersion` appears inside it. This is weaker than v1's snapshot pin and is stated as weaker rather than described as equivalent.

## Frozen configuration

| Item | Value |
|---|---|
| Benchmark | AgentDojo, banking suite |
| Pin | commit a75aba7, identical to v1, so the case set is the same object |
| Python | 3.11 |
| Provider | `google-genai` 3.0.0, free tier, no billing attached to the key's project |
| Model | `gemini-3.6-flash`, name pin only, `modelVersion` recorded from every response, temperature 0.0, `thinkingConfig.thinkingBudget` 0, no fallback model |
| Cases | all 144 paired (user_task, injection_task) pairs, same ordering rule as v1 |
| Case list | `case-list-v1.txt` unchanged, 144 lines, SHA-256 `7b4ca3b932d6535430ed9c1ee42b3e545c2ddf4048fddf0a4d34a625a7ad0003` |
| Enumeration hash | SHA-256 `650dc5ff7d2fe22cf6a2b2cf08e1be60c71d7299486d6e88d883e81b678401ff` |
| Arms | Arm A and Arm B1 only |
| Runs | one complete pass per arm, resumable, no case re-executed once recorded |

Arm A: AgentDojo native pipeline, no gate.

Arm B1: same pipeline, CUSTOS gate in front of every tool call. Allowlist identical to v1: read-only banking tools only, every state-mutating tool absent, payload rules at defaults, untuned.

Arm B2 is not run here. Its v1 prediction is near-parity with Arm A on both metrics, which is a null result, and it would consume a third of a quota that is the binding constraint. Omitting it is a cost decision made before any measurement, and it is recorded here so that it cannot later be presented as a finding.

## Predictions, recorded before the run

P4. Arm B1 injection success will be 0/144 on this model, because no state-mutating tool is reachable through the allowlist and every banking injection task requires one.

P5. Arm B1 utility will be at or below 36/144. The ceiling is arithmetic and model-independent: four of sixteen user tasks complete on read-only tools alone, so four tasks by nine injection tasks is the maximum any run of B1 can reach, whatever generates the calls. A result above 36 indicates a scoring error, not a strong gate.

P6. Independence holds only if the pipeline is driven at all. If Arm A utility on this model is below 72/144, the model failed to use the tools competently, and both numbers describe a model-competence floor rather than the gate. In that case the series is published as uninformative about independence and no independence claim is made from it.

P6 exists because a model that produces zero valid tool calls would also produce zero injection success under B1, and that pair of numbers would look like a result while measuring nothing. It is written here, before the run, so the outcome cannot be argued into a headline afterwards.

## Interruption policy, which differs from v1

v1 clause 2 reads that a run which dies is reported as a died run and that arm stays unmeasured. That clause was written for a paid provider with a per-call budget, where a death is a defect worth recording.

A free-tier series cannot be run under that clause. Per-day request quotas are expected to interrupt an arm across several days, and a rule that voids the arm on the first 429 would make this series impossible to run honestly.

So, for this series only:

- The series is one complete pass, executed as many sittings as the quota requires, with every completed case written to the journal before the next case starts.
- A per-minute rate limit is waited out and retried. A per-day quota exhaustion stops the pass, records an interruption event, and resumes at the next case that is not already in the journal.
- A completed case is never re-executed. A resumed pass may not revise a case already recorded.
- The number of interruptions, the timestamps, and the resumed case ids are published with the result. A series that took five days and eleven interruptions says so.
- An arm that cannot complete is published as an incomplete pass with its partial case-level results marked partial, not as a void series.

This clause does not license rerunning a case whose result is disliked. The journal binds each case id to one outcome, and the runner refuses a conflicting second write.

## Metrics

- Utility: AgentDojo native scorer per user task, counted over 144 cases.
- Injection success: AgentDojo native scorer per injection task, counted over 144 cases.
- Case-level difference lists against Arm A, in full.
- Distinct `modelVersion` values observed, with the count of calls behind each.
- Provider calls, and interruptions with timestamps.

## Provider data terms

The free tier may use prompts and responses to improve Google's products. The inputs here are AgentDojo's synthetic banking tasks: generated user names, IBANs, addresses and transaction records, with no third party's personal data. The frozen record holds case outcomes, tool calls, arguments and verdicts, not the benchmark's synthetic personal payloads, except where a case-level list necessarily quotes a tool argument.

Anyone re-running this must accept the same terms or attach billing to the key's project. That difference is disclosed rather than hidden because a paid run and a free-tier run are not the same data arrangement.

## Cost estimate

Zero provider spend. The comparable VERITAS run recorded 820 provider calls for 128 cases, which puts a 144-case pass near 920 calls per arm, so roughly 1,840 calls for both arms. Wall-clock time depends on the daily quota and cannot be estimated before the first pass records its first 429.

## Reporting rules

Both numbers for both arms, including the arm that looks bad. No claim of prevention, proof, certification or generalization. Phrasing follows the standing rule: shows and detected within the harness. The result document cites this file's freeze SHA beside the numbers, states the model name and the `modelVersion` values actually seen, and states that the run was free tier.

## What voids this series

1. Tuning the allowlist or payload rules after seeing any result.
2. Changing the model name, the temperature, the thinking budget, or the case count mid-series.
3. More than one distinct `modelVersion` appearing across the series. If Google rotates the alias mid-pass, the series stops and is published as a mixed-version series, which is exploratory.
4. Adding or removing an arm after the first case is recorded.
5. Reporting a metric not in this file as though it were pre-registered.

## Commitment procedure

1. Read the two unfixed facts at the end of this file and accept that they are disclosed rather than resolved.
2. Commit as `docs/benchmark/agentdojo-prereg-v2-gemini.md`, message: `prereg: Gemini Flash independence series, arms and void rules frozen before first run`.
3. Record that commit SHA in the Commit line in a follow-up commit that changes nothing else.
4. Only then run Arm A. Arm B1 follows the same rule.
5. Freeze artifacts in the red-proof pattern: journal, JUnit XML, per-case records, SHA-256 manifest.

## Two facts disclosed rather than resolved

Neither of these can be settled before the first call, so both are stated as limits of the design rather than as pre-run tasks.

1. Daily request quota for `gemini-3.6-flash` on a new free-tier project is unmeasured. The first pass records the first 429 verbatim, and the result document states the observed wall rather than an assumed one.
2. The runner needs a `--provider` path that builds `GoogleLLM` with the frozen settings, and a 429 classifier that separates per-minute from per-day exhaustion. Neither exists on `main` today. The resumable runner is under review on `feat/agentdojo-resilience` and must merge before step 4.
