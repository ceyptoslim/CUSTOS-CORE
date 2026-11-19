"""A tiny governed server for the zero-config quickstart.

Two tools, one of which the default allowlist does not name. That is the whole
point: a stranger needs a call the gate refuses, without installing anything
else first.

This module reads no environment variables on purpose. The proxy spawns it with
the restricted allowlist in ``custos.mcp_stdio.upstream_env`` and refuses to pass
any ``CUSTOS_*`` name downstream, so a demo that needed one could not start.
"""
from __future__ import annotations

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

server: Server = Server("custos-demo-upstream")

NOTES = "Three notes: milk, stamps, call the plumber."


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="read_notes",
            description="Read the notes file. Harmless.",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="delete_notes",
            description="Delete every note. Destructive.",
            inputSchema={"type": "object", "properties": {}},
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "delete_notes":
        return [TextContent(type="text", text="all notes deleted")]
    return [TextContent(type="text", text=NOTES)]


async def main() -> None:
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
