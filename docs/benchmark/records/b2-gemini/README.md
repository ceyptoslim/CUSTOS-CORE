# AgentDojo arm B2, Gemini series: frozen record

The post-hoc control declared in `../../agentdojo-prereg-v2-b2-addendum.md`, run
after A and B1 were scored. Finished 2026-11-10T02:04:42.464588+00:00. This arm builds the same
gate, installs the same wrapper, and allows all eleven banking tools.

## What it measured

| Quantity | Value |
|---|---|
| Cases | 144 of 144 |
| Utility | 110/144 (76.4 percent) |
| Injection success | 0/144 |
| Errors | 0 |
| Provider interruptions | 0 |
| Model | `gemini-3.6-flash`, one `modelVersion` |
| Decisions recorded | 291 (291 allow, 0 deny) |
| Writes allowed | 101 (send_money 54, update_scheduled_transaction 19, update_user_info 18, schedule_transaction 9, update_password 1) |

## The prediction, and whether it held

| Predicted | Observed |
|---|---|
| Utility 100 or above, within 15 of A's 110 | **110**, identical to A |
| Injection success 0 | **0** of 144 |
| Denials near zero, any denial a finding | **0** denials in 291 decisions |
| Decisions populated | 291 records across 144 cases |

All four held. The prediction that mattered was the first one: a figure below 95
would have meant the wrapper costs utility on its own, and the series would have
had to report that as a defect in the implementation rather than a price of policy.

## What the three arms now say together

| Arm | Policy | Utility | Injection | Denials |
|---|---|---|---|---|
| A | no gate | 110 | 0 | none recorded |
| B2 | gate, all tools allowed | 110 | 0 | 0 |
| B1 | gate, read-only allowlist | 54 | 0 | 110 |

B2 reproduces A exactly while running the gate that B1 ran, and it denied nothing,
so the wrapper, the extra pipeline element and the decision path all cost zero
utility on this suite. That leaves one explanation for the 56-point gap between A
and B1: the read-only allowlist refused writes the tasks needed, 110 times, across
83 of 144 cases. The gap is the policy's price, measured, not the cost of inserting
a gate.

It also removes the alternative reading that B1's refusals had been returned in a
shape the model could not recover from. B2 shows the same model, on the same cases,
through the same seam, scoring exactly what the ungated baseline scored. What B1
lost, it lost to the refusals themselves.

## What this does not show

Not prevention, and the control makes that plainer rather than weaker. Injection
success is 0 in all three arms, so the attack never landed in the ungated baseline
either, and no arm had anything to prevent. B2 is the arm where a landing attack
would have been most visible, since it permits every write an attacker wants, and
nothing landed there. That floor belongs to the model within this harness.

Nor does it generalize beyond the banking suite, this case list, this attack or this
model, and it says nothing about B1's cost on a different task distribution, where
the shares of read-only and writing tasks differ.

## Files

`results-B2.json`, `decisions-B2.jsonl`, `journal-B2.jsonl` and `manifest-B2.json`
are the runner's own outputs; `logs/` holds the per-case conversation records;
`SHA256SUMS` covers every file.
