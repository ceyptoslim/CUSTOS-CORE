#!/usr/bin/env bash
# SABOTAGE 004: Weaken the custody external verify's P2 reconciliation
# (must turn the suite RED, or the run is recorded FAULTY-GREEN).
#
# The anchored-head comparison in verify_custody's P2 block no longer
# fires: a consistently rewritten audit store (the rewrite-and-rehash
# attack — internal chain verification green, store tampered) would
# reconcile as ESTABLISHED against the external anchors. Pre-registered in
# docs/red-proof-records/sabotage-custody/DESIGN.md (hash pinned in the
# workflow). NOT engineered to dodge tests; see DESIGN.md "Blindness" for
# the disclosed weaker-blindness position on this class.
set -euo pipefail
sed -i 's/if head != a.head_hash:/if False:/' custos/custody.py
# Integrity guard: a silent no-op here would fake a FAULTY-GREEN.
grep -q 'if False:' custos/custody.py || {
  echo "[sabotage] FAILED TO APPLY - P2 reconciliation not weakened (code drift?)"; exit 1;
}
echo "[sabotage] custody P2 anchored-head reconciliation disabled (known-bad patch applied)"
