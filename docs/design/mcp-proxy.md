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
2. **One record per call**, written by the gate, at decision time. Verified end to
   end: `tests/test_mcp_gate_integration.py` reads the chain and asserts the hash
   returned to the proxy is the hash the gate wrote.
3. **The proxy mints the correlation id** and passes `trace_id` into
   `evaluate_action`, which threads it into the record's preimage. That parameter
   was added by this integration; before it, correlation was only reachable by
   calling `AuditChain.record` directly.
4. **Bounded, fail-closed waiting.** Default 2s. A timeout, an exception, or a
   verdict that is not an explicit allow all deny without forwarding. A zero,
   negative, infinite, NaN or missing timeout refuses to start, because a bound
   that cannot fire turns a refusal into a hang.

## The adapter contract

```python
class GateAdapter(Protocol):
    async def evaluate(self, *, tenant_id: str, tool: str,
                       arguments: dict, trace_id: str) -> GateVerdict: ...
```

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

* `evaluate_action` is synchronous and runs in a worker thread. The timeout bounds
  how long the agent waits and denies the call; it cannot interrupt a gate call
  already running. The denial is what matters, and the orphaned call's record is
  written but never acted on.
* `client_id` is fixed to `mcp-proxy`, so records distinguish mediated calls from
  direct API calls without a second field.

## Tests

46 tests: `tests/test_mcp_proxy.py` (36, fake adapter — mediation rules, literal-True
authorization, timeout arithmetic, malformed verdicts, structural checks that the
core cannot become a second gate) and `tests/test_mcp_gate_integration.py` (10, real
gate — allow, deny without upstream contact, dangerous command inside an allowed
tool, trace id landing in the record, two calls two records).

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
