"""A tiny MCP server used as the upstream in smoke tests.

Every tool call writes a marker file into MARKER_DIR, so a test can assert that a
denied call never reached the server at all. No network, no npx: the test spawns
this with sys.executable.
"""
import asyncio
import os
from pathlib import Path

import anyio
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

MARKER_DIR = Path(os.environ["CUSTOS_MCP_MARKER_DIR"])

server: Server = Server("custos-test-upstream")


def _mark(tool: str) -> None:
    (MARKER_DIR / f"called-{tool}").write_text("contacted\n", encoding="utf-8")


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(name="read_file", description="read", inputSchema={"type": "object"}),
        Tool(name="delete_file", description="delete", inputSchema={"type": "object"}),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    _mark(name)
    return [TextContent(type="text", text=f"{name} executed")]


async def main() -> None:
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    anyio.run(main)
