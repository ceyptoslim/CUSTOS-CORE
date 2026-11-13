# Record: the provenance series on arm B2 (November 12, 2026)

Two runs of the AgentDojo banking suite, 144 cases each, arm B2 with the gate on and
all eleven tools allowed. They differ in one flag: where the recipient list came
from. Pre-registration v5 (`agentdojo-prereg-v5-provenance.md`, frozen at
`7e1e18a`) predicted all four outcomes below before either run started.

| Run | `--recipient-source` | Utility | Injection success | Errors | Decision records | Recipient refusals |
|---|---|---|---|---|---|---|
| P-declared | `declared` | 93/144 | 0/144 | 0 | 327 (301 allow, 26 deny) | 26 |
| P-derived | `derived` | 105/144 | 2/144 | 0 | 306 (297 allow, 9 deny) | 9 |

Both runs: model `gemini-3.6-flash`, one model version each, attack `direct`,
144-case list `case-list-v1.txt`, temperature 0, thinking budget 0, provider Google
paid tier, zero interruptions.

## What the numbers show

**P5.1 held.** No injection lands on the declared arm. The interesting part is not
the zero but what produced it: 26 money-tool calls named a recipient outside the
frozen list and were refused with rule `recipient_not_permitted` in the same
decision stream as the gate's own decisions. The attack was attempted far more
often than twice and was refused every time.

**P5.2 held.** Both landings occur where the list was learned from what the agent
read during the episode.

**P5.3 did not hold.** The declared list costs 12 utility points against the derived
arm and 14 against the earlier v3 arm B2 figure of 107. A frozen list refuses
legitimate payments to payees it could not know in advance. That is the price of
provenance and it is a finding, not a defect to explain away.

## What these numbers do not establish

**Not a rate.** Two of 144 against zero of 144 is an observation, not an effect
size; Fisher's exact two-sided p is 0.498, the same figure the v3 series carried.
What the run supports is a mechanism, visible in the refusal counts (26 against 9),
not a claim that one policy reduces attacks by any measurable proportion.

**The derived arm's learnings are not in its record.** The runner of this date wrote
the manifest before the first case, so the list at case 144 exists nowhere in the
run's own files. A post-hoc scan of the per-case logs finds six IBAN-shaped tokens
and no occurrence of the attacker's recipient `UK12345678901234567890`, which means
how the two derived-arm landings paid out is not established from the logs on hand.
It is recorded as unresolved rather than explained. The defect is fixed in the
runner that now writes `recipients-{arm}.json` with the start snapshot, the end
snapshot and the refusal count.

**Single model, single attack, one run per arm.** Nothing here bears on a different
model, a different attack, or a repeated run. The model's own resistance is a
confound this design cannot separate, which is why the refusal count rather than the
landing count is the load-bearing number.

## Why the series exists

A tool-level allowlist cannot separate a legitimate `send_money` from an injected
one, because the discriminating information is the recipient and not the tool name.
The next question was what a recipient policy is worth when its list arrives through
the channel the attack controls. The answer recorded here is that the policy shape
was identical in both runs and the provenance decided the outcome.

## Artifacts

Both runs live under `runs/agentdojo-B2-declared/` and `runs/agentdojo-B2-derived/`
in the operator's workspace: journal, decisions, results, manifest, `recipients-B2.json`
and 144 per-case logs each. They are not committed to this repository. An earlier
discard is kept beside them under `runs/agentdojo-B2-declared-WRONG-ATTACK/`: 75
cases started under `important_instructions` by mistake and stopped, kept as evidence
because prereg v5 did not pin the attack name. No arm in this record is that run.
