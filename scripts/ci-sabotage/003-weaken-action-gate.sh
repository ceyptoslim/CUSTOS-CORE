#!/usr/bin/env bash
# SABOTAGE 003: Weaken the action gate's declared-authority check
# (must turn the suite RED, or the run is recorded FAULTY-GREEN).
#
# The deny-by-default tool allowlist check in ActionGate.evaluate_action
# no longer fires: a tool the tenant never registered proceeds past the
# authorization-decision boundary. Pre-registered in
# docs/red-proof-records/sabotage-003/DESIGN.md (hash pinned in the
# workflow). NOT engineered to dodge tests; see DESIGN.md "Blindness".
set -euo pipefail
sed -i 's/if action.tool not in self._tool_allowlists.get(tenant_id, set()):/if False:/' custos/action_gate.py
# Integrity guard: a silent no-op here would fake a FAULTY-GREEN.
grep -q 'if False:' custos/action_gate.py || {
  echo "[sabotage] FAILED TO APPLY - authority check not weakened (code drift?)"; exit 1;
}
echo "[sabotage] action gate authority check disabled (known-bad patch applied)"
