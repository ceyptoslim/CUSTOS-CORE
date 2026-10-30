"""MCP proxy: every ``tools/call`` is decided by the gate before it is forwarded.

Design rules, each of which exists because something went wrong before it:

1. **The proxy decides nothing.** Verdicts come from the injected adapter, which
   is the only thing that knows about the gate. This module imports nothing from
   ``custos``, holds no allowlist, and authorizes only on a literal ``True``
   (the same rule the OPA engine applies to its response). A second copy of a
   decision is how three separate preimage duplicates drifted in this repo.
2. **One record per decided call, written by the gate, before any effect.** The
   proxy does not record outcomes; post-execution binding is exit class EX-2 and
   stays declared open. The single exception is reconciled in rule 5, on purpose.

3. **The proxy mints the correlation id** and passes it on every call, so a
   record produced under a proxy has a trace a third party can follow.
4. **Bounded, fail-closed waiting.** A timeout, an exception, or a malformed
   verdict all deny without forwarding. The gate gets its own bounded executor, and
   after N consecutive timeouts the proxy denies fast without calling the gate at
   all: a saturated gate must not become a saturated proxy.
5. **A timed-out call is reconciled, not merely uncited.** A late-landing ALLOW for
   a call the proxy denied would put authorisation in the chain for an action that
   never happened. So on timeout the proxy asks the adapter to append a linked
   DENY record for that ``trace_id``. That makes two records for the timeout case,
   which is the intended cost. If the audit store is itself unreachable, nothing
   can be recorded: that limit is declared, not engineered around.

Caveat that belongs at the top rather than in a footnote: a proxy mediates only
when it is the agent's sole path to the upstream server. Point an agent at the
server directly and nothing here applies. That is exit class EX-4, closed for an
API surface and open at deployment.
"""

from __future__ import annotations

import asyncio
import inspect
import math
import os
import time
import uuid
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional, Protocol, runtime_checkable

DEFAULT_TIMEOUT_SECONDS = 2.0

# Denial reasons the proxy itself can produce. Gate denials carry the gate's own
# rule name instead; these four mean "the gate did not answer usably".
REASON_TIMEOUT = "mcp_proxy_gate_timeout"
REASON_ERROR = "mcp_proxy_gate_error"
REASON_MALFORMED = "mcp_proxy_malformed_verdict"
REASON_CIRCUIT_OPEN = "mcp_proxy_gate_circuit_open"

# How many timeouts in a row open the breaker, and how long it stays open before
# one probe call is allowed through. Both are deliberately small: the breaker
# exists to stop a saturated gate from turning into an all-denied proxy, not to
# add a second opinion about authorisation.
DEFAULT_CONSECUTIVE_TIMEOUT_LIMIT = 3
DEFAULT_BREAKER_COOLDOWN_SECONDS = 5.0
# Budget for the reconciliation record. It must not re-introduce an unbounded wait
# on the path that just proved the gate can hang.
RECONCILE_BUDGET_SECONDS = 0.5


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
    # True when a linked deny was appended for a timed-out call, so the caller can
    # tell a reconciled timeout from an unreconciled one without parsing strings.
    reconciled: bool = False


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


def timeout_from_env(var: str = "CUSTOS_MCP_GATE_TIMEOUT",
                     default: float = DEFAULT_TIMEOUT_SECONDS) -> float:
    """Read a bounded timeout from the environment, failing at startup.

    A malformed value must not fall back to the default: an operator who typed
    ``CUSTOS_MCP_GATE_TIMEOUT=1e9`` or ``30s`` believes a bound is in force, and a
    silent fallback would leave them believing it while the proxy waits forever.
    """
    raw = os.environ.get(var)
    if raw is None or raw.strip() == "":
        return _validated_timeout(default)
    try:
        return _validated_timeout(float(raw))
    except ValueError as exc:
        raise ValueError(f"invalid {var}: {exc}") from exc


def _validated_cooldown(value: Any) -> float:
    """A cooldown must be a real, finite, non-negative number of seconds."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"breaker_cooldown_seconds must be a number, got {value!r}")
    value = float(value)
    if math.isnan(value) or math.isinf(value) or value < 0:
        raise ValueError(f"breaker_cooldown_seconds must be finite and >= 0, got {value!r}")
    return value


_UNSET: Any = object()


class McpProxy:
    """Mediates ``tools/call`` for one tenant through an injected gate adapter."""

    def __init__(
        self,
        gate: GateAdapter,
        *,
        tenant_id: str,
        timeout_seconds: Any = _UNSET,
        trace_id_factory: Optional[Callable[[], str]] = None,
        consecutive_timeout_limit: int = DEFAULT_CONSECUTIVE_TIMEOUT_LIMIT,
        breaker_cooldown_seconds: float = DEFAULT_BREAKER_COOLDOWN_SECONDS,
        clock: Optional[Callable[[], float]] = None,
    ) -> None:
        if not tenant_id:
            raise ValueError("tenant_id is required: an unlabelled call has no policy to apply")
        if not callable(getattr(gate, "evaluate", None)):
            raise ValueError("gate adapter must expose an async evaluate() method")
        self._gate = gate
        self._tenant_id = tenant_id
        # Omitted means "read the environment, else the default". An explicit
        # None still refuses: it is a caller asking for an unbounded wait.
        if timeout_seconds is _UNSET:
            self._timeout = timeout_from_env()
        else:
            self._timeout = _validated_timeout(timeout_seconds)
        self._trace_id_factory = trace_id_factory or (lambda: uuid.uuid4().hex)
        # Breaker state. Small and local on purpose: it answers "is the gate
        # answering at all" and nothing about whether an action is allowed.
        if consecutive_timeout_limit < 1:
            raise ValueError("consecutive_timeout_limit must be at least 1")
        self._timeout_limit = consecutive_timeout_limit
        self._breakers = {}
        self._cooldown = _validated_cooldown(breaker_cooldown_seconds)
        self._clock = clock or time.monotonic

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

        if self._breaker_open():
            # The gate is not answering. Denying here is the same decision a
            # timeout would produce, made without paying the timeout each time.
            return ProxyOutcome(
                forwarded=False,
                trace_id=trace_id,
                reason=REASON_CIRCUIT_OPEN,
                rule=REASON_CIRCUIT_OPEN,
            )

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
            self._record_answer(timed_out=True)
            reconciled = await self._reconcile_timeout(tool, trace_id)
            return ProxyOutcome(
                forwarded=False,
                trace_id=trace_id,
                reason=REASON_TIMEOUT,
                rule=REASON_TIMEOUT,
                reconciled=reconciled,
            )
        except Exception as exc:  # noqa: BLE001 - any gate failure must deny
            return ProxyOutcome(
                forwarded=False,
                trace_id=trace_id,
                reason=f"{REASON_ERROR}: {type(exc).__name__}",
                rule=REASON_ERROR,
            )

        self._record_answer(timed_out=False)

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

    # -- gate health -------------------------------------------------------
    def _record_answer(self, *, timed_out: bool) -> None:
        """Track consecutive timeouts and open the breaker at the limit."""
        state = self._breakers
        if timed_out:
            state["consecutive"] = state.get("consecutive", 0) + 1
            if state["consecutive"] >= self._timeout_limit:
                state["open_until"] = self._clock() + self._cooldown
        else:
            state["consecutive"] = 0
            state["open_until"] = None

    def _breaker_open(self) -> bool:
        """True while the gate is presumed not answering.

        When the cooldown lapses the breaker goes half-open rather than closed: one
        call is allowed through to see whether the gate recovered, and a single
        timeout re-opens it. That keeps recovery observable without a stampede.
        """
        open_until = self._breakers.get("open_until")
        if open_until is None:
            return False
        if self._clock() < open_until:
            return True
        self._breakers["open_until"] = None
        self._breakers["consecutive"] = max(self._timeout_limit - 1, 0)
        return False

    # -- reconciliation ----------------------------------------------------
    async def _reconcile_timeout(self, tool: str, trace_id: str) -> bool:
        """Ask the adapter to append a linked deny for a timed-out call.

        Optional by design: an adapter without the hook leaves the timeout
        uncited, which is the pre-existing behaviour and is reported honestly as
        ``reconciled=False`` rather than papered over. Failures here never change
        the denial, because the denial is already the safe answer.
        """
        hook = getattr(self._gate, "record_timeout_denial", None)
        if not callable(hook):
            return False
        try:
            result = hook(tenant_id=self._tenant_id, tool=tool, trace_id=trace_id)
            if inspect.isawaitable(result):
                await asyncio.wait_for(result, timeout=RECONCILE_BUDGET_SECONDS)
        except Exception:  # noqa: BLE001 - the denial stands either way
            return False
        return True

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
