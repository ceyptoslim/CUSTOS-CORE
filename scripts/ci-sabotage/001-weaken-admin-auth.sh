#!/usr/bin/env bash
# SABOTAGE 001: Weaken admin authentication (must turn the suite RED).
#
# Replaces the token verification call with a no-op, so require_auth
# and optional_auth no longer verify bearer tokens. Every 401/auth
# regression test MUST fail. If CI stays green after this patch, the
# suite cannot detect auth regressions and the green is meaningless.
set -euo pipefail
sed -i 's/return verify_token(credentials)/return None/' main.py
echo "[sabotage] admin auth verification disabled (known-bad patch applied)"
