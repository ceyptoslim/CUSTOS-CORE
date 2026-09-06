"""
Surplus-Recovery Outreach Policy Pack (functional working name — no brand;
naming pending attorney clearance).

Fail-closed compliance gate for AI-drafted tax-deed surplus / overage
recovery outreach letters. Five rule groups, all config on the EXISTING
policy components (PolicyRule / PolicyEngine / TenantManager) — zero core
engine, API, or schema changes:

1. STATUTE-CITATION GATE (fail-closed allowlist). Every Florida statute
   citation in a draft (e.g. "s. 197.582", "F.S. 201.582", "Section 197.582")
   must exist in packs/verified_statutes.json — a registry the OWNER populates
   only after verifying each statute against official Florida sources
   (flsenate.gov). The registry SHIPS EMPTY: until a statute is verified and
   entered, ANY citation is DENIED. No AI-generated statute number can pass
   this gate. Unverified citation = no letter goes out.

1b. COURT-CITATION GATE (fail-closed allowlist). Every court citation in a
   draft ("Smith v. Jones, 123 So. 3d 456", "500 U.S. 123", "2026 WL 1234567")
   must be covered by an entry in packs/verified_cases.json — the OWNER-
   populated registry that also SHIPS EMPTY. This is the Nippon v. OpenAI
   fabricated-citation class: an AI-generated case cite cannot pass.

2. GUARANTEE LANGUAGE (DENY). Guaranteed / risk-free outcome claims are
   prohibited — surplus recovery outcomes are never guaranteed.

3. UPL RISK (DENY). Unauthorized-practice-of-law patterns: claiming to give
   legal advice, claiming attorney identity, claiming court representation.
   ("Consult your own attorney" is allowed and encouraged.)

4. PREDATORY URGENCY (DENY). Pressure tactics ("act now", "final notice",
   "last chance") are prohibited in owner-outreach letters.

5. FEE-STRUCTURE CLAIMS (AUDIT). Any percentage-fee phrasing flags for
   owner review against the executed fee agreement before sending.

Usage (dogfooding path — the owner's own surplus pipeline is the first
governed workload):

    from custos.tenant import TenantManager
    from packs.surplus_recovery import load_pack, evaluate_outreach

    tm = TenantManager()
    load_pack(tm)                       # registers tenant "surplus_recovery" + rules
    result = evaluate_outreach(tm, draft_letter_text)
    # result.allowed is False on ANY deny — fail-closed by construction.

LICENSED UNDER AGPL-3.0. Commercial license available upon request.
"""
# Copyright (C) 2024-2026 FroLife Productions
# Licensed under the GNU Affero General Public License v3.0 (AGPL-3.0)
# See LICENSE file for details. Commercial license available upon request.

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from custos.policy_engine import PolicyAction, PolicyResult, PolicyRule

if TYPE_CHECKING:  # pragma: no cover
    from custos.tenant import TenantContext, TenantManager

DEFAULT_TENANT_ID = "surplus_recovery"
DEFAULT_REGISTRY_PATH = Path(__file__).parent / "verified_statutes.json"
DEFAULT_CASE_REGISTRY_PATH = Path(__file__).parent / "verified_cases.json"

# Court citations: "Smith v. Jones, 123 So. 3d 456", "500 U.S. 123",
# "45 F. Supp. 3d 789", "2026 WL 1234567" (the Nippon v. OpenAI fabrication class).
_COURT_CITATION_RES = [
    re.compile(
        r"\b[A-Z][\w&.'\u2019]*(?:\s+[A-Z][\w&.'\u2019]*){0,4}\s+v\.?\s+"
        r"[A-Z][\w&.'\u2019]*(?:\s+[A-Z][\w&.'\u2019]*){0,4},?\s*\d+\s+"
        r"(?:U\.S\.?|F\.2d|F\.3d|F\.4th|F\.?\s?Supp\.?\s?\d?d?|So\.?\s?\d?d?|WL|Fla\.?)(?:\s+\d+)?"
    ),
    re.compile(
        r"\b\d+\s+(?:U\.S\.?|F\.2d|F\.3d|F\.4th|F\.?\s?Supp\.?\s?\d?d?|So\.?\s?\d?d?|WL)\s+\d+\b"
    ),
]


# Citations: "§ 197.582", "s. 197.582", "F.S. 197.582", "Fla. Stat. § 197.582",
# "Section 197.582", "Statute 197.582", "Sec. 197.582". Group 1 = statute number.
_STATUTE_CITATION_RE = re.compile(
    r"(?:§|\bF\.?S\.?|\bFla\.?\s+Stat\.?|\bSection\b|\bStatute\b|\bSec\.?|\bs\.)\s*§?\s*(\d{1,4}\.\d{1,4})"
)


def pack_rules() -> list[PolicyRule]:
    """Return the pack's outreach rules (DENY unless noted)."""
    return [
        PolicyRule(
            name="surplus_guarantee_language",
            pattern=r"(?i)\b(guarantee[ds]?|guaranteed|risk[-\s]?free|no risk|100% (?:success|guaranteed))\b",
            action=PolicyAction.DENY,
            reason="Guaranteed-outcome language is prohibited in surplus-recovery outreach.",
        ),
        PolicyRule(
            name="surplus_upl_risk",
            pattern=r"(?i)\b(legal advice|(?:i am|we are|we're) (?:an? )?(?:lawyers?|law firm|attorneys?)|represent (?:you|the owner) in court)\b",
            action=PolicyAction.DENY,
            reason="UPL risk: outreach must not claim legal advice, attorney identity, or court representation.",
        ),
        PolicyRule(
            name="surplus_predatory_urgency",
            pattern=r"(?i)\b(act now|final notice|last chance|immediately or (?:you'?ll|you will) lose)\b",
            action=PolicyAction.DENY,
            reason="Predatory urgency/pressure tactics are prohibited in owner outreach.",
        ),
        PolicyRule(
            name="surplus_fee_structure",
            pattern=r"(?i)\b\d{1,3}\s*%\s*(?:of|commission|contingency|fee)\b",
            action=PolicyAction.AUDIT,
            reason="Fee-structure claim: owner must verify against the executed fee agreement before sending.",
        ),
    ]


def load_verified_statutes(path: Optional[Path] = None) -> dict:
    """Load the owner-verified Florida statute registry.

    Returns {} if the registry file is missing or malformed — fail-closed:
    an unreadable registry denies every citation, never allows.
    """
    p = path or DEFAULT_REGISTRY_PATH
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    registry = data.get("florida", {})
    return registry if isinstance(registry, dict) else {}


def find_unverified_citations(content: str, registry: Optional[dict] = None) -> list[str]:
    """Return statute numbers cited in `content` that are NOT in the registry.

    Registry None -> load from disk (ships empty -> all citations unverified).
    """
    reg = registry if registry is not None else load_verified_statutes()
    unverified: list[str] = []
    for m in _STATUTE_CITATION_RE.finditer(content):
        statute = m.group(1)
        if statute not in reg and statute not in unverified:
            unverified.append(statute)
    return unverified


def load_verified_cases(path: Optional[Path] = None) -> dict:
    """Load the owner-verified court-case registry (same fail-closed design
    as the statute registry: missing/malformed file -> {} -> all denied)."""
    p = path or DEFAULT_CASE_REGISTRY_PATH
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    registry = data.get("cases", {})
    return registry if isinstance(registry, dict) else {}


def find_unverified_case_citations(content: str, registry: Optional[dict] = None) -> list[str]:
    """Return court citations in `content` NOT covered by the verified registry.

    A citation is covered when a registry key (normalized) matches it —
    registry keys are the verified reporter cites, e.g. "123 So. 3d 456".
    """
    reg = (
        {re.sub(r"\s+", " ", k).strip().lower() for k in registry}
        if registry is not None
        else {re.sub(r"\s+", " ", k).strip().lower() for k in load_verified_cases()}
    )
    unverified: list[str] = []
    case_spans: list[tuple[int, int]] = []

    def _covered(cite: str) -> bool:
        return any(k in cite.lower() or cite.lower() in k for k in reg)

    # Case-form matches first ("Smith v. Jones, 123 So. 3d 456")
    for m in _COURT_CITATION_RES[0].finditer(content):
        case_spans.append(m.span())
        cite = re.sub(r"\s+", " ", m.group(0)).strip().rstrip(",.")
        if not _covered(cite) and cite not in unverified:
            unverified.append(cite)

    # Bare reporter cites ("500 U.S. 123") — skip any overlapping a case-form span
    for m in _COURT_CITATION_RES[1].finditer(content):
        s0, e0 = m.span()
        if any(not (e0 <= a or s0 >= b) for a, b in case_spans):
            continue
        cite = re.sub(r"\s+", " ", m.group(0)).strip().rstrip(",.")
        if not _covered(cite) and cite not in unverified:
            unverified.append(cite)
    return unverified


def load_pack(tenant_manager: "TenantManager", tenant_id: str = DEFAULT_TENANT_ID) -> "TenantContext":
    """Register the pack tenant and install the pack rules (persisted if a
    PolicyStore is configured). Idempotent per process: re-registration on an
    already-registered tenant adds duplicate rules, so callers should load once
    at startup (standard usage).
    """
    if tenant_manager.get(tenant_id) is None:
        from custos.tenant import TenantConfig

        tenant_manager.register(tenant_id, TenantConfig(tenant_id=tenant_id))
    for rule in pack_rules():
        tenant_manager.add_policy_rule(tenant_id, rule)
    return tenant_manager.get(tenant_id)  # type: ignore[return-value]


def evaluate_outreach(
    tenant_manager: "TenantManager",
    content: str,
    tenant_id: str = DEFAULT_TENANT_ID,
    registry: Optional[dict] = None,
    case_registry: Optional[dict] = None,
) -> PolicyResult:
    """Evaluate an outreach draft. Fail-closed by construction:

    1. Statute gate first: any unverified citation -> DENY (nothing else matters).
    2. Pack tenant missing (not loaded) -> DENY (no ungoverned evaluation).
    3. Otherwise the tenant's policy engine (base rules + pack rules) decides.
    """
    unverified = find_unverified_citations(content, registry)
    if unverified:
        return PolicyResult(
            allowed=False,
            action=PolicyAction.DENY,
            triggered_rule="surplus_statute_gate",
            reason=(
                "Unverified statute citation(s): " + ", ".join(unverified)
                + ". Only statutes the owner has verified against official Florida "
                "sources and entered into packs/verified_statutes.json may appear "
                "in outreach drafts."
            ),
        )

    unverified_cases = find_unverified_case_citations(content, case_registry)
    if unverified_cases:
        return PolicyResult(
            allowed=False,
            action=PolicyAction.DENY,
            triggered_rule="surplus_court_citation_gate",
            reason=(
                "Unverified court citation(s): " + "; ".join(unverified_cases)
                + ". Only citations the owner has verified against official sources "
                "and entered into packs/verified_cases.json may appear in "
                "outreach drafts (the Nippon v. OpenAI fabricated-citation class)."
            ),
        )

    ctx = tenant_manager.get_strict(tenant_id)
    if ctx is None:
        return PolicyResult(
            allowed=False,
            action=PolicyAction.DENY,
            triggered_rule="surplus_pack_not_loaded",
            reason="Surplus-recovery pack not loaded — fail-closed. No ungoverned outreach evaluation.",
        )
    return ctx.policy_engine.evaluate(content)
