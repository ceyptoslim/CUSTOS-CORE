<!-- citation-check: on -->
# Pre-Execution Authorization: What the Code Does

**Pinned to:** `CUSTOS-CORE @ f207af7c3ce6fa3a5233d850128fcdaff4bd1cc0` (2026-11-04, main)
**Purpose:** replace an earlier summary that carried claims the repository does not support. Every statement below cites a file and line, and `scripts/check_doc_citations.py` fails the build if a fragment stops sitting on the line this document says it sits on. Section 6 lists what was withdrawn and why.

---

## 1. The boundary is before execution, not after

`custos/action_gate.py:2` calls the module a "Pre-Flight Action Gate" and says it "evaluates a PROPOSED agent action BEFORE execution." The same docstring separates it from output governance: output governance judges what an agent said, this judges what an agent proposes to do.

That distinction is the whole thesis. A filter that inspects content after generation reviews an artifact that already exists. A gate that runs before the effect-bearing call is a decision about whether the artifact is allowed to become an effect.

## 2. Deny by default, in a fixed order

The evaluation order is enumerated in the module docstring (`custos/action_gate.py:16-31`) "Semantics — fail-closed everywhere:" and implemented in that order.

1. **Unknown tenant denies.** `custos/action_gate.py:281` "Fail-closed: unknown tenant" and `custos/action_gate.py:293` "No ungoverned action evaluation". An unrecognized tenant returns DENY rather than running an evaluation against no policy at all.
2. **Unregistered tool denies.** `custos/action_gate.py:297` "Deny-by-default tool allowlist". Every tool must appear in the tenant allowlist; the denial reason string is `action_gate_tool_not_allowlisted`, so an unconfigured gate denies all actions rather than passing them through.
3. **Dangerous command classes deny before content rules run.** `custos/action_gate.py:316` "Dangerous command classes". Exfiltration, destructive operations, privilege changes, package installs, process tampering, credential access, reverse shells, and attempts to disable the governance layer itself are matched against the serialized action.
4. **Tenant content rules compose.** `custos/action_gate.py:332` "content rules compose". The existing policy engine evaluates the serialized action, so injection, PII, and tenant pack rules apply at the action layer as they do at the content layer.
5. **Every decision is audited.** `custos/action_gate.py:335` "Audit every decision". The digest is read once at `custos/action_gate.py:285` "cited_digest = (" and written into each of the three record calls: `custos/action_gate.py:310` "policy_digest=cited_digest", `custos/action_gate.py:326` "policy_digest=cited_digest", `custos/action_gate.py:342` "policy_digest=cited_digest".

Fail-closed on the forwarding side is separate and equally explicit. `custos/execution.py:10` "any exception during forwarding = block, never forward", implemented at `custos/execution.py:381` "Fail-closed: any unexpected error = block", and restated for the circuit breaker at `custos/execution.py:233` "any exception = block, not forward". An unexpected error cannot become an allow.

Strict interpretation of the policy answer is enforced in `custos/opa_engine.py:78` "only literal True authorizes" and again at `custos/opa_engine.py:179` "only literal True authorizes". A truthy value does not authorize.

## 3. There are two authorization outcomes, plus one advisory flag

`custos/policy_engine.py:18-21` `ALLOW = "allow"` defines `PolicyAction` as ALLOW, DENY, and AUDIT. `custos/policy_engine.py:140-141` "DENY takes precedence over AUDIT" fixes the precedence order.

AUDIT is not a third authorization outcome. It flags a matched rule on a call that is otherwise allowed, so the record carries a marker without the call being stopped. It does not freeze a timeline and it does not hand the decision to anyone else. Describing the system as resolving to `{ALLOW, DENY, ABSTAIN}` is wrong in the specific sense that `ABSTAIN` does not exist and `AUDIT` does not behave like it.

## 4. What the record carries, and what it does not

`custos/policy_citation.py:3-9` "sha256 digest of the exact in-force policy set" states the property: every emitted record cites the digest of the policy set it was enforced against, read on the same code path that made the decision. The digest is computed at emission rather than cached, deliberately, so an in-flight policy change shows up in the very next record. The gate computes it in `custos/action_gate.py:165-181` "def _cited_policy_digest".

Each record is hash-chained to its predecessor through `custos/audit.py:328` "def compute_record_hash(record, previous_hash: str)", which makes a silent edit to the middle of a chain detectable to anyone holding the chain. The reconciliation path records the same citation `custos/action_gate.py:264` "policy_digest=digest".

What this is not: ground truth. The record is produced by the system being governed. It is a statement about a decision, made by the decider, and it is checkable against the policy digest only to the extent the digest computation is trustworthy. In a dispute about whether an action was in bounds, the record is the artifact that outlives the disagreement. It does not settle who was right, because nothing in this lane can.

## 5. Explicitly out of scope

`custos/action_gate.py:12-14` "does NOT contain infrastructure-level sandbox escapes and must never be claimed to." The gate is defense in depth: the network layer, the runtime layer, and the OS layer remain necessary, and the module forbids the claim that it replaces them.

The honest scope sentence is therefore: this governs agent actions inside deployments that route through CUSTOS. It says nothing about calls that do not route through it. How many such paths exist in a given deployment is the question a reviewer should ask first, and the answer is a property of the deployment, not of the gate.

## 6. Claims withdrawn from the earlier summary

| Claim | Status | Reason |
| --- | --- | --- |
| Three-member verdict space `{ALLOW, DENY, ABSTAIN}` | Not implemented | The string "abstain" does not occur in any tracked file at the pinned commit (verified with `git grep`, command in section 8). `PolicyAction` is ALLOW, DENY, AUDIT `custos/policy_engine.py:18-21` `ALLOW = "allow"`. |
| ABSTAIN freezes execution and escalates to a human arbiter | Not implemented | No escalation path exists in the code. The only occurrences of "escalat" in `custos/` are the privilege-escalation command class. |
| Cryptographically verified ALLOW token | Not implemented | The digest is a citation written into a record `custos/policy_citation.py:3-9` "sha256 digest of the exact in-force policy set", not a minted authorization artifact. The weaker claim is the true one. |
| "Non-bypassable" enforcement, "hard software sandbox" | Rejected | Directly contradicted by `custos/action_gate.py:12-14` "does NOT contain infrastructure-level sandbox escapes". |
| The record is a "checkable, deterministic ground truth" | Rejected | The record is written by the governed system. It is testimony with a policy digest attached, not an independent arbiter. See section 4. |
| SSRN abstract ids 7316378 and 6300558 | Unverified | Neither resolves to a document under this project's authorship on inspection. Remove unless the documents can be produced. |
| arXiv 2607.07405 cited as describing this architecture | Misattributed | That paper is by Reddy, Challaram, and Basu. It is related work, not a description of this implementation. See section 7. |

## 7. Related work, cited correctly

Reddy, Challaram, and Basu, "Reason Less, Verify More: Deterministic Gates Recover a Silent Policy-Violation Failure Mode in Tool-Using LLM Agents," arXiv:2607.07405 (v1 2026-07-08, v2 2026-07-11).

What it shows: in the τ²-bench airline domain, 78 percent of observed failures on a budget agent are silent wrong-state failures with no tool error. A suite of four read-only pre-execution gates raises full-benchmark success from 29.6 percent to 42.0 percent on gpt-4o-mini (+12.4 points, P=0.0012), reproduces on a disjoint seed set, and two negative controls bound the mechanism. The authors are careful about their own limits, including an n=5 frontier result they label as non-replicated.

How it relates: their gates are read-only checks inside an evaluation harness. This project is an enforcement boundary plus a cited record. Their result supports the premise that pre-execution checks change outcomes. It does not test this implementation, and it should never be cited as though it did.

## 8. Re-walk the claims

```
git clone https://github.com/ceyptoslim/CUSTOS-CORE
cd CUSTOS-CORE
git checkout f207af7c3ce6fa3a5233d850128fcdaff4bd1cc0
git grep -in abstain f207af7c3ce6fa3a5233d850128fcdaff4bd1cc0 | wc -l   # expect 0
sed -n 16,31p custos/action_gate.py    # the deny-by-default order
sed -n 18,21p custos/policy_engine.py  # ALLOW, DENY, AUDIT
sed -n 12,14p custos/action_gate.py    # the scope limit
python scripts/check_doc_citations.py --selftest   # the guards on this document
```

Any test count quoted in public writing must name the commit that produced it, because a count without a revision decays into a claim nobody can check.

## 9. The short version

A pre-execution authorization boundary for agent actions: unknown tenants and unregistered tools deny by default, dangerous command classes deny before content rules run, every decision is recorded with the sha256 digest of the policy set that decided it, and any failure in forwarding blocks rather than allows. It governs only the calls that route through it, and it does not contain sandbox escapes. The record it produces outlives the argument about whether an action was in bounds. It does not settle that argument.
