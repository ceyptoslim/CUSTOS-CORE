"""Adapter from an MCP tool call to the CUSTOS action gate.

This is the only module that knows both sides. The proxy core stays ignorant of
``custos`` on purpose (see ``custos/mcp_proxy.py``): the adapter translates, the
gate decides, the proxy forwards or refuses.

Two honest notes about the contract, both verified against ``custos/action_gate.py``
rather than assumed:

* ``evaluate_action`` is synchronous, so it runs in a worker thread. A timeout
  therefore bounds how long the *agent* waits and denies the call, but cannot
  interrupt a gate call already running in that thread. The denial is what
  matters; the abandoned thread finishes into a record nobody acts on.
* ``trace_id`` is passed straight through to the gate, which threads it into the
  decision record's preimage. That parameter was added for this integration; a
  record emitted through the proxy therefore correlates with the agent's request
  rather than only with the gate's own tenant and tool labels.
"""

from __future__ import annotations

import asyncio
from typing import Optional

from custos.action_gate import ActionGate, ActionRequest
from custos.mcp_proxy import GateVerdict
from custos.policy_engine import PolicyAction


class CustosGateAdapter:
    """Implements the proxy's ``GateAdapter`` protocol over a real ``ActionGate``."""

    def __init__(self, gate: ActionGate, *, client_id: str = "mcp-proxy") -> None:
        if gate is None:
            raise ValueError("an ActionGate is required; the adapter does not decide")
        self._gate = gate
        self._client_id = client_id

    async def evaluate(
        self,
        *,
        tenant_id: str,
        tool: str,
        arguments: dict,
        trace_id: str,
    ) -> GateVerdict:
        request = ActionRequest(tool=tool, command="", args=dict(arguments or {}))
        result = await asyncio.to_thread(
            self._gate.evaluate_action,
            tenant_id,
            request,
            self._client_id,
            trace_id,
        )
        decision = result.decision
        return GateVerdict(
            allowed=decision.action == PolicyAction.ALLOW,
            record_hash=result.audit_record_hash,
            rule=decision.triggered_rule,
            reason=decision.reason or "",
        )


def build_proxy(gate: ActionGate, *, tenant_id: str, timeout_seconds: Optional[float] = None):
    """Convenience constructor: real gate in, mediated proxy out."""
    from custos.mcp_proxy import DEFAULT_TIMEOUT_SECONDS, McpProxy

    return McpProxy(
        CustosGateAdapter(gate),
        tenant_id=tenant_id,
        timeout_seconds=DEFAULT_TIMEOUT_SECONDS if timeout_seconds is None else timeout_seconds,
    )
