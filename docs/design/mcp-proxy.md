# MCP proxy — mediation at the point where tool calls are made

**Status:** first integration. Public, in `custos/mcp_proxy.py` (core) and
`custos/mcp_gate_adapter.py` (the gate side).

## What it is

An MCP server that sits between an agent and the MCP servers it wants to use.
It lists upstream tools, and every `tools/call` is decided by CUSTOS before it is
forwarded. A denial returns an error result to the agent carrying the rule and the
audit record hash; a denial means the upstream server is never contacted.

## What it does not do, stated first because it matters most

**A proxy mediates only when it is the agent's only path.** Point the agent at the
upstream server directly and none of this applies. This is exit class `EX-4`
coverage in `EABC-EXIT-CLASS-REGISTER.md`: closed for the in-process API surface,
open at deployment. Configuring the agent with the proxy alone and adding egress
rules is the deployment work that closes it, and it happens outside this repo.

**It does not record outcomes.** One record per call: the gate's decision record,
written before any effect. Whether the forwarded call then succeeded is not
recorded, so `EX-2` substitution stays `declared-open`. A proxy that recorded
outcomes would be claiming half of a property it cannot prove, and this integration
is not that claim.

## Design rules

1. **The proxy decides nothing.** Verdicts come from an injected adapter. The core
   imports nothing from `custos`, holds no allowlist, and authorizes only on a
   literal `True` — the same rule the OPA engine applies to its own response. A
   test fails if the core imports `custos` or grows an allowlist.
2. **One record per decided call**, written by the gate, at decision time.
   Verified end to end: `tests/test_mcp_gate_integration.py` reads the chain and
   asserts the hash returned to the proxy is the hash the gate wrote. "Decided" is
   load-bearing: the timeout path does not produce a citable record (item 4).
3. **The proxy mints the correlation id** and passes `trace_id` into
   `evaluate_action`, which threads it into the record's preimage. That parameter
   was added by this integration; before it, correlation was only reachable by
   calling `AuditChain.record` directly.
4. **A refusal the proxy makes alone is recorded, and the marker decides.**
   Two refusals happen without a gate verdict: a timeout, and a call denied by the
   open breaker. Both append a linked DENY carrying the call's `trace_id` and the
   proxy's rule (`mcp_proxy_gate_timeout`, `mcp_proxy_gate_circuit_open`), so a
   reader joining on that id sees the refusal next to any late grant the gate wrote.

   **Order is not evidence; the marker is.** The abandoned gate call may write its
   ALLOW *after* the reconciling DENY, so "last record per trace wins" would conclude
   the call was allowed. The rule is therefore: **any trace carrying
   `mcp_proxy_gate_timeout` or `mcp_proxy_gate_circuit_open` means the call was not
   forwarded, regardless of record order.** Both orders are tested.
   `ProxyOutcome.reconciled` reports whether the corrective record landed.

   **Declared limits.** If the audit store is unreachable, nothing can be recorded
   by anyone, and the refusal is unrecorded rather than mis-recorded — the caller
   sees `reconciled=False`. In that state "one record per decided call" does not
   hold for proxy-side refusals: a breaker denial is then unrecorded entirely, and
   saying otherwise would be the suppression class (EX-1) wearing a different label.

5. **Bounded, fail-closed waiting.** Default 2s. A timeout, an exception, or a
   verdict that is not an explicit allow all deny without forwarding. A zero,
   negative, infinite, NaN or missing timeout refuses to start, because a bound
   that cannot fire turns a refusal into a hang.

## The adapter contract

```python
class GateAdapter(Protocol):
    async def evaluate(self, *, tenant_id: str, tool: str,
                       arguments: dict, trace_id: str) -> GateVerdict: ...

# optional, one method for both proxy-side refusals:
#   record_denial(*, tenant_id, tool, trace_id, rule, reason) -> bool
```

Reconciliation is written through public API only: the adapter calls
`ActionGate.record_reconciliation(...)`, which resolves the tenant context and the
in-force citation and appends via `AuditChain.append_reconciliation(...)`. The
chain's lock and its save-before-append ordering therefore stay in one place, and a
second writer cannot fork the chain by appending around them. A static test fails if
the adapter reaches for `_tm` or `_cited_policy_digest` again.

`CustosGateAdapter` implements it against the real gate:

```python
request = ActionRequest(tool=tool, command="", args=arguments)
result  = await asyncio.to_thread(gate.evaluate_action,
                                  tenant_id, request, "mcp-proxy", trace_id)
GateVerdict(allowed=result.decision.action == PolicyAction.ALLOW,
            record_hash=result.audit_record_hash,
            rule=result.decision.triggered_rule,
            reason=result.decision.reason)
```

These names are verified against `custos/action_gate.py`, not assumed. Two
consequences worth knowing:

* `evaluate_action` is synchronous and runs in a **bounded executor of its own**
  (`GATE_EXECUTOR_WORKERS`, threads named `custos-gate`), not in the loop's shared
  default pool. A timeout bounds how long the agent waits and denies the call; it
  cannot interrupt a gate call already running, so the orphaned work finishes where
  it is — but it can now only exhaust the gate's pool, not every other
  `asyncio.to_thread` user in the process.
* **The breaker.** After `consecutive_timeout_limit` timeouts in a row (default 3)
  the proxy denies fast with `mcp_proxy_gate_circuit_open` without calling the gate
  at all, so a saturated gate cannot turn into an all-denied proxy that pays the
  timeout on every request. After a cooldown (default 5s) it half-opens: one probe
  call decides whether the gate is back, and a single timeout re-opens it.
* **The upstream environment is an allowlist.** `upstream_env()` passes `PATH`,
  `HOME`, `LANG`, `LC_ALL`, `TMPDIR` and any names named in `CUSTOS_MCP_UPSTREAM_ENV`
  — never `os.environ`. This process holds the JWT secret and the database URL, and
  the upstream is the component being governed. `PYTHONPATH` is deliberately absent:
  it decides what code a Python upstream imports. It can be opted into explicitly.
  Names beginning `CUSTOS_` are refused outright, in the setting and in programmatic
  extras alike, so a typo cannot hand this process's keys to the governed process.
* `client_id` is fixed to `mcp-proxy`, so records distinguish mediated calls from
  direct API calls without a second field.

## Tests

66 75 tests: `tests/test_mcp_proxy.py` (40, fake adapter — mediation rules, literal-True
authorization, timeout arithmetic, malformed verdicts, structural checks that the
core cannot become a second gate), `tests/test_mcp_gate_integration.py` (10, real
gate — allow, deny without upstream contact, dangerous command inside an allowed
tool, trace id landing in the record, two calls two records),
`tests/test_mcp_proxy_timeout_evidence.py` (3, what a timeout leaves behind) and
`tests/test_mcp_gate_isolation.py` (22, own executor, breaker, one-probe half-open,
reconciliation in both orders against a real chain, upstream env allowlist).

## Pre-registered sabotage

Class `007-weaken-fail-closed-proxy` in `docs/red-proof-records/sabotage-mcp-proxy/`.
The two failing assertions are named before the first run, and the design discloses
that the same session wrote the proxy, its tests and its sabotage, which is a
weaker blindness position than classes 001–003.

## What is not wired yet

Transport binding (stdio and HTTP shells around this core) is deliberately absent:
the core is transport-agnostic and the MCP SDK's API has changed between major
versions, so the binding belongs in a commit that pins `mcp>=1,<2` and smoke-tests
against it. Wiring a binding whose API was guessed is how a demo passes locally and
fails on someone else's machine.
