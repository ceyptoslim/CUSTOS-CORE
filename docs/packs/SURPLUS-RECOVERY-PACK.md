# Surplus-Recovery Outreach Policy Pack

**Status:** shipped as config-only components (`packs/surplus_recovery.py`,
`packs/verified_statutes.json`, `tests/test_surplus_pack.py` — 30 tests).
Functional working name only — **no brand naming** (naming pending attorney
clearance; commercial naming is a counsel decision).

**What it is:** a fail-closed compliance gate for AI-drafted tax-deed
surplus/overage recovery outreach letters. The owner's own surplus-recovery
pipeline (revival of the 2018–2020 claims business) is the first governed
workload — internal dogfooding, not an external claim.

## How it works

Composes ONLY existing components (`PolicyRule`, `PolicyEngine`,
`TenantManager`, `PolicyStore`). Zero core engine/API/schema changes.

| # | Rule group | Action | What it catches |
|---|---|---|---|
| 1 | `surplus_statute_gate` | DENY | Any Florida statute citation (`s. 197.582`, `F.S. 201.582`, `Fla. Stat. § …`, `Section …`) not in the owner-verified registry |
| 2 | `surplus_guarantee_language` | DENY | Guaranteed / risk-free / 100%-success outcome claims |
| 3 | `surplus_upl_risk` | DENY | Legal-advice claims, attorney identity, court-representation claims (UPL exposure) |
| 4 | `surplus_predatory_urgency` | DENY | "Act now", "final notice", "last chance", lose-it-immediately pressure |
| 5 | `surplus_fee_structure` | AUDIT | Percentage-fee phrasing — flagged for owner review against the executed fee agreement |

## The fail-closed design (the whole point)

`packs/verified_statutes.json` **ships EMPTY**. Until the owner verifies a
statute against official Florida sources (flsenate.gov) and enters it
themselves, **every statute citation in every draft is DENIED**. An
AI-generated/hallucinated statute number cannot pass this gate — there is no
registry entry for it to match. Missing or malformed registry file → also
denies everything (never allows). Pack tenant not loaded → denies evaluation
entirely. This is the anti-hallucination discipline of the project expressed
as a policy: **an AI never introduces a statute; only the owner does.**

Sabotage-verified: inverting the gate or pre-populating the registry fails
the shipped test suite (7 and 6 failures respectively).

## Usage

```python
from custos.tenant import TenantManager
from packs.surplus_recovery import load_pack, evaluate_outreach

tm = TenantManager()
load_pack(tm)  # tenant "surplus_recovery" + rules, persisted if a PolicyStore is configured
result = evaluate_outreach(tm, draft_text)   # .allowed is False on ANY deny
```

Pipeline integration target: the deployed CUSTOS-CORE service (`/v1/evaluate`,
tenant `surplus_recovery`) on the one-command VPS deployment — no local Docker
Desktop required.

## Does not claim (frozen)

- Not legal advice and not a law-practice tool; this is a content-compliance
  gate. "Consult your own attorney" is allowed (and encouraged) in letters.
- No statute in the shipped registry — the owner populates it exclusively
  from official sources. **No AI-suggested statute may be added without owner
  verification.**
- No commercial naming (working title only), no customers, no external
  deployments. The surplus pipeline itself is a separate system (not built
  here); this pack governs its outreach content only.
- Mock lead data (development) and real county records must never share a
  store — enforcement of that separation lives in the pipeline, not the pack.
