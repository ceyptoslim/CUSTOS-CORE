#!/usr/bin/env bash
# SABOTAGE 005: Weaken the policy-commit citation binding
# (must turn the suite RED, or the run is recorded FAULTY-GREEN).
#
# Two lines, the minimal natural weakening of the R2 binding at both
# mutation vectors:
#   1. The content-key check in ActionGate._cited_policy_digest is
#      dropped — the gate returns the first digest it ever computed for
#      the tenant forever, so a rule change mid-stream leaves records
#      citing the OLD policy set while enforcement uses the new one
#      (citing X while doing Y).
#   2. The tools-change invalidation in register_tools is deleted.
# Pre-registered in docs/red-proof-records/sabotage-citation/DESIGN.md
# (hash pinned in the workflow). Expected failing assertions, named in
# advance: TestCitationAtEmission::test_record_cites_in_force_policy_digest
# and TestCitationAtEmission::test_rule_change_also_changes_citation.
# NOT engineered to dodge tests; see DESIGN.md "Blindness" for the
# disclosed weaker-blindness position on this class.
set -euo pipefail

# 1. Drop the content-key check.
sed -i 's/if cached is not None and cached\[0\] == key:/if cached is not None:/' custos/action_gate.py

# 2. Delete the register_tools invalidation.
sed -i '/self\._digest_cache\.pop(tenant_id, None)/d' custos/action_gate.py

# Integrity guards: a silent no-op would fake a FAULTY-GREEN.
grep -q 'if cached is not None:' custos/action_gate.py || {
  echo "[sabotage] FAILED TO APPLY - content-key check not weakened (code drift?)"; exit 1;
}
grep -q 'cached\[0\] == key' custos/action_gate.py && {
  echo "[sabotage] FAILED TO APPLY - key check still present"; exit 1;
}
grep -q '_digest_cache\.pop' custos/action_gate.py && {
  echo "[sabotage] FAILED TO APPLY - register_tools invalidation still present"; exit 1;
}
echo "[sabotage] citation binding weakened (stale digest on policy change; known-bad patch applied)"
