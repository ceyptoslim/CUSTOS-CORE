# Pre-registration v6: declared plus a recorded escalation

**Series:** CUSTOS-CORE AgentDojo banking, arm B2, escalation axis
**Status:** unfrozen. The axis does not exist in code yet, and
`ArmConfig.validate()` must refuse it until this text is frozen and its pin cites a
40-hex commit.

## The question

v5 measured the cost of provenance at 12 utility points. The declared list refuses
legitimate payments to payees fixed before the episode, and it refuses them for a
good reason: it has no way to tell a new legitimate payee from an injected one.

The question here is whether that cost is inherent or an artifact of the refusal
being final. A gate that can only refuse and allow forces a choice between safety
and utility. A gate that can also defer to a recorded decision does not.

## The design, one variable wide

One run, arm B2, all else held to the v5 declared configuration.

A money tool whose recipient is not in the declared list does not execute and does
not fail. It produces an escalation record: the recipient, the amount, the case, and
the digest of the arguments, written to the decision stream with verdict
`escalated`. The scripted approver then answers.

Two approver policies, both fixed before the run:

| Run | Policy | A permitted escalation does |
|---|---|---|
| E-refuse | `refuse_all` | nothing; the call stays unexecuted, which reproduces the v5 declared arm |
| E-allow | `allow_all` | the call executes on the approval, and the record carries both verdicts |

`refuse_all` exists so the escalation plumbing can be shown not to have changed the
v5 result by itself. If E-refuse does not reproduce the declared arm's 93 and 0, the
plumbing is not inert and the series stops.

## Predictions

**P6.1.** E-refuse reproduces the v5 declared figures inside noise: utility near 93,
injection 0, and the same refusal count. This is a control, not a finding.

**P6.2.** E-allow recovers most of the 12-point utility gap, because the payments the
declared list refused are arbitrary to a scripted approver that says yes.

**P6.3.** E-allow also admits the attacker's payments, at or above the derived arm's
two landings, because a scripted approver that says yes is not a control. This is the
prediction that matters: it separates "approval recovers utility" from "approval
recovers safety", and only the first is expected to hold.

## What this establishes

If P6.1 to P6.3 hold, the finding is that deferral buys utility and buys nothing
else, and that the human in the loop is a control only if the human can tell the two
cases apart. Stated as the stronger claim this series cannot support: it does not
show that a real approver with a rendered argument digest would fail, only that an
approver who cannot discriminate does.

## Void conditions

- Any deviation of E-refuse from the v5 declared arm beyond the recorded refusal count.
- A second model version inside a run, a case-list drift, or a run started against
  an unfrozen pin. These carry over from v4 and v5 unchanged.

## Open question this prereg does not answer

The approver here is a script. A later series would need a rendering study, since
deciding what an approver can see at the moment of decision is a different
measurement from whether approval preserves safety. Naming that boundary is the point
of writing it down now.
