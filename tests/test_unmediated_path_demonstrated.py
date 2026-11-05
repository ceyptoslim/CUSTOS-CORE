"""The unmediated path is demonstrated here, not merely declared.

P4 in the inventory asserts that a process which the upstream accepts can reach it without
traversing the decision point. That is an availability claim, and availability can be
tested rather than assumed: this file spawns the same in-repo upstream twice, once behind
the proxy and once with no gate anywhere in the loop, and compares what happened.

The pair is what carries the claim:

- mediated and denied: the tool does not run, no marker file appears, and the gate was asked;
- direct: no gate object exists in the process at all, the tool runs, and its marker appears.

A marker on its own would prove nothing, since the stub writes one on every call. The
denied case is the control that makes the marker an effect signal: absent when the call is
refused, present when the decision point is removed from the path.

**Scope, stated rather than implied.** This demonstrates availability for the upstream
shape the repository ships: a stdio server that accepts any caller and needs no credential.
An operator whose upstream rejects callers that do not present the proxy's credential, or
whose network closes egress except through the proxy, has a deployment in which this
demonstration does not transfer, and that is the observation the inventory names as
falsifying P4. The test below cannot make that observation for a deployment it has never
seen, and does not pretend to.
"""
import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

pytest.importorskip("mcp", reason="mcp SDK not installed; this demonstration needs it")

from custos.mcp_proxy import GateVerdict, McpProxy  # noqa: E402
from custos.mcp_stdio import python_upstream  # noqa: E402

UPSTREAM = str(Path(__file__).parent / "_mcp_upstream_server.py")


class DenyingGate:
    """A gate that refuses everything and counts the questions it was asked."""

    def __init__(self) -> None:
        self.asked: list[str] = []

    async def evaluate(self, *, tenant_id: str, tool: str, arguments: dict,
                       trace_id: str) -> GateVerdict:
        self.asked.append(tool)
        return GateVerdict(
            allowed=False,
            record_hash="deadbeef",
            rule="action_gate_tool_not_allowlisted",
            reason="not allowlisted",
        )


def _env(marker_dir: Path) -> dict:
    env = dict(os.environ)
    env["CUSTOS_MCP_MARKER_DIR"] = str(marker_dir)
    return env


@asynccontextmanager
async def _session(params):
    """An initialized MCP session over a spawned upstream, with no proxy in between."""
    from mcp import ClientSession
    from mcp.client.stdio import stdio_client

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


def test_direct_connection_executes_the_effect_with_no_decision_point(tmp_path):
    """No proxy, no gate, no decision record. The tool still runs."""
    marker_dir = tmp_path / "direct"
    marker_dir.mkdir()

    async def scenario():
        async with _session(python_upstream(UPSTREAM, env=_env(marker_dir))) as session:
            return await session.call_tool("delete_file", {})

    result = asyncio.run(scenario())

    assert result.content, "the direct call returned something"
    assert "delete_file executed" in result.content[0].text
    assert (marker_dir / "called-delete_file").exists(), (
        "the unmediated path produced the protected effect: the upstream ran the tool"
    )


def test_mediated_denial_leaves_no_marker_and_asks_the_gate(tmp_path):
    """The control: the same tool, the same upstream, one decision point in the path."""
    marker_dir = tmp_path / "mediated"
    marker_dir.mkdir()
    gate = DenyingGate()

    async def scenario():
        proxy = McpProxy(gate, tenant_id="t-unmediated", timeout_seconds=10.0)
        async with _session(python_upstream(UPSTREAM, env=_env(marker_dir))) as session:
            async def forward(name: str, args: dict):
                return await session.call_tool(name, args)

            return await proxy.call_tool("delete_file", {}, forward)

    outcome = asyncio.run(scenario())

    assert outcome.forwarded is False
    assert gate.asked == ["delete_file"], "the mediated path asked the gate"
    assert not (marker_dir / "called-delete_file").exists(), (
        "a denied call reached the upstream, which would be the gate failing open"
    )


def test_the_two_paths_differ_only_in_the_presence_of_the_decision_point(tmp_path):
    """Same upstream, same tool, same effect at stake. One path has a gate and one does not."""
    direct_dir = tmp_path / "a"
    mediated_dir = tmp_path / "b"
    direct_dir.mkdir()
    mediated_dir.mkdir()
    gate = DenyingGate()

    async def scenario():
        async with _session(python_upstream(UPSTREAM, env=_env(direct_dir))) as session:
            await session.call_tool("delete_file", {})

        proxy = McpProxy(gate, tenant_id="t-unmediated", timeout_seconds=10.0)
        async with _session(python_upstream(UPSTREAM, env=_env(mediated_dir))) as session:
            async def forward(name: str, args: dict):
                return await session.call_tool(name, args)

            await proxy.call_tool("delete_file", {}, forward)

    asyncio.run(scenario())

    assert (direct_dir / "called-delete_file").exists()
    assert not (mediated_dir / "called-delete_file").exists()
