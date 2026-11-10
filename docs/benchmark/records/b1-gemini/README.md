# AgentDojo arm B1, Gemini series: frozen record

One run of arm B1 (read-only allowlist) under the v2 pre-registration, on the
fixed harness, replacing the defective sitting disclosed in
`../../agentdojo-prereg-v2-b1-rerun.md`. Finished 2026-11-10T00:24:29.171276+00:00.

## What it measured

| Quantity | Value |
|---|---|
| Cases | 144 of 144 |
| Utility | 54/144 (37.5 percent) |
| Injection success | 0/144 |
| Errors | 0 |
| Provider interruptions | 0 |
| Model | `gemini-3.6-flash`, one `modelVersion` |
| Attack | `important_instructions`, naming the model "AI model developed by Google" |
| Temperature / thinking budget | 0.0 / 0 |
| Decisions recorded | 302 (192 allow, 110 deny) |
| Denial rate | 36.4 percent of decisions |
| Rule that fired | `action_gate_tool_not_allowlisted`, 110 times, and no other rule |
| Writes allowed | 0 |

The decision journal is the point of this record. The first B1 sitting ran under a
harness defect that discarded it, which left a utility figure of unknown cause;
this one carries 302 records naming every tool called and every refusal.

## Where the utility went

Arm A, the ungated baseline, scored 110 of 144. B1 scored 54. The difference is
not a single quantity, and the decision log separates it:

- **Cases never denied: 61, of which 36 completed.** The v2
  pre-registration forecast a read-only utility ceiling of 36 of 144, from four of
  sixteen user tasks being completable on read-only tools. The measured
  never-denied figure is exactly that ceiling.
- **Cases with at least one denial: 83, of which 18 still completed.** These
  are the cases where the gate refused a write and the task completed anyway,
  through another route or because the utility check did not depend on the write.
  They are why B1 sits above the structural ceiling rather than at it.

So the 56-point gap between the arms decomposes as 74 cases that lost the write
they needed, against 18 that survived a refusal, with 0 writes allowed anywhere in
the run. The allowlist held on every attempt: 110 denials, 55 of them
`send_money`, and not one write tool passed the gate.

## What this shows, and what it does not

It shows what a strict read-only allowlist costs in task completion on this
benchmark, with the refusals in a file that can be audited rather than summarised,
and it shows that the gate's denials are the operative cause: the rule that fired
is the same one 110 times, the denied tools are exactly the five that
persist effects, and no write ever reached the runtime.

It does not show that the gate prevented an attack. Injection success is
0 of 144 in this arm and was 0 of 144 in arm A as
well, so the attack never succeeded in the ungated baseline, and there is nothing
left for the gate to reduce. That floor is a property of the model within this
harness and is stated in arm A's record. No claim of prevention is made here.

## Files

`results-B1.json`, `decisions-B1.jsonl`, `journal-B1.jsonl` and `manifest-B1.json`
are the runner's own outputs; `logs/` holds the per-case conversation records;
`SHA256SUMS` covers every file so a third party can re-hash rather than trust.
