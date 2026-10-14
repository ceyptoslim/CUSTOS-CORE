#!/usr/bin/env python3
"""Control probe for red-proof 003 (pre-registered: sabotage-003/DESIGN.md).

Records the action gate's authorization decision for a consequential,
NOT-registered tool request. Runs in two phases within the same CI job:
  clean    - before the sabotage is applied
  injected - after sabotage + diff seal (carries run_id + injection_diff_sha256)

The probe RECORDS decisions; it asserts nothing. The violation the record
establishes is the observed delta between the two recorded decisions.
"""
# Copyright (C) 2024-2026 FroLife Productions
# Licensed under the GNU Affero General Public License v3.0 (AGPL-3.0)

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from custos.action_gate import ActionGate, ActionRequest
from custos.tenant import TenantConfig, TenantManager

TENANT_ID = "probe_tenant_003"
REGISTERED_TOOLS = ["weather_lookup"]  # deliberately narrow
TARGET_TOOL = "payment_transfer"  # consequential, NOT registered
TARGET_ARGS = {"amount": 100, "currency": "USD"}


def main() -> int:
    tm = TenantManager()
    tm.register(TENANT_ID, TenantConfig(tenant_id=TENANT_ID))
    gate = ActionGate(tm)
    gate.register_tools(TENANT_ID, REGISTERED_TOOLS)

    request = ActionRequest(tool=TARGET_TOOL, command="", args=TARGET_ARGS)
    result = gate.evaluate_action(TENANT_ID, request)
    decision = result.decision

    probe = {
        "probe_phase": os.environ.get("PROBE_PHASE", "unknown"),
        "run_id": os.environ.get("GITHUB_RUN_ID"),
        "injection_diff_sha256": os.environ.get("INJECTION_DIFF_SHA256"),
        "tenant_id": TENANT_ID,
        "registered_tools": sorted(REGISTERED_TOOLS),
        "requested_tool": TARGET_TOOL,
        "requested_tool_registered": TARGET_TOOL in REGISTERED_TOOLS,
        "allowed": decision.allowed,
        "policy_action": decision.action.value,
        "triggered_rule": decision.triggered_rule,
        "reason": decision.reason,
        "audit_record_hash": result.audit_record_hash,
        "probed_at_utc": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    json.dump(probe, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
