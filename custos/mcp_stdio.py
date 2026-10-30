"""stdio binding: an MCP client that reaches an upstream server through the gate.

The proxy core decides nothing (see mcp_proxy.py); this module is the transport.
It spawns the upstream over stdio, lists its tools, and routes every tools/call
through McpProxy, which asks the gate first and forwards only on a literal True.

Pinned to the mcp 1.x API (`mcp.client.stdio`, `ClientSession`). The 2.x API
differs; _resolver_guard in the tests fails the build if 2.x is ever resolved.
"""
from __future__ import annotations

import os
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


# The upstream is the thing being governed, and this process holds credentials
# (JWT secret, database URL). So it gets an allowlist, never os.environ: whatever
# the governed component cannot read, it cannot leak or repurpose.
UPSTREAM_ENV_ALLOW = ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR")
UPSTREAM_ENV_EXTRA_VAR = "CUSTOS_MCP_UPSTREAM_ENV"
# Prefix reserved for this process's own configuration and secrets. An upstream is
# the component being governed; it has no business reading our keys, and an operator
# typo should fail loudly rather than quietly hand them over.
RESERVED_ENV_PREFIX = "CUSTOS_"


def _refuse_reserved(names) -> None:
    """Reject any attempt to hand this process's own CUSTOS_* config downstream."""
    reserved = sorted(n for n in names if n.startswith(RESERVED_ENV_PREFIX))
    if reserved:
        raise ValueError(
            f"{UPSTREAM_ENV_EXTRA_VAR} may not pass {reserved}: names beginning "
            f"{RESERVED_ENV_PREFIX} are this proxy's own configuration and secrets"
        )


def upstream_env(extra_names: Optional[list[str]] = None) -> dict[str, str]:
    """Environment for a spawned upstream: PATH/HOME and what an operator names.

    Names come from ``UPSTREAM_ENV_ALLOW``, the comma-separated
    ``CUSTOS_MCP_UPSTREAM_ENV`` setting, and ``extra_names``. Everything else in
    this process's environment — secrets included — stays here.

    ``PYTHONPATH`` is deliberately not in the default allowlist: it decides what
    code a Python upstream imports, and that upstream is the thing being governed.
    An operator who wants it can name it explicitly. Names beginning ``CUSTOS_``
    are refused outright, in the setting and in ``extra_names`` alike.
    """
    configured = [
        name.strip()
        for name in os.environ.get(UPSTREAM_ENV_EXTRA_VAR, "").split(",")
        if name.strip()
    ]
    extra = [n for n in (extra_names or []) if n]
    _refuse_reserved(configured + extra)
    allowed = set(UPSTREAM_ENV_ALLOW)
    allowed.update(configured)
    allowed.update(extra)
    return {name: os.environ[name] for name in sorted(allowed) if name in os.environ}


def upstream_params(command: str, args: Optional[list[str]] = None,
                    env: Optional[dict[str, str]] = None,
                    cwd: Optional[str] = None,
                    allow_env: Optional[list[str]] = None) -> "StdioServerParameters":
    """Build spawn parameters for an upstream server.

    ``env=None`` means the allowlist from ``upstream_env()``, not the inherited
    environment. Pass an explicit dict only when the caller really wants full
    control of what the governed process can read.
    """
    if StdioServerParameters is None:  # pragma: no cover
        raise RuntimeError("the mcp SDK is required for the stdio binding")
    if env is None:
        env = upstream_env(allow_env)
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
