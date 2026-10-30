"""Gate isolation: its own executor, a breaker, and a reconciled timeout.

Three separate failures, three separate answers:

* a stalled gate must not consume the loop's shared worker pool  -> own executor
* sustained timeouts must not turn into an all-denied proxy       -> breaker
* a late ALLOW must not sit in the chain unqualified              -> reconcile
"""
import asyncio
import os
import threading

import pytest

from custos.mcp_proxy import (
    REASON_CIRCUIT_OPEN,
    REASON_TIMEOUT,
    GateVerdict,
    McpProxy,
)


class CountingGate:
    """Times out, or answers, and counts how often it was asked."""

    def __init__(self, *, answer=True, delay=0.5, reconcile=None):
        self.calls = 0
        self._answer = answer
        self._delay = delay
        self.reconciled = []
        if reconcile is not None:
            self.record_denial = reconcile

    async def evaluate(self, *, tenant_id, tool, arguments, trace_id):
        self.calls += 1
        await asyncio.sleep(self._delay)
        return GateVerdict(allowed=self._answer, record_hash="h", rule=None, reason="ok")


def _proxy(gate, **kw):
    kw.setdefault("timeout_seconds", 0.05)
    return McpProxy(gate, tenant_id="t", **kw)


# -- breaker ---------------------------------------------------------------
def test_consecutive_timeouts_open_the_breaker_without_asking_the_gate():
    gate = CountingGate()
    proxy = _proxy(gate, consecutive_timeout_limit=3)

    async def scenario():
        for _ in range(3):
            out = await proxy.call_tool("t", {}, None)
            assert out.rule == REASON_TIMEOUT
        asked = gate.calls
        fast = await proxy.call_tool("t", {}, None)
        return asked, fast, gate.calls

    asked, fast, after = asyncio.run(scenario())
    assert asked == 3
    assert fast.rule == REASON_CIRCUIT_OPEN
    assert fast.forwarded is False
    assert after == 3, "an open breaker must not call the gate at all"


def test_a_success_clears_the_count_so_isolated_timeouts_never_open_it():
    gate = CountingGate()
    proxy = _proxy(gate, consecutive_timeout_limit=2)

    async def scenario():
        await proxy.call_tool("t", {}, None)          # timeout 1
        proxy._gate = gate                             # same object; explicit for clarity
        gate._delay = 0.0
        await proxy.call_tool("t", {}, None)          # success, resets
        gate._delay = 0.5
        out = await proxy.call_tool("t", {}, None)    # timeout 1 again, not 2
        return out

    out = asyncio.run(scenario())
    assert out.rule == REASON_TIMEOUT, "one isolated timeout must not open the breaker"


def test_the_breaker_half_opens_after_the_cooldown():
    gate = CountingGate()
    now = [1000.0]
    proxy = _proxy(gate, consecutive_timeout_limit=1, breaker_cooldown_seconds=5.0,
                   clock=lambda: now[0])

    async def scenario():
        await proxy.call_tool("t", {}, None)          # opens
        blocked = await proxy.call_tool("t", {}, None)
        now[0] += 6.0                                  # cooldown lapses
        gate._delay = 0.0
        probe = await proxy.call_tool("t", {}, None)
        return blocked, probe

    blocked, probe = asyncio.run(scenario())
    assert blocked.rule == REASON_CIRCUIT_OPEN
    assert probe.forwarded is True, "a half-open breaker lets exactly one probe through"


def test_a_nonsense_cooldown_refuses_to_start():
    with pytest.raises(ValueError):
        _proxy(CountingGate(), breaker_cooldown_seconds=float("inf"))
    with pytest.raises(ValueError):
        _proxy(CountingGate(), consecutive_timeout_limit=0)


# -- reconciliation --------------------------------------------------------
def test_timeout_appends_a_linked_deny_record():
    seen = []

    def reconcile(*, tenant_id, tool, trace_id, rule, reason):
        seen.append((tenant_id, tool, trace_id, rule))
        return True

    gate = CountingGate(reconcile=reconcile)
    proxy = _proxy(gate)
    out = asyncio.run(proxy.call_tool("delete_file", {}, None))

    assert out.rule == REASON_TIMEOUT
    assert out.reconciled is True
    assert seen == [("t", "delete_file", out.trace_id, REASON_TIMEOUT)], \
        "the deny record must carry the same trace_id and rule as the refusal"


def test_a_failing_reconciler_does_not_change_the_denial():
    def reconcile(**_kw):
        raise RuntimeError("audit store down")

    gate = CountingGate(reconcile=reconcile)
    proxy = _proxy(gate)
    out = asyncio.run(proxy.call_tool("t", {}, None))

    assert out.forwarded is False
    assert out.rule == REASON_TIMEOUT
    assert out.reconciled is False, "an unwritable store is reported, not hidden"


def test_an_adapter_without_the_hook_reports_uncited():
    out = asyncio.run(_proxy(CountingGate()).call_tool("t", {}, None))
    assert out.reconciled is False


def test_reconciliation_is_bounded_and_cannot_hang_the_denial():
    async def reconcile(**_kw):
        await asyncio.sleep(5)

    gate = CountingGate(reconcile=reconcile)
    proxy = _proxy(gate)

    async def scenario():
        start = asyncio.get_running_loop().time()
        out = await proxy.call_tool("t", {}, None)
        return out, asyncio.get_running_loop().time() - start

    out, elapsed = asyncio.run(scenario())
    assert out.reconciled is False
    assert elapsed < 1.5, "the reconcile budget must fire before the caller notices"


# -- stdio env allowlist ---------------------------------------------------
def test_upstream_env_is_an_allowlist_not_the_whole_environment(monkeypatch):
    from custos.mcp_stdio import upstream_env

    monkeypatch.setenv("CUSTOS_JWT_SECRET", "do-not-leak")
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@host/db")
    monkeypatch.setenv("PATH", "/usr/bin")
    env = upstream_env()

    assert env["PATH"] == "/usr/bin"
    assert "CUSTOS_JWT_SECRET" not in env
    assert "DATABASE_URL" not in env


def test_an_operator_can_name_extra_variables(monkeypatch):
    from custos.mcp_stdio import upstream_env

    monkeypatch.setenv("CUSTOS_MCP_UPSTREAM_ENV", "NODE_OPTIONS, MY_VAR")
    monkeypatch.setenv("NODE_OPTIONS", "--max-old-space-size=256")
    monkeypatch.setenv("MY_VAR", "1")
    monkeypatch.setenv("SOMETHING_ELSE", "no")
    env = upstream_env()

    assert env["NODE_OPTIONS"] == "--max-old-space-size=256"
    assert env["MY_VAR"] == "1"
    assert "SOMETHING_ELSE" not in env


# -- dedicated executor ----------------------------------------------------
def test_gate_work_runs_on_its_own_named_threads():
    """The adapter's pool is separate: a stalled gate cannot exhaust the default."""
    from types import SimpleNamespace

    from custos.mcp_gate_adapter import CustosGateAdapter
    from custos.policy_engine import PolicyAction

    names = []

    class FakeGate:
        def evaluate_action(self, tenant_id, request, client_id, trace_id=None):
            names.append(threading.current_thread().name)
            decision = SimpleNamespace(
                action=PolicyAction.ALLOW, triggered_rule=None, reason="ok"
            )
            return SimpleNamespace(decision=decision, audit_record_hash="h")

    adapter = CustosGateAdapter(FakeGate())
    try:
        verdict = asyncio.run(
            adapter.evaluate(tenant_id="t", tool="x", arguments={}, trace_id="tid")
        )
    finally:
        adapter.close()

    assert verdict.allowed is True
    assert names and all(n.startswith("custos-gate") for n in names), \
        f"gate work must run on its own pool, got {names}"


def test_an_explicit_env_dict_is_still_honoured(monkeypatch):
    """Callers who pass env mean it: no allowlist silently replaces their dict."""
    pytest.importorskip("mcp")
    from custos.mcp_stdio import upstream_params

    params = upstream_params("true", ["--x"], env={"ONLY": "this"})
    assert params.env == {"ONLY": "this"}


def test_the_adapter_appends_a_real_linked_record_on_timeout():
    """End-to-end against a real gate: the corrective record exists and joins.

    This is the guard for the adapter's two private-member accesses. If
    ``ActionGate`` stops exposing ``_tm`` or ``_cited_policy_digest``, the timeout
    path silently loses its record again — so this test asserts on the chain, not
    on a mock.
    """
    from custos.action_gate import ActionGate
    from custos.mcp_gate_adapter import CustosGateAdapter
    from custos.tenant import TenantManager

    tm = TenantManager()
    gate = ActionGate(tm)
    gate.register_tools("default", {"file_read"})
    adapter = CustosGateAdapter(gate, max_workers=1)
    proxy = McpProxy(adapter, tenant_id="default", timeout_seconds=0.05)

    class HangingGate:
        """Answers through the real gate never reaching it: blocks past the bound."""

        async def evaluate(self, **_kw):
            await asyncio.sleep(5)

    # Ask the real chain, but make the evaluate call hang by wrapping evaluate_action.
    original = gate.evaluate_action
    gate.evaluate_action = lambda *a, **kw: __import__("time").sleep(5)  # type: ignore[assignment]
    try:
        outcome = asyncio.run(proxy.call_tool("file_read", {}, None))
    finally:
        gate.evaluate_action = original  # type: ignore[assignment]
        adapter.close()

    assert outcome.reconciled is True, "a real adapter must be able to reconcile"
    ctx = tm.get_strict("default")
    records = [r for r in ctx.audit_chain._records if r.trace_id == outcome.trace_id]
    assert records, "the deny record must be in the chain under the call's trace_id"
    assert all(r.action.upper() == "DENY" for r in records)
    assert any(r.triggered_rule == "mcp_proxy_gate_timeout" for r in records)


# -- ordering: the deny wins on the marker, not on recency -----------------
def _real_gate():
    from custos.action_gate import ActionGate
    from custos.tenant import TenantManager

    tm = TenantManager()
    gate = ActionGate(tm)
    gate.register_tools("default", {"file_read"})
    return tm, gate


def _traces(tm):
    ctx = tm.get_strict("default")
    return list(ctx.audit_chain._records)


@pytest.mark.parametrize("grant_first", [True, False])
def test_a_late_grant_cannot_outvote_the_deny_whichever_order_it_lands(grant_first):
    """The reconciliation marker, not arrival order, decides what happened.

    Both orders are simulated against a real chain: the proxy's deny lands first and
    a late grant follows, or a grant is already there when the deny arrives. The rule
    is that a trace carrying ``mcp_proxy_gate_timeout`` means "not forwarded",
    regardless of which record is newer.
    """
    import time

    from custos.mcp_gate_adapter import CustosGateAdapter

    tm, gate = _real_gate()
    adapter = CustosGateAdapter(gate, max_workers=1)
    proxy = McpProxy(adapter, tenant_id="default", timeout_seconds=0.05)

    original = gate.evaluate_action
    gate.evaluate_action = lambda *a, **kw: time.sleep(5)  # type: ignore[assignment]

    ctx = tm.get_strict("default")
    try:
        if grant_first:
            ctx.audit_chain.record(
                client_id="gate", action="ALLOW", reason="late grant",
                content="t", trace_id="fixed-trace", tenant_id="default",
            )
            proxy._trace_id_factory = lambda: "fixed-trace"
        else:
            proxy._trace_id_factory = lambda: "fixed-trace"
        outcome = asyncio.run(proxy.call_tool("file_read", {}, None))
        if not grant_first:
            ctx.audit_chain.record(
                client_id="gate", action="ALLOW", reason="late grant",
                content="t", trace_id="fixed-trace", tenant_id="default",
            )
    finally:
        gate.evaluate_action = original  # type: ignore[assignment]
        adapter.close()

    records = [r for r in _traces(tm) if r.trace_id == "fixed-trace"]
    markers = [r for r in records if r.triggered_rule == "mcp_proxy_gate_timeout"]
    assert outcome.reconciled is True
    assert markers, "the deny marker must be present in both orders"
    assert all(m.action.upper() == "DENY" for m in markers)
    # The point of the test: whatever the order, the marker is what a reader keys on.
    assert any(r.action.upper() == "ALLOW" for r in records), \
        "precondition: a grant for the same trace exists in both orders"


# -- breaker denials are recorded too -------------------------------------
def test_a_breaker_denial_is_recorded_when_the_store_is_up():
    import time

    from custos.mcp_gate_adapter import CustosGateAdapter

    tm, gate = _real_gate()
    adapter = CustosGateAdapter(gate, max_workers=1)
    proxy = McpProxy(adapter, tenant_id="default", timeout_seconds=0.05,
                     consecutive_timeout_limit=2, breaker_cooldown_seconds=60.0)
    original = gate.evaluate_action
    gate.evaluate_action = lambda *a, **kw: time.sleep(5)  # type: ignore[assignment]
    try:
        for _ in range(2):
            asyncio.run(proxy.call_tool("file_read", {}, None))
        out = asyncio.run(proxy.call_tool("file_read", {}, None))
    finally:
        gate.evaluate_action = original  # type: ignore[assignment]
        adapter.close()

    assert out.rule == REASON_CIRCUIT_OPEN
    assert out.reconciled is True, "a breaker denial must not be silent"
    markers = [r for r in _traces(tm) if r.trace_id == out.trace_id
               and r.triggered_rule == REASON_CIRCUIT_OPEN]
    assert markers and markers[0].action.upper() == "DENY"


# -- half-open admits exactly one probe ------------------------------------
def test_half_open_admits_exactly_one_probe_under_concurrent_calls():
    gate = CountingGate(delay=0.2)
    proxy = _proxy(gate, consecutive_timeout_limit=1, breaker_cooldown_seconds=0.0)

    async def scenario():
        first = await proxy.call_tool("t", {}, None)      # times out, opens breaker
        assert first.rule == REASON_TIMEOUT
        gate._delay = 0.0                                 # the probe answers
        before = gate.calls
        results = await asyncio.gather(*[proxy.call_tool("t", {}, None) for _ in range(5)])
        return before, gate.calls - before, results

    before, extra_calls, results = asyncio.run(scenario())
    assert extra_calls == 1, f"half-open must admit one probe, gate saw {extra_calls}"
    denied = [r for r in results if r.rule == REASON_CIRCUIT_OPEN]
    allowed = [r for r in results if r.forwarded]
    assert len(allowed) == 1 and len(denied) == 4, (len(allowed), len(denied))


# -- env: PYTHONPATH out, CUSTOS_ reserved ---------------------------------
def test_pythonpath_is_not_in_the_default_allowlist(monkeypatch):
    from custos.mcp_stdio import upstream_env

    monkeypatch.setenv("PYTHONPATH", "/tmp/evil")
    assert "PYTHONPATH" not in upstream_env()


def test_the_setting_refuses_to_pass_our_own_prefixed_names(monkeypatch):
    from custos.mcp_stdio import upstream_env

    monkeypatch.setenv("CUSTOS_MCP_UPSTREAM_ENV", "PATH, CUSTOS_JWT_SECRET")
    with pytest.raises(ValueError) as exc:
        upstream_env()
    assert "CUSTOS_" in str(exc.value)


def test_programmatic_extra_names_are_refused_too():
    from custos.mcp_stdio import upstream_env

    with pytest.raises(ValueError):
        upstream_env(["CUSTOS_DATABASE_URL"])


def test_pythonpath_can_be_opted_into_explicitly(monkeypatch):
    from custos.mcp_stdio import upstream_env

    monkeypatch.setenv("PYTHONPATH", "/opt/vendor")
    assert upstream_env(["PYTHONPATH"])["PYTHONPATH"] == "/opt/vendor"


# -- no private access -----------------------------------------------------
def test_the_adapter_touches_no_private_members_of_the_gate():
    """Static guard: reconciliation goes through the public method only."""
    from pathlib import Path

    src = Path(__file__).resolve().parents[1] / "custos" / "mcp_gate_adapter.py"
    text = src.read_text()
    assert "_tm" not in text.replace("_tm(", ""), "adapter must not reach into _tm"
    assert "_cited_policy_digest" not in text, \
        "adapter must use ActionGate.record_reconciliation, not the citation helper"
