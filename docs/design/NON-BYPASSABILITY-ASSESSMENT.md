<!-- citation-check: on -->
# Deployment-level non-bypassability assessment: the reference deployment

This document answers one question about one deployment: for a defined effect `E` and a
defined boundary `B`, does every path capable of producing `E` sit inside `B`?

It exists because the exit-class register asks for an architectural argument rather than
the absence of a test, and because the answer for this deployment is negative. A
specimen whose answer is `yes` would not have exercised the method.

**Implementation:** CUSTOS-CORE, commit `c7fad9d` (public repository). **EABC version:**
v1. **Scope:** the reference deployment started from this repository's entry points. It
does not speak for any customer deployment, and it does not speak for the enterprise
assembly, which redeclares in its own inventory.

---

## 1. Four claims kept apart

Merging any two of these is how a declaration starts asserting more than it carries.

| Claim | What it is | What it establishes | What it does not |
|---|---|---|---|
| Declared scope | The effect, the boundary, and the portion of the system under assessment | Where the claim applies | That the scope is the right one |
| Path enumeration | Which paths are known to be capable of producing `E` | That these paths exist and where they go | That the list is complete |
| Path availability | Whether a named path is shown to produce `E` in this deployment, or merely argued to be possible | That the path is real, not hypothetical | That other paths exist |
| Path-set completeness | Whether the enumeration covers every such path within scope | That none is missing | That each is mediated |
| Mediation | Whether a given path actually traverses `B` | What happens on that path | Anything about unlisted paths |

The first two are declarations. The third is the one a verdict can turn on, because a
hypothetical bypass is not a bypass. The fourth can only be argued exhaustively or left
open. The fifth is the one with testable evidence per row.

## 1a. Three evidence states for a bypass, kept distinguishable

`DOES_NOT_CONFORM` needs a path that produces `E` while avoiding `B`. Observations of
very different strength can support that sentence, and merging them is how a declaration,
or somebody else's report, becomes a finding it has not earned.

- **`DECLARED`** — the architecture permits the path, argued from the code, with no
  observation of it executing. This is sufficient to open a row and insufficient for a
  verdict.
- **`REPORTED`** — an interested party reports an executed observation, and the artifacts
  needed for anyone else to check it are not available. Another team's run, quoted in a
  document with no preserved output, is `REPORTED` no matter how detailed the account is:
  a reviewer can read the report but cannot re-run it.
- **`DEMONSTRATED`** — an executed observation shows the path producing `E` with `B` absent
  from the loop, and the means to reproduce it are in hand. This is what `DOES_NOT_CONFORM`
  rests on.

An evidence state describes where an observation came from and how strongly it is
verified. It is not a conformance verdict, and the two must not be collapsed in either
direction: a strong state does not create a verdict, and a weak one does not make one
unavailable. Only `DEMONSTRATED` carries `DOES_NOT_CONFORM`. Promotion from `REPORTED` to
`DEMONSTRATED` needs the artifacts and an independent reproduction or equivalent
independent verification; repeating the reporter's conclusion is not verification, and
neither is a summary that quotes the artifacts instead of exercising them.

This document applies the same rule to itself. The `E1` observation is a runnable test in
`tests/test_unmediated_path_demonstrated.py`, so a reader reproduces it without us, which
is what lets the row say `DEMONSTRATED`. Had the observation arrived as somebody's written
account with no preserved output, the row would sit at `REPORTED` and the verdict would
have to fall back to `INSUFFICIENT_EVIDENCE`.

The distinction has a second use, which is where most assessments go wrong: a
demonstration has a *shape*. It is demonstrated against something specific, and the
demonstration transfers only as far as that something does. An assessment that says
`DEMONSTRATED` without naming what it was demonstrated against has quietly upgraded a
specimen into a universal claim.

---

## 2. Declarations

**`E1`** (in scope): a tool invocation reaches an upstream MCP server, which may act on
the world. This is the first half of the protected effect as the inventory defines it
(`docs/design/EXECUTION-PATH-INVENTORY.md:24`, "The protected effect is" an external state change
produced by an agent action that this deployment forwards).

**`E2`** (declared, not produced here): an outbound HTTP request to a decided target. This
is the enterprise execution path. See section 5 for why it gets no verdict here.

**`B`**: the pre-flight `ActionGate`, as reached by a client of this deployment through
the MCP stdio proxy. The decision API is deliberately *not* part of `B`: a caller that may
ignore the answer is a consumer, not an enforcement point, which is the inventory's
`not-effect-producing` status (`docs/design/path-inventory.yaml:120`, "None by itself. Returns a decision" and
`docs/design/EXECUTION-PATH-INVENTORY.md:57`, "no service in this deployment exposes it").

**Declared path set:** the six rows of `docs/design/path-inventory.yaml`, enumerated by
the repository rather than by this assessment, so that a reader compares this document
against a file that CI keeps honest.

**Path-set completeness for `E1`: NOT ESTABLISHED.** The inventory states the same thing
in its own words (`docs/design/EXECUTION-PATH-INVENTORY.md:46`, "Completeness here is an attestation, not a derivation"). A declared inventory is never read here as an exhaustive
one.

---

## 3. Per-path status for `E1`

| Path | Inventory status | Traverses `B`? | Capable of `E1`? | Per-path verdict |
|---|---|---|---|---|
| P1 stdio proxy | `mediated` | yes | yes | subject to `B` |
| P2 decision API | `not-effect-producing` | n/a | no | not a path to `E1` |
| P3 HTTP adapter | `not-present` | n/a | not in this deployment | not a path to `E1` here |
| P4 direct upstream | `unmediated-declared` | **no** | **yes, `DEMONSTRATED`** | **bypass** |
| P5 custody anchoring | `out-of-scope-by-construction` | n/a | no | excluded by the definition of `E` |
| P6 enterprise execute | `not-present` | n/a | not in this deployment | not a path to `E1` here |

P4 is the row that decides this document, and its own text says so
(`docs/design/path-inventory.yaml:160`, "Produces the same protected effect without passing the decision point."). The condition Stanislav attached to the verdict, that the
bypass must be able to produce *the same* effect, is what that sentence asserts and what
the row's assertion argues: a process holding credentials the upstream accepts connects
directly and the upstream runs the tool.

---

## 4. Verdict for `E1`: DOES_NOT_CONFORM

A known path capable of `E1` bypasses `B`. Under the reading this document follows, that
settles the verdict and makes path-set completeness irrelevant to it: a demonstrated
bypass does not become less demonstrated because the list is short.

**What the demonstration is.** The bypass is `DEMONSTRATED`, not merely declared, and the
observation is executable in this repository: the same in-repo upstream is spawned twice,
once behind the proxy and once with no gate object in the process at all
(`tests/test_unmediated_path_demonstrated.py:89`, "the upstream ran the tool"). The denied control is the other half, and it
is what makes the marker an effect signal rather than noise
(`tests/test_unmediated_path_demonstrated.py:112`, "which would be the gate failing open").

**What it is demonstrated against, which is the part that keeps the verdict honest.** The
upstream in that test is a stdio server that accepts any caller and requires no credential.
So the verdict is `DEMONSTRATED` for the deployment shape this repository ships, and only
`DECLARED` for an operator deployment whose upstream demands a credential the agent does
not hold or whose egress is closed. An operator deployment reaches `DOES_NOT_CONFORM` only
by repeating the demonstration against its own upstream; until it does, the honest label
there is a declared bypass, and the verdict belongs at `INSUFFICIENT_EVIDENCE`, not here.

The verdict is negative and stays negative until one of three things happens, each of
which is a deployment observation rather than a code change:

1. the upstream refuses connections that do not present the proxy's credential;
2. egress from the deployment is closed except through the proxy;
3. `E` is narrowed so that `E1` is no longer the effect under assessment, which would be
   a new assessment rather than an amendment to this one.

**Falsification condition for this verdict.** An observation showing P4 cannot produce
`E1`: the upstream rejects a direct connection, or network policy prevents one. Note what
does *not* falsify it: an upstream effect that no mediated path explains. That is the
inventory's `detection_signal`, and it is what this verdict predicts. Reading a predicted
observation as a refutation is the mistake the inventory warns about in the same words
(`docs/design/EXECUTION-PATH-INVENTORY.md:73`, "Take EX-4, the row asserting that an unmediated path exists").

---

## 5. Verdict for `E2`: NOT ASSESSED

No service in this deployment exposes the forward path
(`docs/design/path-inventory.yaml:140`, "status: not-present"). With no path producing `E2` inside the declared
scope, `NON_BYPASSABILITY(B,E2)` is a claim this deployment can neither make nor refute.

This is deliberately outside the two-value scale. It is not `CONFORMS`, because nothing
was shown about a path that does not exist here, and it is not `INSUFFICIENT_EVIDENCE`
either, because there is no enumeration shortfall: the effect is produced elsewhere and
redeclared there.

---

## 6. A second boundary, and the verdict the first one could not produce

The negative verdict above is decided by a path that leaves `B` entirely. A different
question can be asked about the same deployment: holding the boundary at the proxy's own
decide-then-forward step, is there a known path that forwards without a decision?

Within that boundary there is not. The proxy asks the gate and forwards only after an
allow (`custos/mcp_proxy.py:205`, "Ask the gate, then forward only on an explicit allow."),
the breaker refuses without asking and records the refusal
(`custos/mcp_proxy.py:215`, "The gate is not answering"), and the reconciliation path
exists so that a refusal the gate never saw is still written down
(`custos/mcp_proxy.py:326`, "Ask the adapter to append a linked deny for a proxy-side refusal.").

No bypass is known inside that boundary, and completeness of its internal path set is not
established either: asynchronous cancellation, adapter behaviour and the upstream stub are
not enumerated here. That is `INSUFFICIENT_EVIDENCE`, and it is the honest middle case:
absence of a known bypass is not a completeness argument.

---

## 7. What this assessment does not establish

- **Not a conformance verdict.** Nothing here establishes `NON_BYPASSABILITY(B,E)` for the
  deployment as a whole, and section 4 establishes that it currently fails for `E1`.
- **Not an exhaustive path claim.** The enumeration is the repository's declaration, and
  the completeness status is open by design.
- **Not availability against an operator's upstream.** The bypass is demonstrated against
  the upstream this repository ships. A deployment with a credential-gated upstream or
  closed egress has a different answer, and it has to be observed rather than inherited.
- **Nothing about identity.** `B` decides on the principal a caller presents. Whether that
  principal is the one actually on the connection is a separate claim, and it is not
  established here.
- **Nothing outside the declared scope.** Customer deployments, the enterprise assembly,
  and processes that never connect to a mediated surface are out of scope, which is a
  statement about this document rather than about them.

---

## 8. What would change this document

The verdicts move only on deployment-level evidence, so they move when the deployment
changes: a network policy, an upstream credential requirement, or a narrowed effect. The
one thing that would change the *method* is an argument that `E1` as defined is not the
protected effect a reviewer would choose. That would be a new assessment, and the register
expects it to be argued rather than amended in place.
