"""Adapter from an MCP tool call to the CUSTOS action gate.

This is the only module that knows both sides. The proxy core stays ignorant of
``custos`` on purpose (see ``custos/mcp_proxy.py``): the adapter translates, the
gate decides, the proxy forwards or refuses.

Two honest notes about the contract, both verified against ``custos/action_gate.py``
rather than assumed:

* ``evaluate_action`` is synchronous, so it runs in a bounded executor of its own
  (``GATE_EXECUTOR_WORKERS`` threads, prefix ``custos-gate``) rather than in the
  loop's shared default pool. A timeout bounds how long the *agent* waits and
  denies the call, but cannot interrupt a gate call already running; keeping that
  orphaned work away from the default pool stops a stalled gate from starving
  every other ``asyncio.to_thread`` user in the process.
* ``record_denial`` appends the reconciliation record for a call the proxy denied
  without a gate verdict (timeout, open breaker). It goes through
  ``ActionGate.record_reconciliation`` — a public method added for this — so no
  private member is touched and the chain's lock and save-before-append ordering
  stay in one place. Nothing here forks the chain.
* ``trace_id`` is passed straight through to the gate, which threads it into the
  decision record's preimage. That parameter was added for this integration; a
  record emitted through the proxy therefore correlates with the agent's request
  rather than only with the gate's own tenant and tool labels.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from custos.action_gate import ActionGate, ActionRequest
from custos.mcp_proxy import GateVerdict
from custos.policy_engine import PolicyAction

# The gate runs in its own pool: a stalled gate must be able to exhaust this pool
# and nothing else. Small on purpose, and paired with the proxy's breaker.
GATE_EXECUTOR_WORKERS = 4
TIMEOUT_RULE = "mcp_proxy_gate_timeout"


class CustosGateAdapter:
    """Implements the proxy's ``GateAdapter`` protocol over a real ``ActionGate``."""

    def __init__(
        self,
        gate: ActionGate,
        *,
        client_id: str = "mcp-proxy",
        executor: Optional[ThreadPoolExecutor] = None,
        max_workers: int = GATE_EXECUTOR_WORKERS,
    ) -> None:
        if gate is None:
            raise ValueError("an ActionGate is required; the adapter does not decide")
        if max_workers < 1:
            raise ValueError("max_workers must be at least 1")
        self._gate = gate
        self._client_id = client_id
        self._executor = executor or ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="custos-gate"
        )
        self._owns_executor = executor is None

    async def evaluate(
        self,
        *,
        tenant_id: str,
        tool: str,
        arguments: dict,
        trace_id: str,
    ) -> GateVerdict:
        request = ActionRequest(tool=tool, command="", args=dict(arguments or {}))
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            self._executor,
            lambda: self._gate.evaluate_action(
                tenant_id, request, self._client_id, trace_id
            ),
        )
        decision = result.decision
        return GateVerdict(
            allowed=decision.action == PolicyAction.ALLOW,
            record_hash=result.audit_record_hash,
            rule=decision.triggered_rule,
            reason=decision.reason or "",
        )


    # -- reconciliation ----------------------------------------------------
    def record_denial(
        self, *, tenant_id: str, tool: str, trace_id: str, rule: str, reason: str
    ) -> bool:
        """Append a linked DENY for a call the proxy refused without a verdict.

        The record carries the same ``trace_id`` as the call and the proxy's own rule
        marker, so a reader joining on that id sees this deny next to any late grant
        from the gate. Two records for one such call is the deliberate cost of not
        leaving authorisation in the chain for an action that did not happen, and the
        marker is what makes the deny authoritative regardless of arrival order.

        Returns ``False`` when nothing could be written (unknown tenant, audit store
        unreachable, bound evidence required but unavailable). That limit is declared
        rather than engineered around: if the store is down, nobody can record.
        """
        try:
            return bool(
                self._gate.record_reconciliation(
                    tenant_id,
                    client_id=self._client_id,
                    trace_id=trace_id,
                    rule=rule,
                    reason=reason,
                    content=f"{rule} tool={tool}",
                )
            )
        except Exception:  # noqa: BLE001 - never let reconciliation break a denial
            return False

    def close(self) -> None:
        """Shut down the gate executor if this adapter created it."""
        if self._owns_executor:
            self._executor.shutdown(wait=False)


def build_proxy(gate: ActionGate, *, tenant_id: str, timeout_seconds: Optional[float] = None):
    """Convenience constructor: real gate in, mediated proxy out."""
    from custos.mcp_proxy import DEFAULT_TIMEOUT_SECONDS, McpProxy

    return McpProxy(
        CustosGateAdapter(gate),
        tenant_id=tenant_id,
        timeout_seconds=DEFAULT_TIMEOUT_SECONDS if timeout_seconds is None else timeout_seconds,
    )
