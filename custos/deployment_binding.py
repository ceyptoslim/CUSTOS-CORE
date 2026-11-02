"""Deployment binding: tie a checked-in path inventory to a running deployment.

An inventory can stay perfectly reviewable while the deployment changes around it.
This module produces the evidence that closes that gap for one direction: a record,
written at startup into the same audit chain as every decision, that states what this
process is, what it mediated, and what configuration produced it.

Three rules, each with a reason:

1. **No secrets, only fingerprints.** The proxy process holds the JWT secret and the
   database URL. A binding record is evidence, not a credential store, so a token is
   represented by the SHA-256 of its value and never by the value.
2. **Canonical form before hashing.** Key order must not change the digest, or two
   identical deployments produce different evidence and a reviewer learns to ignore it.
3. **The digest goes in the chain, the payload goes in a file.** The chain stores
   content hashes by design. A reviewer needs the payload to check the digest, so the
   payload is written next to the deployment and its digest is what the chain anchors.

What this cannot do is stated in the doc, not here in a footnote: a process that never
connects to the mediated surface leaves no startup record, so binding is not path-set
completeness. See docs/design/EXECUTION-PATH-INVENTORY.md.
"""
# Copyright (C) 2024-2026 FroLife Productions
# Licensed under the GNU Affero General Public License v3.0 (AGPL-3.0)
# See LICENSE file for details.

from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable, Optional

BINDING_RULE = "deployment_binding_startup"
BINDING_CLIENT_ID = "custos-binding"
BINDING_SCHEMA = 1


def credential_fingerprint(secret: Optional[str]) -> Optional[str]:
    """SHA-256 of a credential, never the credential itself."""
    if not secret:
        return None
    return "sha256:" + hashlib.sha256(secret.encode("utf-8")).hexdigest()


def tool_list_digest(names: Iterable[str]) -> str:
    """Stable digest of the tool names an upstream actually advertised."""
    ordered = sorted({str(n) for n in names})
    blob = json.dumps(ordered, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(blob).hexdigest()


def canonical_payload(**fields: Any) -> dict:
    """Drop empty values and fix an order, so a digest depends on content only."""
    payload = {k: v for k, v in fields.items() if v not in (None, "", [], {})}
    payload["binding_schema"] = BINDING_SCHEMA
    return json.loads(json.dumps(payload, sort_keys=True, ensure_ascii=False))


def payload_digest(payload: dict) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()


def build_payload(
    *,
    deployment_id: str,
    build_commit: Optional[str] = None,
    transport: Optional[str] = None,
    upstream_command: Optional[str] = None,
    upstream_endpoint: Optional[str] = None,
    tool_names: Optional[Iterable[str]] = None,
    credential: Optional[str] = None,
    config: Optional[dict] = None,
    entry_ids: Optional[Iterable[str]] = None,
) -> dict:
    """Assemble the binding payload for one running deployment.

    ``entry_ids`` are the inventory rows this process claims to implement, so a
    reviewer can diff the declaration against the inventory file rather than guess.
    """
    return canonical_payload(
        deployment_id=deployment_id,
        build_commit=build_commit,
        transport=transport,
        upstream_command=upstream_command,
        upstream_endpoint=upstream_endpoint,
        tool_list_digest=tool_list_digest(tool_names) if tool_names is not None else None,
        credential_fingerprint=credential_fingerprint(credential),
        config=config or None,
        entry_ids=sorted({str(e) for e in entry_ids}) if entry_ids else None,
    )


def record_binding(chain, tenant_id: str, payload: dict, *, trace_id: Optional[str] = None):
    """Append the binding to an audit chain. Returns the AuditRecord."""
    digest = payload_digest(payload)
    return chain.record(
        client_id=BINDING_CLIENT_ID,
        action="BINDING",
        reason="deployment binding written at startup",
        content=json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
        triggered_rule=BINDING_RULE,
        trace_id=trace_id,
        tenant_id=tenant_id,
    ), digest
