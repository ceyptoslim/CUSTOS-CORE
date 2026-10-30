"""End-to-end: a denied call must never reach a real MCP server.

The upstream is a tiny in-repo server spawned with sys.executable, which writes a
marker file on every tool call. If the marker exists after a denied call, the gate
was bypassed; that is the assertion, not the proxy's own return value.
"""
import asyncio
import os
import sys
from pathlib import Path

import pytest

pytest.importorskip("mcp", reason="mcp SDK not installed; binding tests need it")

from custos.mcp_proxy import GateVerdict, McpProxy  # noqa: E402
from custos.mcp_stdio import mediated_session, python_upstream  # noqa: E402

UPSTREAM = str(Path(__file__).parent / "_mcp_upstream_server.py")


class ScriptedGate:
    """Verdict per tool, mimicking the real gate's contract."""

    def __init__(self, allowed: set[str], record_hash: str = "deadbeef") -> None:
        self.allowed = allowed
        self.record_hash = record_hash
        self.seen: list[tuple[str, str]] = []

    async def evaluate(self, *, tenant_id: str, tool: str, arguments: dict,
                       trace_id: str) -> GateVerdict:
        self.seen.append((tool, trace_id))
        if tool in self.allowed:
            return GateVerdict(allowed=True, record_hash=self.record_hash, rule=None, reason="ok")
        return GateVerdict(allowed=False, record_hash=self.record_hash,
                           rule="action_gate_tool_not_allowlisted", reason="not allowlisted")


def _run(tmp_path: Path, allowed: set[str]) -> dict:
    env = dict(os.environ)
    env["CUSTOS_MCP_MARKER_DIR"] = str(tmp_path)

    async def scenario() -> dict:
        gate = ScriptedGate(allowed)
        proxy = McpProxy(gate, tenant_id="t-smoke", timeout_seconds=10.0)
        params = python_upstream(UPSTREAM, env=env)
        from mcp import ClientSession
        from mcp.client.stdio import stdio_client
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                listed = await session.list_tools()

                async def forward(name: str, args: dict):
                    return await session.call_tool(name, args)

                allowed_outcome = await proxy.call_tool("read_file", {}, forward)
                denied_outcome = await proxy.call_tool("delete_file", {}, forward)
                return {"listed": [t.name for t in listed.tools],
                        "allowed": allowed_outcome, "denied": denied_outcome, "gate": gate}

    return asyncio.run(scenario())


def test_denied_call_never_contacts_the_upstream(tmp_path):
    result = _run(tmp_path, allowed={"read_file"})
    assert (tmp_path / "called-read_file").exists(), "allowed call should have reached upstream"
    assert not (tmp_path / "called-delete_file").exists(), \
        "denied call reached the upstream server"
    assert result["denied"].forwarded is False
    assert result["denied"].rule == "action_gate_tool_not_allowlisted"


def test_allowed_call_returns_the_gate_record_hash(tmp_path):
    result = _run(tmp_path, allowed={"read_file"})
    assert result["allowed"].forwarded is True
    assert result["allowed"].record_hash == "deadbeef"


def test_gate_is_consulted_with_a_minted_trace_id(tmp_path):
    result = _run(tmp_path, allowed={"read_file"})
    tools = [t for t, _ in result["gate"].seen]
    assert tools == ["read_file", "delete_file"]
    assert all(len(tid) >= 16 for _, tid in result["gate"].seen)


def test_resolver_guard_pins_mcp_below_two():
    import importlib.metadata as md
    version = md.version("mcp")
    major = int(version.split(".")[0])
    assert major < 2, f"mcp {version} resolved; the stdio binding targets the 1.x API"
