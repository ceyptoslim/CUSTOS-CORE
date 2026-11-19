"""The zero-config CLI, at the level a stranger meets it.

These run the installed entry point in a subprocess with CUSTOS_HOME pointed at
a temporary directory, because the thing under test is what a participant sees:
stdout that can be pasted, and a state directory that appears where it should.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

CLI = [sys.executable, "-m", "custos.cli"]


def _run(tmp_path: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["CUSTOS_HOME"] = str(tmp_path / "state")
    return subprocess.run(CLI + list(args), capture_output=True, text=True, env=env)


def test_print_config_is_copyable_json(tmp_path: Path) -> None:
    result = _run(tmp_path, "print-config")
    assert result.returncode == 0, result.stderr
    # stdout must be the block and nothing else, or it cannot be pasted whole.
    block = json.loads(result.stdout)
    entry = block["mcpServers"]["custos"]
    assert Path(entry["command"]).is_absolute(), "Claude Desktop spawns with a minimal PATH"
    assert entry["args"] == ["-m", "custos.cli", "serve", "--demo"]
    assert "claude_desktop_config.json" in result.stderr


def test_verify_reports_an_empty_chain(tmp_path: Path) -> None:
    result = _run(tmp_path, "verify")
    assert result.returncode == 0, result.stdout
    assert "records: 0" in result.stdout
    assert "verify: OK" in result.stdout


def test_serve_without_a_target_is_refused(tmp_path: Path) -> None:
    result = _run(tmp_path, "serve")
    assert result.returncode == 2
    assert "needs --demo or --upstream" in result.stderr
