# Execution path inventory: making the declaration reviewable

This answers a question the exit-class register raises but does not settle: when an
implementation says a decision point mediates every path to a protected effect, how does
a reviewer who does not trust the author check that? Short answer: they cannot check
completeness directly. What they can check is a declaration, path by path, and the
evidence attached to each row.

Three claims are separated here, because merging them is how the category produced
dashboards that assert more than they carry.

| Claim | Artifact | What it establishes | What it does not |
|---|---|---|---|
| Declared path coverage | `docs/design/path-inventory.yaml` | What this deployment says can reach the protected effect | That the list is complete |
| Path mediation | Per-row `evidence` (tests, frozen records) | That the named path traverses the enforcement point | That unlisted paths do not exist |
| Deployment binding | Startup binding record (see below) | That a process which wrote a record matched the declaration | That unconnected processes exist, or that any process wrote one |

## What is protected, and against what

Every other section depends on this one. An exclusion cannot be reviewed until the
reviewer knows what is being protected, and "out of scope" without a scope is a word
rather than a claim.

The protected effect is **an external state change produced by an agent action that this
deployment forwards**: invoking a tool on an upstream MCP server, and issuing an outbound
HTTP request to a decided target. Both act on systems the deployment does not own.

In scope:

- tool invocations forwarded to an upstream MCP server over stdio;
- outbound HTTP requests to a decided target, which is the enterprise execution path.

Out of scope, each with the reason rather than the label:

- **Custody anchoring** (git push of the chain head, RFC 3161 timestamp). The effect is
  durability of evidence, not an agent action on a third-party system. This is what makes
  P5 a definitional exclusion instead of a convenience, and the row carries a
  falsification condition for the definition itself.
- **Inbound decision requests, health and metrics.** No state change outside the process.
- **Local filesystem writes by the process.** Nothing outside the deployment observes
  them; they are evidence, not effect.

The declaration covers processes started from this repository's entry points in the named
deployment. It excludes processes that never connect to a mediated surface, infrastructure
outside the deployment's control, and the enterprise execution assembly, which redeclares
in its own inventory. Completeness here is an attestation, not a derivation.

## The file

`path-inventory.yaml` holds one row per path, using the register's closed status
vocabulary:

- `mediated` — the path reaches the enforcement point; evidence must exist.
- `not-effect-producing` — the path returns a decision and cannot act. A decision API
  the caller may ignore is not an enforcement path, and calling it one is the oldest
  overclaim in this space.
- `not-present` — the code exists but no service in this deployment exposes it.
- `unmediated-declared` — the path produces the effect and is not mediated. This is
  EX-4 stated as a row rather than a footnote.
- `out-of-scope-by-construction` — excluded by the definition of the protected effect,
  with an argument and a falsification condition for the definition.

Every row carries three fields, and the separation between the last two is deliberate:
`assertion` (the claim the row makes), `falsification_condition` (the observation that
would show it false), and `detection_signal` (the observation that is merely consistent
with it being false).

## Falsification is not detection

The distinction is easy to lose and expensive to lose, because it determines whether a
finding can be used against the document.

Take EX-4, the row asserting that an unmediated path exists. The tempting text is "an
effect on the upstream that no mediated path explains". That sentence describes a
**detection signal**. It tells an operator a deployment deserves investigation, and it is
consistent with exactly the world the row asserts. It refutes nothing, because the row
predicts it.

Falsifying the row requires the opposite kind of observation: every path capable of
producing the protected effect is enumerated and each is shown to traverse a decision
point, for instance because the upstream rejects connections that do not present the
proxy's credential or because egress is closed except through the proxy. Showing that the
claimed bypass does not exist, because the upstream is unreachable without the proxy,
does the same work.

So the two fields are ordered that way in the file: a claim, what would refute it, and
what would only be a clue. A row whose falsification condition is its detection signal is
a claim that nothing could refute, which is the shape this whole exercise exists to avoid.

## Implemented mechanism versus established binding

### The wiring that closes the gap, and why it stays off

`record_binding` is now called from the startup lifespan, gated on
`CUSTOS_DEPLOYMENT_BINDING`. Two decisions are worth stating because both are
choices, not defaults:

**Off by default.** Enabling it changes what a deployment writes and how it fails,
so it is opt-in and the reference deployment does not opt in. The inventory keeps
`established_at_runtime: false` for the same reason it kept it before: wiring is a
capability of the code, a record is a fact about a process.

**Fail-closed when enabled.** If a deployment sets the flag and the record cannot
be written, startup is refused. The alternative, logging a warning and starting
anyway, produces the exact confusion this artifact exists to prevent: a running
process described by an inventory that says the mechanism is in place, bound by
nothing. A refused start is loud, and it is the only failure that cannot be
mistaken for success.

`/v1/info` reports `deployment_binding.established` for the running process, so a
reviewer checks the process rather than the tree. Credentials still appear only as
fingerprints, and the payload is returned to the caller to be written beside the
deployment, since the chain stores digests rather than payloads.


The binding module is in this tree and the startup lifespan now calls it, gated on
`CUSTOS_DEPLOYMENT_BINDING` and off by default. The earlier version of this paragraph said
nothing called it, which was true when it was written and stopped being true when the
wiring landed; a document that describes the tree from memory is the defect this artifact
exists to prevent. What does not follow from the wiring: the reference deployment does not
enable the flag, so `established_at_runtime` stays `false`, because a wired mechanism is a
capability of the code and a record is a fact about a process.

| What exists | What it establishes | How a reviewer tells |
|---|---|---|
| `custos/deployment_binding.py` | That a recorder is implemented | Nothing about any running process |
| A record with rule `deployment_binding_startup` in a process's chain | That this process ran the recorder | Which configuration produced that record, once the payload is read |
| A published payload whose digest matches that record | That the record describes the deployment being reviewed | Not that the payload is complete, and not that the process is the only one running |

A binding exists for a process only when that process's chain contains the record and the
deployment publishes the payload it hashes. The module's presence establishes no record
for anything. The inventory's `binding` block states this in the same words, so the
declaration and the code cannot drift apart quietly.

## The binding record

The inventory can stay accurate while the deployment drifts. Binding ties the two
together with a record written at startup, in the same chain as every decision:

```
client_id = "custos-binding"
triggered_rule = "deployment_binding_startup"
content = canonical JSON payload (its hash is what the chain stores)
```

Payload fields, schema 2 (`custos/deployment_binding.py`): `deployment_id`,
`build_commit`, `transport`, `upstream_command` or `upstream_endpoint`,
`tool_list_digest`, `tool_descriptor_digest`, `tool_count`, `credential_fingerprint`,
`credential_binding`, `config_digest`, `secret_config_fields`, `config_keys`,
`entry_ids`, `binding_schema`.

Four properties make it evidence rather than a log line:

1. **No secrets, including in places people forget.** A credential appears as `sha256:`
   of its value. That rule covers the obvious cases and three less obvious ones: secret
   flags in an upstream argv (`--token …`, `--api-key=…`), URL userinfo, and
   secret-looking query parameters are all fingerprinted before the payload is built.
   The redaction is a backstop, not a licence: a deployment that needs to pass credentials
   to an upstream process should use an environment variable or a mounted file.
2. **Canonical form.** Keys are sorted and empty values dropped, so digest equality
   means deployment equality. Evidence that changes with key order is noise.
3. **The digest is anchored, the payload is published.** The chain stores hashes by
   design, so the payload is written beside the deployment and its digest is what the
   record holds. A reviewer reads the payload, re-hashes it, and compares.
4. **The payload describes capability, not just identity.** `tool_descriptor_digest`
   covers each tool's name, description, input schema and annotations, because those
   decide what the upstream can be asked to do. Names alone do not move when a tool
   widens from one record to a bulk update, which is precisely the change that matters.

## Credentials and configuration in the payload

Two details decide whether the binding describes the running system or the paperwork
next to it.

**The credential is the one the caller reports presenting, not one this process observed.**
A fingerprint taken from a configuration file shows what was written down, not what was
used: environment overrides, mounted secrets and runtime refresh all change the value after
the file is read. `credential_binding` narrows that gap by recording the fingerprint of the
value the calling process declares it presents at runtime, tagged
`source: "runtime-connection"`, bound to the upstream it reached, with `configured_matches`
saying whether a static value agreed. That field is explicitly `null` when there was
nothing to compare, because "no configured value" and "no comparison" are different states.

The limit belongs in the same paragraph as the capability, because the two are one claim.
Nothing here reads the credential off the socket. The recorder cannot distinguish a caller
that presents token A from a caller that presents token B and says A, so what a reviewer
can check is consistency between the declared value, the configuration and the upstream
that was reached, not the bytes on the wire. Closing that would mean terminating the
connection at the recorder, which changes what the deployment is rather than what this
field records.

**A rotated secret has to be detectable without being readable.** `config_digest`
replaces secret-looking values with their fingerprints before hashing and lists the field
paths in `secret_config_fields`. The digest moves when a credential rotates, and the
record still contains no credential. `config_keys` preserves the shape for review without
publishing values.

## How a reviewer uses it

1. Read the protected-effect section first. If you disagree with what is in scope, stop:
   nothing downstream is reviewable.
2. Read the inventory. For each `mediated` row, open the named evidence and confirm it
   actually exercises the path rather than the function next to it.
3. For each row, check that the falsification condition could really refute the
   assertion, and that the detection signal is not doing the work the falsification
   condition is supposed to do.
4. Establish whether a binding exists at all before treating one as evidence: look for the
   `deployment_binding_startup` record, then for the payload whose digest matches it.
5. Diff `entry_ids` both ways. Inventory row with no binding claim: declared but not
   deployed. Binding claim with no inventory row: deployed and undeclared.
6. Check `tool_descriptor_digest` against what the upstream actually advertises. A tool
   the upstream serves with a wider schema than the deployment recorded is a drift
   finding, and a name-only digest would have missed it.
7. Note what remains: any process that never connects leaves no record.

## What this does not establish

Stated here rather than discovered later:

- **Completeness.** A green diff is consistent with a complete declaration and with an
  incomplete one. Only an unlisted path that someone finds falsifies it.
- **That any binding exists.** The mechanism is implemented and unwired. Absence of a
  record is not evidence of drift, and presence of the module is not evidence of binding.
- **Unconnected processes.** Binding observes components that connect to the mediated
  surface. An agent pointed straight at the upstream produces no binding record and no
  decision record. That is EX-4, unchanged by this file.
- **Effect correctness.** These rows say a path reaches the decision point; they say
  nothing about whether the tool did what it claimed.

The honest summary a reviewer can hold us to: every declared path is probed, every claim
names the observation that would refute it, and any path that changes the deployment
without changing the declaration is either caught by binding or outside what binding can
see. Nobody has established the second half, and this document does not pretend
otherwise.

## The assessment this inventory feeds

The inventory is the declaration. The verdict it supports lives in
[`NON-BYPASSABILITY-ASSESSMENT.md`](NON-BYPASSABILITY-ASSESSMENT.md), which asks
`NON_BYPASSABILITY(B,E)` one effect at a time against this file, records `DOES_NOT_CONFORM`
for the tool-invocation effect because P4 is declared, and carries
`INSUFFICIENT_EVIDENCE` for the proxy's internal boundary where no bypass is known but
completeness is not established. Read the two together: the inventory says what paths
exist, the assessment says what that amounts to, and neither is allowed to answer the
other's question silently.

