"""MCP proxy: every ``tools/call`` is decided by the gate before it is forwarded.

Design rules, each of which exists because something went wrong before it:

1. **The proxy decides nothing.** Verdicts come from the injected adapter, which
   is the only thing that knows about the gate. This module imports nothing from
   ``custos``, holds no allowlist, and authorizes only on a literal ``True``
   (the same rule the OPA engine applies to its response). A second copy of a
   decision is how three separate preimage duplicates drifted in this repo.
2. **One record per call, written by the gate, before any effect.** The proxy
   records nothing and does not record outcomes; post-execution binding is
   exit class EX-2 and stays declared open.
3. **The proxy mints the correlation id** and passes it on every call, so a
   record produced under a proxy has a trace a third party can follow.
4. **Bounded, fail-closed waiting.** A timeout, an exception, or a malformed
   verdict all deny without forwarding.

Caveat that belongs at the top rather than in a footnote: a proxy mediates only
when it is the agent's sole path to the upstream server. Point an agent at the
server directly and nothing here applies. That is exit class EX-4, closed for an
API surface and open at deployment.
"""

from __future__ import annotations

import asyncio
import math
import uuid
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional, Protocol, runtime_checkable

DEFAULT_TIMEOUT_SECONDS = 2.0

# Denial reasons the proxy itself can produce. Gate denials carry the gate's own
# rule name instead; these four mean "the gate did not answer usably".
REASON_TIMEOUT = "mcp_proxy_gate_timeout"
REASON_ERROR = "mcp_proxy_gate_error"
REASON_MALFORMED = "mcp_proxy_malformed_verdict"


@dataclass(frozen=True)
class GateVerdict:
    """What an adapter must return. Nothing else counts as an answer."""

    allowed: bool
    record_hash: Optional[str] = None
    rule: Optional[str] = None
    reason: str = ""


@dataclass(frozen=True)
class ProxyOutcome:
    """Result of one mediated call, including why it was refused."""

    forwarded: bool
    trace_id: str
    record_hash: Optional[str] = None
    rule: Optional[str] = None
    reason: str = ""


@runtime_checkable
class GateAdapter(Protocol):
    """The only thing the proxy knows about the gate.

    Implementations translate a tool call into the gate's own request type and
    return a :class:`GateVerdict`. They are expected to be async so a slow gate
    cannot block the event loop.
    """

    async def evaluate(
        self,
        *,
        tenant_id: str,
        tool: str,
        arguments: dict,
        trace_id: str,
    ) -> GateVerdict:  # pragma: no cover - protocol declaration
        ...


def _validated_timeout(value: Any) -> float:
    """Refuse to start with a timeout that cannot bound anything.

    ``0``, a negative, ``inf`` and ``nan`` all pass a naive ``> 0`` check in some
    language runtimes and then never fire. A proxy whose bound cannot fire is a
    proxy that hangs the agent instead of refusing it.
    """
    if value is None:
        raise ValueError("timeout_seconds is required; a proxy with no bound cannot fail closed")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"timeout_seconds must be a number, got {type(value).__name__}")
    seconds = float(value)
    if math.isnan(seconds) or math.isinf(seconds) or seconds <= 0:
        raise ValueError(f"timeout_seconds must be finite and > 0, got {value!r}")
    return seconds


class McpProxy:
    """Mediates ``tools/call`` for one tenant through an injected gate adapter."""

    def __init__(
        self,
        gate: GateAdapter,
        *,
        tenant_id: str,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        trace_id_factory: Optional[Callable[[], str]] = None,
    ) -> None:
        if not tenant_id:
            raise ValueError("tenant_id is required: an unlabelled call has no policy to apply")
        if not callable(getattr(gate, "evaluate", None)):
            raise ValueError("gate adapter must expose an async evaluate() method")
        self._gate = gate
        self._tenant_id = tenant_id
        self._timeout = _validated_timeout(timeout_seconds)
        self._trace_id_factory = trace_id_factory or (lambda: uuid.uuid4().hex)

    # -- correlation -------------------------------------------------------
    def mint_trace_id(self) -> str:
        trace_id = self._trace_id_factory()
        if not isinstance(trace_id, str) or not trace_id:
            raise ValueError("trace_id_factory must return a non-empty string")
        return trace_id

    # -- mediation ---------------------------------------------------------
    async def call_tool(
        self,
        tool: str,
        arguments: Optional[dict] = None,
        forward: Optional[Callable[[str, dict], Awaitable[Any]]] = None,
    ) -> ProxyOutcome:
        """Ask the gate, then forward only on an explicit allow.

        ``forward`` is called at most once, and only after an allow. A forward
        that raises leaves the decision record standing: the effect failed, the
        authorization did not.
        """
        args = dict(arguments or {})
        trace_id = self.mint_trace_id()

        try:
            verdict = await asyncio.wait_for(
                self._gate.evaluate(
                    tenant_id=self._tenant_id,
                    tool=tool,
                    arguments=args,
                    trace_id=trace_id,
                ),
                timeout=self._timeout,
            )
        except asyncio.TimeoutError:
            return ProxyOutcome(
                forwarded=False,
                trace_id=trace_id,
                reason=REASON_TIMEOUT,
                rule=REASON_TIMEOUT,
            )
        except Exception as exc:  # noqa: BLE001 - any gate failure must deny
            return ProxyOutcome(
                forwarded=False,
                trace_id=trace_id,
                reason=f"{REASON_ERROR}: {type(exc).__name__}",
                rule=REASON_ERROR,
            )

        refusal = self._refusal(verdict, trace_id)
        if refusal is not None:
            return refusal

        if forward is not None:
            await forward(tool, args)

        return ProxyOutcome(
            forwarded=True,
            trace_id=trace_id,
            record_hash=getattr(verdict, "record_hash", None),
        )

    def _refusal(self, verdict: Any, trace_id: str) -> Optional[ProxyOutcome]:
        """Return a refusal when the verdict does not explicitly allow.

        Structural checks rather than ``isinstance`` so an adapter may return its
        own verdict type, but nothing loosely truthy is accepted: ``allowed`` must
        be the literal ``True``.
        """
        if verdict is None:
            return ProxyOutcome(
                forwarded=False, trace_id=trace_id, reason=REASON_MALFORMED, rule=REASON_MALFORMED
            )
        allowed = getattr(verdict, "allowed", None)
        if allowed is not True:
            if allowed is False:
                return ProxyOutcome(
                    forwarded=False,
                    trace_id=trace_id,
                    record_hash=getattr(verdict, "record_hash", None),
                    rule=getattr(verdict, "rule", None),
                    reason=getattr(verdict, "reason", "") or "denied",
                )
            return ProxyOutcome(
                forwarded=False,
                trace_id=trace_id,
                reason=f"{REASON_MALFORMED}: allowed={allowed!r}",
                rule=REASON_MALFORMED,
            )
        return None
