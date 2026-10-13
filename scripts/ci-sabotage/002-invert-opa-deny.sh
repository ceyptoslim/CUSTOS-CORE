#!/usr/bin/env bash
# SABOTAGE 002: Invert OPA deny verdicts (must turn the suite RED).
#
# Flips every DENY construction in the OPA engine to an allow, so
# denied content flows through. OPA security regression tests MUST
# fail. If CI stays green after this patch, the suite cannot detect
# deny-logic regressions and the green is meaningless.
set -euo pipefail
sed -i 's/allowed=False,/allowed=True,/' custos/opa_engine.py
echo "[sabotage] OPA deny verdicts inverted (known-bad patch applied)"
