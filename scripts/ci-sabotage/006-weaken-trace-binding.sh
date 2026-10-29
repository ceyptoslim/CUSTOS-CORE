#!/usr/bin/env bash
# SABOTAGE 006: Weaken the trace-binding in the record-hash preimage
# (must turn the suite RED, or the run is recorded FAULTY-GREEN).
#
# One deletion, the minimal natural regression: drop trace_id from the
# preimage while LEAVING the binding marker in place. This is the tidy-up a
# well-meaning refactor performs on a field that looks redundant — the marker
# still says v1, records still look bound, and request correlation quietly
# stops being provable from the artifact (EABC docs/002, "Intrinsically
# Bound").
# Pre-registered in docs/red-proof-records/sabotage-trace-binding/DESIGN.md
# (hash pinned in the workflow). Expected failing assertions, named in
# advance: tests/test_audit_trace_binding.py::test_mutating_trace_id_breaks_verification
# and ::test_dropping_trace_id_breaks_verification.
# NOT engineered to dodge tests; see DESIGN.md "Blindness" for the disclosed
# weaker-blindness position on this class.
set -euo pipefail

python3 - <<'INJECT'
import pathlib

path = pathlib.Path("custos/audit.py")
source = path.read_text()

block = (
    '        trace_id = _field(record, "trace_id")\n'
    '        if trace_id:\n'
    '            fields["trace_id"] = trace_id\n'
)

if block not in source:
    raise SystemExit(
        "[sabotage] FAILED TO APPLY - trace-binding block not found in preimage (code drift?)"
    )

path.write_text(source.replace(block, "", 1))
INJECT

# Integrity guards: a silent no-op would fake a FAULTY-GREEN.
grep -q 'fields\["trace_id"\] = trace_id' custos/audit.py && {
  echo "[sabotage] FAILED TO APPLY - trace_id still bound in preimage"; exit 1;
}
grep -q 'trace_id = _field(record, "trace_id")' custos/audit.py && {
  echo "[sabotage] FAILED TO APPLY - trace_id lookup still present"; exit 1;
}
# The marker must survive: this weakening is the subtle one.
grep -q 'fields\["binding"\] = f"v{binding_version}"' custos/audit.py || {
  echo "[sabotage] FAILED TO APPLY - binding marker removed (wrong weakening applied)"; exit 1;
}
echo "[sabotage] trace binding weakened (marker intact, identifier outside the preimage; known-bad patch applied)"
