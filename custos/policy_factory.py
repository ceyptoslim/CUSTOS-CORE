"""
CUSTOS Policy Engine Factory.

Selects the policy engine based on CUSTOS_POLICY_ENGINE environment variable:
  - "regex"  (default) — regex-based engine (always available, no deps)
  - "opa"    — OPA/Rego engine (requires OPA server at CUSTOS_OPA_URL)
  - "hybrid" — regex + OPA (regex first, OPA second, graceful fallback)

This mirrors the audit backend factory pattern (SQLite vs PostgreSQL).
Existing tests are unaffected — default is "regex" which uses the original engine.
"""
# Copyright (C) 2024-2026 FroLife Productions
# Licensed under the GNU Affero General Public License v3.0 (AGPL-3.0)
# See LICENSE file for details. Commercial license available upon request.



from __future__ import annotations

import logging
import os

from custos.policy_engine import PolicyEngine as RegexPolicyEngine

logger = logging.getLogger(__name__)


def create_policy_engine():
    """
    Factory: create the policy engine based on CUSTOS_POLICY_ENGINE env var.

    Returns:
        - RegexPolicyEngine (default, no external deps)
        - OPAPolicyEngine (requires OPA server, fails closed)
        - HybridPolicyEngine (regex + OPA, graceful fallback)
    """
    engine_type = os.getenv("CUSTOS_POLICY_ENGINE", "regex").lower().strip()

    if engine_type == "opa":
        logger.info("Using OPA policy engine (CUSTOS_POLICY_ENGINE=opa)")
        from custos.opa_engine import OPAPolicyEngine
        return OPAPolicyEngine()

    if engine_type == "hybrid":
        logger.info("Using hybrid policy engine (CUSTOS_POLICY_ENGINE=hybrid)")
        from custos.hybrid_engine import HybridPolicyEngine
        return HybridPolicyEngine()

    # Default: regex (backwards compatible, no external dependencies)
    logger.info("Using regex policy engine (CUSTOS_POLICY_ENGINE=regex)")
    return RegexPolicyEngine()
