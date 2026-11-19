"""A scripted MCP client: what Claude Desktop does, minus the GUI.

Run with the virtual environment's interpreter, after `custos-core serve --demo`
has been configured. It asserts the two things the trial's definition of a block
requires: a CUSTOS denial in the tool result, and an audit chain that verifies
afterwards (checked by the caller running `custos-core verify`).

Exit 0 only when both the denial and the allowed call behave as documented.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

DENIAL_PREFIX = "CUSTOS denied this call:"
DENIED_TOOL = "delete_notes"
ALLOWED_TOOL = "read_notes"


async def _run(python: str, home: str) -> dict:
    env = dict(os.environ)
    env["CUSTOS_HOME"] = home
    params = StdioServerParameters(
        command=python, args=["-m", "custos.cli", "serve", "--demo"], env=env
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            denied = await session.call_tool(DENIED_TOOL, {})
            allowed = await session.call_tool(ALLOWED_TOOL, {})
            return {
                "tools": [t.name for t in tools.tools],
                "denied": denied.content[0].text,
                "allowed": allowed.content[0].text,
            }


def main() -> int:
    python = sys.executable
    home = os.environ["CUSTOS_HOME"]
    result = asyncio.run(_run(python, home))
    print(json.dumps(result, indent=2))
    problems = []
    if sorted(result["tools"]) != [DENIED_TOOL, ALLOWED_TOOL]:
        problems.append(f"tool list is {result['tools']}, not both demo tools")
    if not result["denied"].startswith(DENIAL_PREFIX):
        problems.append("the denied call did not return a CUSTOS denial")
    if ALLOWED_TOOL in result["denied"] or DENIED_TOOL in result["allowed"]:
        problems.append("results look swapped")
    for problem in problems:
        print(f"FAIL: {problem}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
