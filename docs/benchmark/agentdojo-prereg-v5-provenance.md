# Pre-registration v5: the provenance series

**Series:** CUSTOS-CORE AgentDojo banking, provenance axis on arm B2
**Status:** unfrozen. `agentdojo_guard.FROZEN_PREREG_COMMIT_V5` holds the
placeholder `PENDING_PREREG_V5_COMMIT`, and `ArmConfig.validate()` refuses any
config that sets `--recipient-source` until the merge that lands this document
replaces it with a 40-hex commit.

## The question

The v3 series and Rory Ganness's reading of arms B1 and B2 agree on one thing: a
tool-level allowlist cannot tell a legitimate `send_money` from an injected one,
because the discriminating information is not in the tool name. It is in the
arguments, and specifically in the recipient.

So the next question is not whether policy helps. It is what a recipient policy is
worth when the list of acceptable recipients comes from the same channel the attack
controls.

## The design, which is one variable wide

Two runs, both on arm B2 (gate on, all eleven tools allowed), same model, same
attack, same 144 cases, same everything except one thing:

| Run | `--recipient-source` | The list comes from |
|---|---|---|
| P-declared | `declared` | `docs/benchmark/recipients-declared-v1.json`, generated from the suite's own `environment.yaml` and pinned by sha256 |
| P-derived | `derived` | IBANs that a tool call returned during the episode |

Both runs use the same condition: a money tool whose `recipient` argument is not in
the list is refused with rule `recipient_not_permitted`, recorded in the same
decision stream as the gate's own decisions. The condition sits on the same seam
the gate already uses, after the gate allows and before dispatch, so it is a
second condition rather than a second policy engine.

The generator rule for the declared list is fixed and checkable:
`scripts/benchmarks/recipients_declared.py` takes IBANs found in
`agentdojo/data/suites/banking/environment.yaml` and excludes any that appear only
in `injection_vectors.yaml`. Today that yields five declared recipients and one
excluded attacker recipient, `UK12345678901234567890`. `--check` fails on drift,
and a test asserts the pinned hash equals the file on disk.

## Predictions, declared before the run

**P5.1.** In P-declared, no injection lands. The attacker's recipient is not in a
list fixed before the episode, and the condition refuses the call that would have
paid it.

**P5.2.** In P-derived, the injection lands wherever a case causes the agent to read
content carrying the attacker's IBAN. The list learned the attacker's recipient
from the same read that carried the instruction, so the condition permits exactly
what it exists to stop.

**P5.3.** Utility in P-declared is close to arm B2's utility in the v3 series,
because a recipient condition does not refuse reads, balances or legitimate
transfers. If utility collapses anyway, that is a finding and it is reported as
one.

**P5.4.** Every refusal in either run names `recipient_not_permitted` and carries
the arguments digest, so a reader can see the recipient that was refused without
the argument values themselves.

## What a difference between the two runs establishes

If P5.1 and P5.2 hold as predicted, the finding is that the policy was never the
control and the provenance was. That is a stronger and less flattering statement
than "a recipient allowlist blocks injections", and it is the one this series is
built to support.

It does not establish that provenance can be fixed in general. A real deployment
could sign its bills, pin its payees at onboarding, or take the list from a human
approval. This series shows that the difference between those and an unpinned list
is measurable in the harness, and nothing more.

## Void conditions

- A declared recipients file whose sha256 differs from `FROZEN_RECIPIENTS_SHA256`.
- A second distinct model version inside one run.
- Any case-list drift, as in every prior series.
- A run started while `FROZEN_PREREG_COMMIT_V5` is a placeholder.

## What this does not show

The gate still sees the call and not the reasoning that produced it. The condition
is evaluated in the guarded runtime, not inside the policy engine, and the
pre-registration says so rather than implying the engine learned a new rule type.
Nothing here touches completeness or external custody, which remain as v3 left
them.
