"""Policy-commit citation at emission.

Implements R1/R2 of docs/design/policy-commit-citation.md: every emitted
audit record cites the sha256 digest of the exact in-force policy set it
was enforced against, read on the same code path that made the decision.

The in-force policy set for a tenant is what the gate consults to enforce:
the tool allowlist plus the tenant content rules. Equal policy sets must
produce equal digests on every platform; any mutation that changes
enforcement semantics must change the digest.

Design note (R5 refinement, deliberate): the digest is computed at emission
rather than cached — the binding property requires the very next record to
reflect an in-flight policy change, and a cache invalidation bug would
violate exactly that property. The measured cost is guarded by the
committed benchmark receipt (docs/benchmarks/bench-oct24.json).
"""
# Copyright (C) 2024-2026 FroLife Productions
# Licensed under the GNU Affero General Public License v3.0 (AGPL-3.0)
# See LICENSE file for details. Commercial license available upon request.

import hashlib
import json
from typing import Iterable, Optional, Sequence

from custos.policy_engine import PolicyRule


def _rule_to_canonical(rule: PolicyRule) -> str:
    """Deterministic per-rule canonical JSON string."""
    from custos.policy_store import _rule_to_dict

    return json.dumps(
        _rule_to_dict(rule), sort_keys=True, separators=(",", ":")
    )


def canonical_policy_bytes(
    tools: Iterable[str], rules: Sequence[PolicyRule]
) -> bytes:
    """Exactly one canonical byte representation of a policy set."""
    payload = json.dumps(
        {
            "tools": sorted(tools),
            "rules": sorted(_rule_to_canonical(r) for r in rules),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return payload.encode("utf-8")


def rules_canonical_digest(rules: Sequence[PolicyRule]) -> str:
    """sha256 of the canonical rules component alone (cacheable, R5)."""
    import hashlib

    payload = json.dumps(
        sorted(_rule_to_canonical(r) for r in rules),
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def policy_digest(tools: Iterable[str], rules: Sequence[PolicyRule]) -> str:
    """sha256 of the canonical in-force policy set (R1)."""
    return hashlib.sha256(canonical_policy_bytes(tools, rules)).hexdigest()

REGEX_ENGINE = "regex"


def engine_citation_bytes(
    tools: Iterable[str],
    rules: Sequence[PolicyRule],
    engine_kind: str = REGEX_ENGINE,
    opa_policy_digest: Optional[str] = None,
) -> bytes:
    """Canonical bytes for the policy set a given engine actually consults.

    The regex engine's bytes are exactly ``canonical_policy_bytes``, so every
    citation emitted before engine-aware citation existed still recomputes to
    the same digest. A non-regex engine additionally covers its Rego pin,
    because the Rego rules are policy the decision consulted and a citation
    that omitted them would describe a narrower set than the one enforced.
    """
    if engine_kind == REGEX_ENGINE:
        return canonical_policy_bytes(tools, rules)
    payload = json.dumps(
        {
            "tools": sorted(tools),
            "engine": engine_kind,
            "rules": sorted(_rule_to_canonical(r) for r in rules),
            "opa_policy": opa_policy_digest,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return payload.encode("utf-8")


def engine_policy_digest(
    tools: Iterable[str],
    rules: Sequence[PolicyRule],
    engine_kind: str = REGEX_ENGINE,
    opa_policy_digest: Optional[str] = None,
) -> Optional[str]:
    """The digest enforcement may cite, or None when no honest citation exists.

    None is a real answer: if an engine consults a policy source that cannot be
    hashed (Rego rules living in an OPA server the process does not hold), there
    is no digest that covers what the decision read. Returning a digest over the
    smaller set would let a record claim a citation it did not have, which is
    the failure this module exists to prevent.
    """
    if engine_kind != REGEX_ENGINE and not opa_policy_digest:
        return None
    return hashlib.sha256(
        engine_citation_bytes(tools, rules, engine_kind, opa_policy_digest)
    ).hexdigest()


def empty_policy_digest() -> str:
    """Digest of the empty policy set — the fail-closed default state."""
    return hashlib.sha256(
        json.dumps(
            {"tools": [], "rules": []},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
