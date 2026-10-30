"""stdio binding: an MCP client that reaches an upstream server through the gate.

The proxy core decides nothing (see mcp_proxy.py); this module is the transport.
It spawns the upstream over stdio, lists its tools, and routes every tools/call
through McpProxy, which asks the gate first and forwards only on a literal True.

Pinned to the mcp 1.x API (`mcp.client.stdio`, `ClientSession`). The 2.x API
differs; _resolver_guard in the tests fails the build if 2.x is ever resolved.
"""
from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Optional

from custos.mcp_proxy import McpProxy, ProxyOutcome

try:  # import-time optionality keeps the core importable without the SDK
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
except Exception:  # pragma: no cover - exercised only without the SDK
    ClientSession = None  # type: ignore[assignment]
    StdioServerParameters = None  # type: ignore[assignment]
    stdio_client = None  # type: ignore[assignment]


def upstream_params(command: str, args: Optional[list[str]] = None,
                    env: Optional[dict[str, str]] = None,
                    cwd: Optional[str] = None) -> "StdioServerParameters":
    """Build spawn parameters for an upstream server."""
    if StdioServerParameters is None:  # pragma: no cover
        raise RuntimeError("the mcp SDK is required for the stdio binding")
    return StdioServerParameters(command=command, args=args or [], env=env, cwd=cwd)


@asynccontextmanager
async def mediated_session(params: "StdioServerParameters",
                           proxy: McpProxy) -> AsyncIterator["MediatedUpstream"]:
    """Open an upstream session whose tool calls are mediated by `proxy`."""
    if ClientSession is None:  # pragma: no cover
        raise RuntimeError("the mcp SDK is required for the stdio binding")
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield MediatedUpstream(session=session, proxy=proxy)


class MediatedUpstream:
    """An upstream MCP session where call_tool goes through the gate first."""

    def __init__(self, session: Any, proxy: McpProxy) -> None:
        self._session = session
        self._proxy = proxy

    async def list_tools(self) -> Any:
        return await self._session.list_tools()

    async def call_tool(self, tool: str, arguments: Optional[dict] = None) -> ProxyOutcome:
        async def forward(name: str, args: dict) -> Any:
            return await self._session.call_tool(name, args)

        return await self._proxy.call_tool(tool, arguments, forward)


def python_upstream(script_path: str, env: Optional[dict[str, str]] = None) -> "StdioServerParameters":
    """Spawn an upstream server from a Python file with the current interpreter."""
    return upstream_params(sys.executable, [script_path], env=env)
