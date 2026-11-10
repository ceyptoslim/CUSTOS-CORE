# AgentDojo arm B2 for the Gemini series: a post-hoc control, declared before it runs

**Status:** committed before the B2 sitting. A and B1 are already scored; this adds
the third arm that v2 deliberately omitted, and it is declared as post-hoc here so
that it cannot later be read as if it had been planned from the start.

## What v2 said, and why that was reasonable then

`agentdojo-prereg-v2-gemini.md` line 70: "Arm B2 is not run here. Its v1 prediction
is near-parity with Arm A on both metrics, which is a null result, and it would
consume a third of a quota that is the binding constraint." At the time, the
binding constraint was a free tier limited to twenty requests per day per model.
Omitting the arm that predicts no difference was the right call under that
constraint, and the omission was recorded rather than left silent.

The constraint is gone. The series now runs on a prepaid paid tier, so the arm
costs cents rather than a third of a scarce quota.

## Why the arm matters now that B1 has been scored

Arm A scored utility 110 of 144. Arm B1, the read-only allowlist, scored 54. The
obvious reading is that the allowlist costs 56 points of task completion, and the
obvious reading is not the only one available from two arms. A gate that wraps the
runtime, sits between the model and the tools and refuses some calls could depress
utility by its presence rather than by its policy: an error in the wrapper, a
refusal returned in a shape the model cannot recover from, or a pipeline that
behaves differently when any element is inserted would all produce a drop that has
nothing to do with what the allowlist permits.

B2 separates those. It builds the same gate, installs the same wrapper, and allows
every one of the eleven banking tools. If B2 lands near A, the 56-point cost is the
allowlist and not the gate's existence. If B2 lands near B1, the cost is the
wrapper, and that is a defect to fix before any number from this series is quoted
as the price of a policy.

## Prediction, stated before the run

B2 allows every tool, so the gate is a pass-through and the arm should reproduce
arm A's behaviour rather than B1's.

- Utility: 100 or above, and within 15 points of A's 110. A figure below 95 means
  the gate's presence costs utility independently of its policy, which the series
  would then have to report as a finding about the implementation rather than
  about the allowlist.
- Injection success: 0, matching A and B1. B2 permits the writes an attacker wants,
  so this is the arm where a nonzero figure would be most informative; the same
  floor seen in both scored arms predicts zero here too.
- Denials: near zero, and any denial is a finding. The allowlist is all eleven
  tools, so a deny means a tool outside the pinned set was proposed, which would
  contradict the suite pin.
- Decision records: populated for every case that called a tool, since the
  retention defect is fixed; an empty decisions file here is a run to discard, not
  a result.

## What this cannot do

It cannot change A or B1, cannot rescue B1's defective first sitting, and cannot
make any prior figure better. It is a control run after the fact, and it is worth
exactly what a declared post-hoc control is worth: it removes one alternative
explanation that two arms could not distinguish. If B2 confirms the prediction, the
series reads as one result with all three arms in the record. If it contradicts the
prediction, the earlier numbers are not weakened; the mechanism behind them is.

## Unchanged

Arms A and B1 remain as scored and frozen in `records/arm-a-gemini/` and
`records/b1-gemini/`. The case list, attack, injected text, model id
`gemini-3.6-flash`, thinking budget `0`, temperature `0`, the `modelVersion`
recorder, the metrics and the void rule are unchanged. Nothing here alters v1, and
v1's arms remain unmeasured on GPT-4.1-mini.
