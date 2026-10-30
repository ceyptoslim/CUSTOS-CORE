"""Tests for the MCP proxy core.

The proxy is written so that a mistake in the gate cannot be masked by the proxy.
These tests attack that claim from both directions: the gate must be consulted for
every call, and nothing short of a literal ``True`` may authorize a forward.
"""

import ast
import asyncio
import inspect
from pathlib import Path

import pytest

from custos.mcp_proxy import (
    DEFAULT_TIMEOUT_SECONDS,
    REASON_ERROR,
    REASON_MALFORMED,
    REASON_TIMEOUT,
    GateVerdict,
    McpProxy,
)

MODULE = Path(__file__).resolve().parents[1] / "custos" / "mcp_proxy.py"


class RecordingGate:
    """Adapter that records what it was asked and answers on command."""

    def __init__(self, verdict=None, *, delay=0.0, raises=None):
        self.calls = []
        self._verdict = verdict
        self._delay = delay
        self._raises = raises

    async def evaluate(self, *, tenant_id, tool, arguments, trace_id):
        self.calls.append(
            {"tenant_id": tenant_id, "tool": tool, "arguments": arguments, "trace_id": trace_id}
        )
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._raises is not None:
            raise self._raises
        if callable(self._verdict):
            return self._verdict(tool, arguments, trace_id)
        return self._verdict


def run(coro):
    return asyncio.run(coro)


def proxy(gate, **kwargs):
    kwargs.setdefault("tenant_id", "t-acme")
    return McpProxy(gate, **kwargs)


# -- the allow path -------------------------------------------------------


def test_allow_forwards_once_and_returns_the_record_hash():
    gate = RecordingGate(GateVerdict(allowed=True, record_hash="abc123"))
    forwarded = []

    async def forward(tool, args):
        forwarded.append((tool, args))

    outcome = run(proxy(gate).call_tool("read_file", {"path": "/tmp/x"}, forward))

    assert outcome.forwarded is True
    assert outcome.record_hash == "abc123"
    assert forwarded == [("read_file", {"path": "/tmp/x"})]


def test_allow_without_a_forward_callable_is_still_a_decision():
    """A caller may want the verdict alone; no effect is implied by an allow."""
    gate = RecordingGate(GateVerdict(allowed=True, record_hash="h"))
    outcome = run(proxy(gate).call_tool("tools/list", {}))
    assert outcome.forwarded is True and outcome.record_hash == "h"


# -- the deny path --------------------------------------------------------


def test_deny_never_touches_the_upstream_server():
    gate = RecordingGate(GateVerdict(allowed=False, rule="tool_not_allowlisted", reason="nope"))
    forwarded = []

    async def forward(tool, args):  # pragma: no cover - must not run
        forwarded.append(tool)

    outcome = run(proxy(gate).call_tool("delete_file", {"path": "/"}, forward))

    assert outcome.forwarded is False
    assert forwarded == []
    assert outcome.rule == "tool_not_allowlisted"
    assert outcome.reason == "nope"


def test_deny_carries_the_gate_record_hash_when_there_is_one():
    gate = RecordingGate(GateVerdict(allowed=False, record_hash="r-deny", rule="r1"))
    outcome = run(proxy(gate).call_tool("x", {}))
    assert outcome.record_hash == "r-deny" and outcome.forwarded is False


# -- nothing loose authorizes --------------------------------------------


@pytest.mark.parametrize("loose", [1, "yes", "True", [True], {"allowed": True}, 1.0])
def test_only_a_literal_true_authorizes(loose):
    """Truthiness is not authorization - the same rule the OPA engine applies."""
    gate = RecordingGate(GateVerdict(allowed=loose))
    forwarded = []

    async def forward(tool, args):
        forwarded.append(tool)

    outcome = run(proxy(gate).call_tool("read_file", {}, forward))

    assert outcome.forwarded is False
    assert forwarded == []
    assert outcome.rule == REASON_MALFORMED


def test_a_none_verdict_is_malformed_not_an_allow():
    gate = RecordingGate(None)
    outcome = run(proxy(gate).call_tool("read_file", {}))
    assert outcome.forwarded is False and outcome.rule == REASON_MALFORMED


def test_a_verdict_without_an_allowed_field_is_malformed():
    class Opaque:
        record_hash = "h"

    gate = RecordingGate(Opaque())
    outcome = run(proxy(gate).call_tool("read_file", {}))
    assert outcome.forwarded is False and outcome.rule == REASON_MALFORMED


# -- fail closed on gate failure -----------------------------------------


def test_gate_timeout_denies_without_forwarding():
    gate = RecordingGate(GateVerdict(allowed=True), delay=0.2)
    forwarded = []

    async def forward(tool, args):
        forwarded.append(tool)

    outcome = run(proxy(gate, timeout_seconds=0.01).call_tool("read_file", {}, forward))

    assert outcome.forwarded is False
    assert forwarded == []
    assert outcome.rule == REASON_TIMEOUT


def test_gate_exception_denies():
    gate = RecordingGate(raises=RuntimeError("gate down"))
    outcome = run(proxy(gate).call_tool("read_file", {}))
    assert outcome.forwarded is False
    assert outcome.rule == REASON_ERROR
    assert "RuntimeError" in outcome.reason


@pytest.mark.parametrize("bad", [0, -1, 0.0, float("inf"), float("nan"), None, "2", True])
def test_an_unboundable_timeout_refuses_to_start(bad):
    with pytest.raises(ValueError):
        McpProxy(RecordingGate(GateVerdict(allowed=True)), tenant_id="t", timeout_seconds=bad)


def test_default_timeout_is_two_seconds():
    assert DEFAULT_TIMEOUT_SECONDS == 2.0
    assert proxy(RecordingGate(GateVerdict(allowed=True)))._timeout == 2.0


def test_adapter_without_evaluate_is_refused():
    class NotAGate:
        pass

    with pytest.raises(ValueError):
        McpProxy(NotAGate(), tenant_id="t")


def test_empty_tenant_is_refused():
    with pytest.raises(ValueError):
        McpProxy(RecordingGate(GateVerdict(allowed=True)), tenant_id="")


# -- correlation ---------------------------------------------------------


def test_trace_id_is_minted_and_reaches_the_gate():
    gate = RecordingGate(GateVerdict(allowed=True, record_hash="h"))
    run(proxy(gate).call_tool("read_file", {}))
    assert len(gate.calls) == 1
    trace_id = gate.calls[0]["trace_id"]
    assert isinstance(trace_id, str) and len(trace_id) >= 16


def test_each_call_gets_its_own_trace_id():
    gate = RecordingGate(GateVerdict(allowed=True))
    p = proxy(gate)
    run(p.call_tool("a", {}))
    run(p.call_tool("b", {}))
    assert gate.calls[0]["trace_id"] != gate.calls[1]["trace_id"]


def test_trace_id_factory_is_injectable_for_reproducible_records():
    counter = iter(["trace-0001", "trace-0002"])
    gate = RecordingGate(GateVerdict(allowed=True))
    p = proxy(gate, trace_id_factory=lambda: next(counter))
    run(p.call_tool("a", {}))
    run(p.call_tool("b", {}))
    assert [c["trace_id"] for c in gate.calls] == ["trace-0001", "trace-0002"]


def test_a_bad_trace_id_factory_is_refused_rather_than_shipping_an_empty_id():
    gate = RecordingGate(GateVerdict(allowed=True))
    p = proxy(gate, trace_id_factory=lambda: "")
    with pytest.raises(ValueError):
        run(p.call_tool("a", {}))


# -- the gate sees the real call -----------------------------------------


def test_the_gate_receives_tenant_tool_and_arguments_unchanged():
    gate = RecordingGate(GateVerdict(allowed=True))
    run(proxy(gate, tenant_id="t-9").call_tool("write_file", {"path": "/a", "n": 2}))
    call = gate.calls[0]
    assert call["tenant_id"] == "t-9"
    assert call["tool"] == "write_file"
    assert call["arguments"] == {"path": "/a", "n": 2}


def test_arguments_are_not_mutated_by_mediation():
    gate = RecordingGate(GateVerdict(allowed=True))
    args = {"path": "/a"}
    run(proxy(gate).call_tool("read_file", args))
    assert args == {"path": "/a"}


def test_the_gate_is_consulted_exactly_once_per_call():
    """One decision, one record - the proxy adds no second evaluation."""
    gate = RecordingGate(GateVerdict(allowed=True, record_hash="h"))
    run(proxy(gate).call_tool("read_file", {}))
    assert len(gate.calls) == 1


def test_a_failing_forward_does_not_retry_or_redecide():
    gate = RecordingGate(GateVerdict(allowed=True, record_hash="h"))

    async def forward(tool, args):
        raise OSError("upstream refused")

    with pytest.raises(OSError):
        run(proxy(gate).call_tool("read_file", {}, forward))
    assert len(gate.calls) == 1


# -- structural: the proxy must not become a second gate -----------------


def _module_ast():
    return ast.parse(MODULE.read_text())


def test_the_core_imports_nothing_from_custos():
    """A proxy that imports the gate's internals will eventually re-implement it."""
    imported = set()
    for node in ast.walk(_module_ast()):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert "custos" not in imported


def test_the_core_has_no_allowlist():
    """Deny-by-default lives in one place. A proxy-side list is a second policy."""
    offenders = [
        node.name.lower()
        for node in ast.walk(_module_ast())
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        and "allowlist" in node.name.lower()
    ]
    source = MODULE.read_text().lower()
    assert not offenders
    assert "allowlist_" not in source and "_allowlist" not in source


def test_the_proxy_exposes_no_verdict_shortcut():
    """No method may answer "is this allowed" without asking the gate."""
    shortcuts = [
        name
        for name, member in inspect.getmembers(McpProxy)
        if callable(member) and any(k in name.lower() for k in ("is_allowed", "permit", "authorize"))
    ]
    assert shortcuts == []
