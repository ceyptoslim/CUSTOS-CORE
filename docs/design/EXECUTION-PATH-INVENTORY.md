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
| Deployment binding | Startup binding record (see below) | That the running deployment matches the declaration | That unconnected processes exist |

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
- `out-of-scope-by-construction` — inapplicable, with an architectural argument and a
  falsification condition for the declaration itself.

Every row carries a `falsification` field: the observation that would show the row
wrong. A row without one is a claim, not evidence.

## The binding record

The inventory can stay accurate while the deployment drifts. Binding ties the two
together with a record written at startup, in the same chain as every decision:

```
client_id = "custos-binding"
triggered_rule = "deployment_binding_startup"
content = canonical JSON payload (its hash is what the chain stores)
```

Payload fields (`custos/deployment_binding.py`): `deployment_id`, `build_commit`,
`transport`, `upstream_command` or `upstream_endpoint`, `tool_list_digest`,
`credential_fingerprint`, `config`, `entry_ids`, `binding_schema`.

Three properties make it evidence rather than a log line:

1. **No secrets.** A credential appears as `sha256:` of its value. The process holds
   the JWT secret and the database URL; the binding is not a second place to leak them.
2. **Canonical form.** Keys are sorted and empty values dropped, so digest equality
   means deployment equality. Evidence that changes with key order is noise.
3. **The digest is anchored, the payload is published.** The chain stores hashes by
   design, so the payload is written beside the deployment and its digest is what the
   record holds. A reviewer reads the payload, re-hashes it, and compares.

## How a reviewer uses it

1. Read the inventory. For each `mediated` row, open the named evidence and confirm it
   actually exercises the path rather than the function next to it.
2. Obtain the binding payload from the deployment and verify its digest against the
   chain entry with rule `deployment_binding_startup`.
3. Diff `entry_ids` both ways. Inventory row with no binding claim: declared but not
   deployed. Binding claim with no inventory row: deployed and undeclared.
4. Check `tool_list_digest` against what the upstream actually advertises. A tool the
   upstream serves but the deployment never listed is a drift finding.
5. Note what remains: any process that never connects leaves no record.

## What this does not establish

Stated here rather than discovered later:

- **Completeness.** A green diff is consistent with a complete declaration and with an
  incomplete one. Only an unlisted path that someone finds falsifies it.
- **Unconnected processes.** Binding observes components that connect to the mediated
  surface. An agent pointed straight at the upstream produces no binding record and no
  decision record. That is EX-4, unchanged by this file.
- **Effect correctness.** These rows say a path reaches the decision point; they say
  nothing about whether the tool did what it claimed.

The honest summary a reviewer can hold us to: every declared path is probed, and any
path that changes the deployment without changing the declaration is either caught by
binding or outside what binding can see. Nobody has established the second half, and
this document does not pretend otherwise.
