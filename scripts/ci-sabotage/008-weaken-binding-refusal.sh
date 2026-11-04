#!/usr/bin/env bash
# SABOTAGE 008: Weaken the fail-closed binding refusal at the process boundary
# (must turn the suite RED, or the run is recorded FAULTY-GREEN).
#
# One change: the lifespan stops re-raising after a failed binding write and
# logs a warning instead. This is the patch an operator writes after a bad
# deploy — "a metadata write should not take down the service" — and it turns a
# fail-closed control into a comment about one. establish() still raises,
# record_binding() still raises, the module guarantee survives; the process
# simply stops acting on it.
#
# Pre-registered in docs/red-proof-records/sabotage-binding/DESIGN.md
# (hash pinned in the workflow). Expected failing assertion, named in advance:
# tests/test_startup_binding.py::test_startup_refuses_when_the_binding_cannot_be_written
#
# NOT engineered to dodge tests; see DESIGN.md "Blindness" for the disclosed
# weaker-blindness position on this class.
set -euo pipefail

python3 - <<'INJECT'
import pathlib

path = pathlib.Path("main.py")
source = path.read_text()

block = (
    '        logger.error("custos.deployment_binding.refused", extra={"reason": str(exc)})\n'
    '        raise\n'
)

if block not in source:
    raise SystemExit(
        "[sabotage] FAILED TO APPLY - refusal block not found in lifespan (code drift?)"
    )

replacement = (
    '        logger.warning(\n'
    '            "custos.deployment_binding.skipped", extra={"reason": str(exc)}\n'
    '        )\n'
)

path.write_text(source.replace(block, replacement, 1))
INJECT

# Integrity guards: a silent no-op would fake a FAULTY-GREEN.
grep -q 'custos.deployment_binding.refused' main.py && {
  echo "[sabotage] FAILED TO APPLY - refusal log line still present"; exit 1;
}
grep -q 'custos.deployment_binding.skipped' main.py || {
  echo "[sabotage] FAILED TO APPLY - fail-open warning not written"; exit 1;
}
# The module must keep raising: this weakening is the process-boundary one.
grep -q 'raise' custos/deployment_binding.py || {
  echo "[sabotage] FAILED TO APPLY - module no longer raises (wrong weakening applied)"; exit 1;
}
# And the flag gate must survive, so the class tests the refusal and not the opt-in.
grep -q 'CUSTOS_DEPLOYMENT_BINDING' custos/deployment_binding.py || {
  echo "[sabotage] FAILED TO APPLY - env flag gate removed (wrong weakening applied)"; exit 1;
}
echo "[sabotage] binding refusal weakened (process continues after a failed write; module still raises)"
