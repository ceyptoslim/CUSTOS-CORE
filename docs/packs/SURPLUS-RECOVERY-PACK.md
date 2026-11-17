# Surplus-Recovery Outreach Policy Pack

**Status:** shipped as config-only components (`packs/surplus_recovery.py`,
`packs/verified_statutes.json`, `tests/test_surplus_pack.py` — 38 tests).
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
| 1b | `surplus_court_citation_gate` | DENY | Any court citation (`Smith v. Jones, 123 So. 3d 456`, `500 U.S. 123`, `2026 WL …`) not covered by the owner-verified case registry — the Nippon v. OpenAI fabricated-citation class |
| 2 | `surplus_guarantee_language` | DENY | Guaranteed / risk-free / 100%-success outcome claims |
| 3 | `surplus_upl_risk` | DENY | Legal-advice claims, attorney identity, court-representation claims (UPL exposure) |
| 4 | `surplus_predatory_urgency` | DENY | "Act now", "final notice", "last chance", lose-it-immediately pressure |
| 5 | `surplus_fee_structure` | AUDIT | Percentage-fee phrasing — flagged for owner review against the executed fee agreement |

## The fail-closed design (the whole point)

Both registries — `packs/verified_statutes.json` (statutes) and `packs/verified_cases.json` (court cases) — **ship EMPTY**. Until the owner verifies a
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

**Where the owner's registry lives.** The shipped `packs/verified_statutes.json` stays
empty, and two tests pin that, because a commit must not be able to make a citation pass.
An owner's verifications are deployment data: point `CUSTOS_VERIFIED_STATUTES_PATH` and
`CUSTOS_VERIFIED_CASES_PATH` at files outside version control. Unset means the empty
shipped file, which denies every citation. A path that points at a missing or malformed
file also denies, never allows.

The citation gates run on that route. `load_pack()` installs them as the tenant's
`precheck`, which `/v1/evaluate` consults before the policy engine, so the endpoint
and `evaluate_outreach()` cannot diverge in ordering. Before that hook existed the
endpoint consulted the engine only: a draft citing a hallucinated statute was ALLOWED
there while the same draft was denied in-process (issue 205, evidenced by the
single-host demo transcript of 16 November 2026).

## Does not claim (frozen)
- Citation identity, not the proposition asserted about the citation. Measured 16 November
  2026: with `s. 197.582` owner-verified, a draft reading "Under s. 197.582 the clerk must
  disburse within 60 days" is ALLOWED, because the section exists and is verified. The
  section requires no such thing; the claim period is 120 days and the clerk acts within 90
  days after it. Verifying a citation therefore clears the citation, not what the sentence
  says it means. A pack that checks propositions is a different and larger build.


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
