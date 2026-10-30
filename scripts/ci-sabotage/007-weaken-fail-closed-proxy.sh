#!/usr/bin/env bash
# SABOTAGE 007: Weaken the MCP proxy's fail-closed behavior
# (must turn the suite RED, or the run is recorded FAULTY-GREEN).
#
# The gate can answer "no" and still lose the guarantee if the mediation path
# forwards when the gate never answers. Two edits, one concept:
#   1. `except Exception` -> `except ValueError` in McpProxy.call_tool: a gate
#      whose backend raises RuntimeError propagates to the agent instead of
#      becoming a denial.
#   2. `timeout=self._timeout` -> `timeout=None`: the wait stops being bounded.
# Pre-registered in docs/red-proof-records/sabotage-mcp-proxy/DESIGN.md (hash
# pinned in the workflow). Expected failing assertions, named in advance:
#   tests/test_mcp_proxy.py::test_gate_exception_denies
#   tests/test_mcp_proxy.py::test_gate_timeout_denies_without_forwarding
# NOT engineered to dodge tests; see DESIGN.md "Blindness" for the disclosed
# weaker-blindness position on this class.
set -euo pipefail

TARGET="custos/mcp_proxy.py"

python3 - "$TARGET" <<'PY'
import sys
from pathlib import Path

path = Path(sys.argv[1])
source = path.read_text()

# 1. Gate errors stop denying.
old_except = """        except Exception as exc:  # noqa: BLE001 - any gate failure must deny"""
new_except = """        except ValueError as exc:  # noqa: BLE001 - narrowed: other errors propagate"""
assert old_except in source, "[sabotage 007] FAILED TO APPLY: except clause not found (code drift?)"
source = source.replace(old_except, new_except, 1)

# 2. The wait stops being bounded.
old_timeout = """                timeout=self._timeout,"""
new_timeout = """                timeout=None,"""
assert old_timeout in source, "[sabotage 007] FAILED TO APPLY: timeout argument not found (code drift?)"
source = source.replace(old_timeout, new_timeout, 1)

path.write_text(source)

# Integrity guards: refuse to report a red suite that came from a silent no-op.
patched = path.read_text()
assert "except ValueError as exc" in patched, "[sabotage 007] guard: exception narrowing absent"
assert "timeout=None," in patched, "[sabotage 007] guard: timeout disable absent"
assert "timeout=self._timeout," not in patched, "[sabotage 007] guard: original timeout still present"
print("[sabotage 007] proxy weakened (errors propagate, wait unbounded; known-bad patch applied)")
PY
