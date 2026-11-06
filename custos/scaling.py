"""
CUSTOS Replica Configuration
Copyright (C) 2024-2026 Tavares Heath Sr. (doing business as FroLife Productions)
Licensed under the GNU Affero General Public License v3.0 (AGPL-3.0)
See LICENSE file for details. Commercial license available upon request.

Rate-limit state and the audit chain both live in the process by default. That
makes a second replica a correctness problem rather than a capacity problem:
two processes hold two independent quota counters and two independent chains,
so the configured limit drifts upward with every replica added, and a reader
verifying "the" chain is verifying whichever one the load balancer sent them to.

This module does not fix that. It refuses to let a deployment be described as
horizontal while it is not, by making the replica count an explicit declaration
that startup checks against the storage the process actually has.

What the check does: reads the operator's declaration, compares it with the
storage this build provides, and refuses to start when the two disagree.

What it does not do: it cannot detect how many processes are really running.
An operator can start three containers and declare one, and this module will
never know. The declaration is recorded and contestable, which is the same
standing as the credential binding elsewhere in this codebase: the process
attests to what it was told, not to what is true on the wire.
"""

from __future__ import annotations

import os

REPLICA_ENV = "CUSTOS_REPLICA_COUNT"
STORE_ENV = "CUSTOS_RATE_LIMIT_STORE"

STORE_PROCESS = "process"
STORE_EXTERNAL = "external"
SUPPORTED_STORES = (STORE_PROCESS, STORE_EXTERNAL)

def is_memory_backend(audit_backend: str) -> bool:
    """True for any backend whose records live only in this process.

    Matched on a normalised name rather than a fixed list of spellings,
    because this check used to compare against "memory", "inmemory" and
    "in-memory" while the backend actually reports "InMemoryBackend". The
    audit-chain conflict could therefore never fire, and its test passed
    because the test typed one of the spellings the check expected. A guard
    that reads a string no caller produces is a guard that cannot fail.
    """
    normalized = "".join(
        ch for ch in (audit_backend or "").lower() if ch.isalnum()
    )
    return "memory" in normalized


class ScalingConfigError(RuntimeError):
    """Refusal to start: the declared topology exceeds what the process provides."""


def replica_count() -> int:
    """Return the operator's declared replica count, or 1 when unset.

    A declaration that cannot be parsed is refused rather than defaulted. A
    silently defaulted topology is how a deployment ends up horizontal while
    every log line says single.
    """
    raw = (os.getenv(REPLICA_ENV) or "").strip()
    if not raw:
        return 1
    try:
        count = int(raw)
    except ValueError:
        raise ScalingConfigError(
            f"{REPLICA_ENV}={raw!r} is not an integer. Declare the replica count "
            "as a positive integer, or leave it unset for a single replica."
        ) from None
    if count < 1:
        raise ScalingConfigError(
            f"{REPLICA_ENV}={raw!r} must be at least 1. A deployment with no "
            "replicas is a deployment that is not running."
        )
    return count


def rate_limit_store() -> str:
    """Return the declared rate-limit store, defaulting to in-process."""
    raw = (os.getenv(STORE_ENV) or "").strip().lower()
    if not raw:
        return STORE_PROCESS
    if raw not in SUPPORTED_STORES:
        raise ScalingConfigError(
            f"{STORE_ENV}={raw!r} is not a recognised store. Supported values are "
            f"{', '.join(SUPPORTED_STORES)}; leave it unset for {STORE_PROCESS}."
        )
    return raw


def validate_replica_configuration(audit_backend: str) -> dict:
    """Refuse to start when the declared topology exceeds the actual storage.

    Raises ScalingConfigError with the specific conflict rather than a general
    warning, because the operator needs to know which of the two pieces of
    state made the declaration untrue.
    """
    count = replica_count()
    store = rate_limit_store()
    memory_audit = is_memory_backend(audit_backend)

    conflicts = []

    if store == STORE_EXTERNAL:
        # Selecting a store this build does not contain would be a claim the
        # code cannot keep, so it is refused instead of silently degraded to
        # process-local state.
        conflicts.append(
            f"{STORE_ENV}={STORE_EXTERNAL} is declared but this build has no "
            "shared rate-limit store implementation, so running in-process "
            "state under that declaration would report a topology the software "
            "does not provide"
        )

    if count > 1 and store == STORE_PROCESS:
        conflicts.append(
            f"{REPLICA_ENV}={count} with {STORE_ENV}={STORE_PROCESS}: rate-limit "
            "state is per process, so each replica carries its own counters and "
            f"the configured quota multiplies by {count}"
        )

    if count > 1 and memory_audit:
        conflicts.append(
            f"{REPLICA_ENV}={count} with audit backend {audit_backend!r}: each "
            f"process would hold its own chain, so {count} replicas produce "
            f"{count} chains and a verifier is only shown the one it reached"
        )

    if conflicts:
        raise ScalingConfigError(
            "declared topology cannot be backed by this build: "
            + "; ".join(conflicts)
            + ". See docs/design/single-replica-constraint.md for the scaling path."
        )

    summary = {
        "replica_count": count,
        "rate_limit_store": store,
        "audit_backend": audit_backend,
        "shared_state_enforced": count == 1,
        "audit_durability": "ephemeral" if memory_audit else "durable",
    }
    if memory_audit:
        # Naming the backend is not the same as naming the property it lacks:
        # an operator reading "InMemoryBackend" has to know the codebase to
        # know that nothing survives a restart and that the fork constraint,
        # which is a database constraint, cannot apply.
        summary["audit_durability_note"] = (
            "records do not survive a restart, and the previous_hash "
            "constraint that prevents a forked chain does not apply because "
            "no store is shared"
        )
    return summary
