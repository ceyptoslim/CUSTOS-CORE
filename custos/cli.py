"""Zero-config command line for CUSTOS-CORE.

Three commands, in the order a stranger meets them:

    custos-core print-config   the Claude Desktop block, with absolute paths
    custos-core serve --demo   the mediated stdio server the client spawns
    custos-core verify         the audit chain on disk, and whether it holds

Nothing here needs a database, a server or a secret. State lives in a directory
under the user's home, chosen by CUSTOS_HOME, so a first run writes somewhere
predictable and a second run finds what the first wrote.

Only ``serve`` needs the ``mcp`` extra; ``print-config`` and ``verify`` work on a
bare install, so a participant can check the chain even if the SDK is missing.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

TENANT = "local"
# The one tool the demo allowlist names. delete_notes is deliberately absent.
DEMO_ALLOWLIST = ("read_notes",)
DENIAL_TEMPLATE = "CUSTOS denied this call: tool={tool} rule={rule} record={record}"


def _home() -> Path:
    configured = os.environ.get("CUSTOS_HOME")
    return Path(configured) if configured else Path.home() / ".custos"


def _prepare_state() -> dict[str, str]:
    """Create the state directory and point both stores at it.

    ``setdefault`` rather than assignment: an operator who has already exported
    AUDIT_DB_PATH means it, and a CLI that silently redirected their records
    would be the kind of surprise this project exists to prevent.
    """
    home = _home()
    home.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("AUDIT_DB_PATH", str(home / "audit.db"))
    os.environ.setdefault("POLICY_DB_PATH", str(home / "policy.db"))
    return {"home": str(home), "audit": os.environ["AUDIT_DB_PATH"],
            "policy": os.environ["POLICY_DB_PATH"]}


def _context():
    from custos.tenant import TenantConfig, TenantManager

    manager = TenantManager()
    return manager, manager.register(TENANT, TenantConfig(tenant_id=TENANT))


def _build_gate(allowlist):
    from custos.action_gate import ActionGate

    manager, _ctx = _context()
    gate = ActionGate(manager)
    gate.register_tools(TENANT, set(allowlist))
    return gate


def cmd_print_config(args: argparse.Namespace) -> int:
    state = _prepare_state()
    block = {
        "mcpServers": {
            "custos": {
                "command": sys.executable,
                "args": ["-m", "custos.cli", "serve", "--demo"],
            }
        }
    }
    # stdout is the block and nothing else, so it can be copied whole. The paths
    # a participant needs but must not paste go to stderr.
    print(json.dumps(block, indent=2))
    print(f"config file: {_config_path()}", file=sys.stderr)
    print(f"audit chain: {state['audit']}", file=sys.stderr)
    return 0


def _config_path() -> str:
    if sys.platform == "darwin":
        return str(Path.home() / "Library/Application Support/Claude/claude_desktop_config.json")
    if os.name == "nt":
        return str(Path(os.environ.get("APPDATA", Path.home())) / "Claude/claude_desktop_config.json")
    return str(Path.home() / ".config/Claude/claude_desktop_config.json")


def cmd_verify(args: argparse.Namespace) -> int:
    state = _prepare_state()
    _manager, ctx = _context()
    chain = ctx.audit_chain
    ok, detail = chain.verify()[:2]
    # head() is (length, head_hash); the first element is a count, not a hash.
    length, head_hash = chain.head()
    print(f"audit chain: {state['audit']}")
    print(f"backend: {chain.backend_type}")
    print(f"records: {length}")
    print(f"head: {head_hash}")
    print(f"verify: {'OK' if ok else 'FAILED'} {detail if not ok else ''}".rstrip())
    return 0 if ok else 1


def cmd_serve(args: argparse.Namespace) -> int:
    import asyncio

    _prepare_state()
    allowlist = tuple(args.allow.split(",")) if args.allow else DEMO_ALLOWLIST
    if args.demo and args.upstream:
        print("--demo and --upstream are alternatives", file=sys.stderr)
        return 2
    if not args.demo and not args.upstream:
        print("serve needs --demo or --upstream", file=sys.stderr)
        return 2
    try:
        return asyncio.run(_serve(allowlist, args))
    except KeyboardInterrupt:  # pragma: no cover - client closed the pipe
        return 0


async def _serve(allowlist, args) -> int:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import TextContent

    from custos.mcp_gate_adapter import build_proxy
    from custos.mcp_stdio import upstream_params

    gate = _build_gate(allowlist)
    proxy = build_proxy(gate, tenant_id=TENANT, timeout_seconds=args.timeout)
    if args.demo:
        params = upstream_params(sys.executable, ["-m", "custos.demo_upstream"])
    else:
        parts = args.upstream.split()
        params = upstream_params(parts[0], parts[1:])
    assert isinstance(params, StdioServerParameters)

    server: Server = Server("custos")

    async with stdio_client(params) as (up_read, up_write):
        async with ClientSession(up_read, up_write) as upstream:
            await upstream.initialize()

            @server.list_tools()
            async def list_tools():
                return await upstream.list_tools()

            @server.call_tool()
            async def call_tool(name: str, arguments: dict):
                captured: dict = {}

                async def forward(tool: str, tool_args: dict):
                    # The proxy discards the forwarded value by design; a server
                    # has to return it, so it is captured here rather than by
                    # changing the proxy's contract.
                    captured["result"] = await upstream.call_tool(tool, tool_args)

                outcome = await proxy.call_tool(name, arguments or {}, forward)
                if outcome.forwarded:
                    return captured.get("result")
                return [TextContent(type="text", text=DENIAL_TEMPLATE.format(
                    tool=name, rule=outcome.rule or outcome.reason,
                    record=outcome.record_hash or "none"))]

            async with stdio_server() as (read, write):
                await server.run(read, write, server.create_initialization_options())
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="custos-core", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    config = sub.add_parser("print-config", help="print the Claude Desktop JSON block")
    config.set_defaults(func=cmd_print_config)

    verify = sub.add_parser("verify", help="check the audit chain on disk")
    verify.set_defaults(func=cmd_verify)

    serve = sub.add_parser("serve", help="run the mediated stdio server")
    serve.add_argument("--demo", action="store_true", help="govern the bundled demo server")
    serve.add_argument("--upstream", help="command to spawn and govern")
    serve.add_argument("--allow", help="comma-separated tool allowlist (default: read_notes)")
    serve.add_argument("--timeout", type=float, default=15.0, help="gate timeout in seconds")
    serve.set_defaults(func=cmd_serve)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
