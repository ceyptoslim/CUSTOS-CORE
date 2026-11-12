"""A stub OpenAI-compatible server, for wiring proof only.

This is not a model and it produces nothing to score. It exists so the local
provider path can be exercised end to end, on a machine with no GPU, without
pretending that anything was measured. The distinction matters: an arm run
against this stub would record numbers that carry no information about a model,
so the stub answers only the question "does the client, the request shape and the
parsed tool call line up" and refuses to answer any other.

Usage:

    python scripts/benchmarks/local_openai_stub.py --port 0

It prints ``stub listening on http://127.0.0.1:<port>/v1`` and keeps serving
until interrupted. ``--port 0`` asks the kernel for a free port, which is what the
tests use so two runs cannot collide.
"""

from __future__ import annotations

import argparse
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

DEFAULT_TOOL = "get_balance"
DEFAULT_ARGUMENTS = '{"user_id": "7"}'


def _completion_body(model: str, tool_name: str, arguments: str) -> dict[str, Any]:
    return {
        "id": "chatcmpl-custos-stub",
        "object": "chat.completion",
        "created": 0,
        "model": model,
        "choices": [
            {
                "index": 0,
                "finish_reason": "tool_calls",
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_custos_stub",
                            "type": "function",
                            "function": {"name": tool_name, "arguments": arguments},
                        }
                    ],
                },
            }
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


class StubHandler(BaseHTTPRequestHandler):
    """Answers the two endpoints the client library touches, and nothing else."""

    protocol_version = "HTTP/1.1"
    model = "stub-model"
    tool_name = DEFAULT_TOOL
    arguments = DEFAULT_ARGUMENTS
    calls: list[dict[str, Any]] = []

    def _send(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - the stdlib names it this
        if self.path.rstrip("/").endswith("/models"):
            self._send(
                200,
                {
                    "object": "list",
                    "data": [
                        {
                            "id": self.model,
                            "object": "model",
                            "created": 0,
                            "owned_by": "custos-stub",
                        }
                    ],
                },
            )
            return
        self._send(404, {"error": {"message": f"no route {self.path}"}})

    def do_POST(self) -> None:  # noqa: N802 - the stdlib names it this
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            request = json.loads(raw)
        except json.JSONDecodeError:
            self._send(400, {"error": {"message": "body was not JSON"}})
            return
        # Recorded so a test can assert the request shape the runner actually
        # sends, which is the part a stub is allowed to prove.
        type(self).calls.append(
            {
                "path": self.path,
                "model": request.get("model"),
                "temperature": request.get("temperature"),
                "tools": [t.get("function", {}).get("name") for t in request.get("tools", [])],
            }
        )
        self._send(200, _completion_body(self.model, self.tool_name, self.arguments))

    def log_message(self, *_args: Any) -> None:
        """Silence, so a test run is not filled with request lines."""


def start_stub(
    *,
    port: int = 0,
    model: str = "stub-model",
    tool_name: str = DEFAULT_TOOL,
    arguments: str = DEFAULT_ARGUMENTS,
) -> tuple[ThreadingHTTPServer, threading.Thread, str]:
    """Start the stub on its own thread and return the server, thread and base URL."""
    handler = type("BoundStubHandler", (StubHandler,), {
        "model": model,
        "tool_name": tool_name,
        "arguments": arguments,
        "calls": [],
    })
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, bound = server.server_address[0], server.server_address[1]
    return server, thread, f"http://{host}:{bound}/v1"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--model", default="stub-model")
    parser.add_argument("--tool-name", default=DEFAULT_TOOL)
    parser.add_argument("--arguments", default=DEFAULT_ARGUMENTS)
    args = parser.parse_args(argv)
    server, _thread, base_url = start_stub(
        port=args.port,
        model=args.model,
        tool_name=args.tool_name,
        arguments=args.arguments,
    )
    print(f"stub listening on {base_url} (wiring proof only, not a measurement)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
