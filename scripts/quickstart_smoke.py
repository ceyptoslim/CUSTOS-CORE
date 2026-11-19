"""Rehearse the README quickstart on this machine, from the built wheel.

This is the install path a stranger follows, with the Claude Desktop step
replaced by a scripted client. It is what the three-OS CI job runs, and it is
what an author run measures for the five-minute clock.

    python scripts/quickstart_smoke.py dist/custos_core-*.whl

Steps, in order, each one asserted: build a virtual environment, install the
wheel with its extra, print the client config and check it names an absolute
interpreter, drive the server, then verify the chain on disk.
"""
from __future__ import annotations

import glob
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
DENIAL_PREFIX = "CUSTOS denied this call:"


def _run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, **kwargs)


def _venv_python(venv: Path) -> Path:
    return venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _cli(venv: Path) -> Path:
    return venv / ("Scripts/custos-core.exe" if os.name == "nt" else "bin/custos-core")


def main() -> int:
    wheel = sys.argv[1] if len(sys.argv) > 1 else None
    if not wheel:
        candidates = glob.glob(str(HERE.parent / "dist" / "custos_core-*.whl"))
        if not candidates:
            print("no wheel given and none found in dist/", file=sys.stderr)
            return 2
        wheel = candidates[0]
    wheel = str(Path(wheel).resolve())

    root = Path(tempfile.mkdtemp(prefix="custos-quickstart-"))
    venv = root / "venv"
    home = root / "home"
    started = time.monotonic()

    steps: list[tuple[str, subprocess.CompletedProcess]] = []
    steps.append(("create the environment", _run([sys.executable, "-m", "venv", str(venv)])))
    python = str(_venv_python(venv))
    steps.append(("install the wheel", _run(
        [python, "-m", "pip", "install", "--quiet", f"custos-core[mcp] @ file://{wheel}"])))

    for label, done in steps:
        if done.returncode != 0:
            print(f"FAIL at '{label}':\n{done.stdout}\n{done.stderr}", file=sys.stderr)
            return 1

    env = dict(os.environ)
    env["CUSTOS_HOME"] = str(home)
    config = _run([str(_cli(venv)), "print-config"], env=env)
    if config.returncode != 0:
        print(f"FAIL at 'print-config':\n{config.stderr}", file=sys.stderr)
        return 1
    block = json.loads(config.stdout)
    entry = block["mcpServers"]["custos"]
    if not Path(entry["command"]).is_absolute():
        print(f"FAIL: config command is not absolute: {entry['command']}", file=sys.stderr)
        return 1
    print(f"config block: {json.dumps(entry)}")

    client = _run([python, str(HERE / "quickstart_client.py")], env=env)
    print(client.stdout)
    if client.returncode != 0:
        print(client.stderr, file=sys.stderr)
        return 1

    verify = _run([str(_cli(venv)), "verify"], env=env)
    print(verify.stdout)
    if verify.returncode != 0 or "verify: OK" not in verify.stdout:
        print(f"FAIL at 'verify':\n{verify.stderr}", file=sys.stderr)
        return 1
    if "records: 2" not in verify.stdout:
        print("FAIL: the chain does not hold both calls", file=sys.stderr)
        return 1

    elapsed = time.monotonic() - started
    print(f"quickstart smoke: PASS in {elapsed:.1f}s on {sys.platform}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
