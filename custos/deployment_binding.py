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
4. **Implemented is not established.** This module records a binding when a deployment
   calls it. It is not called from startup, so no binding exists for any process until
   one wires it. A reviewer must not be able to infer a record from the module's
   presence, and the inventory says so in the same words.

What this cannot do is stated in the doc, not here in a footnote: a process that never
connects to the mediated surface leaves no startup record, so binding is not path-set
completeness. See docs/design/EXECUTION-PATH-INVENTORY.md.
"""
# Copyright (C) 2024-2026 FroLife Productions
# Licensed under the GNU Affero General Public License v3.0 (AGPL-3.0)
# See LICENSE file for details.

from __future__ import annotations

import hashlib
import os
import json
import re
from typing import Any, Iterable, Optional

BINDING_RULE = "deployment_binding_startup"
BINDING_CLIENT_ID = "custos-binding"
BINDING_SCHEMA = 2


def credential_fingerprint(secret: Optional[str]) -> Optional[str]:
    """SHA-256 of a credential, never the credential itself."""
    if not secret:
        return None
    return "sha256:" + hashlib.sha256(secret.encode("utf-8")).hexdigest()


def tool_list_digest(names: Iterable[str]) -> str:
    """Stable digest of the tool names an upstream actually advertised.

    Names alone say which tools exist, not what they can be asked to do. Kept for
    comparability with earlier records; use :func:`tool_descriptor_digest` for evidence.
    """
    ordered = sorted({str(n) for n in names})
    blob = json.dumps(ordered, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(blob).hexdigest()


def _descriptor(entry: Any) -> dict:
    """Normalise a tool descriptor so the digest covers behaviour, not spelling."""
    if isinstance(entry, str):
        return {"name": entry}
    if not isinstance(entry, dict):
        return {"name": str(entry)}
    out = dict(entry)
    # Accept the two spellings the MCP spec and SDKs use for the same field.
    schema = out.pop("inputSchema", None)
    if schema is None:
        schema = out.pop("input_schema", None)
    if schema is not None:
        out["inputSchema"] = schema
    out.setdefault("name", "")
    return out


def tool_descriptor_digest(tools: Iterable[Any]) -> str:
    """Digest over tool metadata that decides what the upstream can be asked to do.

    Names are not enough: a tool whose input schema widens from one record to a bulk
    update keeps its name and changes its blast radius. The whole descriptor is
    canonicalised and sorted by name, so a schema, description or annotation change
    moves the digest and a reordering of the same tools does not.
    """
    normalised = sorted((_descriptor(t) for t in tools), key=lambda d: str(d.get("name", "")))
    blob = json.dumps(normalised, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()


_SECRET_HINTS = (
    "secret", "token", "password", "passwd", "credential", "jwt",
    "api_key", "apikey", "database_url", "dsn", "private_key",
)


def _looks_secret(name: str) -> bool:
    lowered = str(name).lower()
    return any(hint in lowered for hint in _SECRET_HINTS)


def _redact_secrets(value: Any, path: str, found: list) -> Any:
    """Replace secret-looking values with fingerprints, remembering where they were."""
    if isinstance(value, dict):
        return {k: _redact_secrets(v, f"{path}.{k}" if path else str(k), found) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact_secrets(v, f"{path}[{i}]", found) for i, v in enumerate(value)]
    if path and _looks_secret(path.split(".")[-1].split("[")[0]):
        found.append(path)
        return credential_fingerprint(str(value))
    return value


def config_digest(config: Optional[dict]) -> dict:
    """Digest the configuration without publishing its secrets.

    A changed secret has to be detectable, and it must not be readable in the record.
    Secret-looking values are replaced by their fingerprints before hashing, so the
    digest moves when a credential rotates and the record still carries no credential.
    """
    if not config:
        return {}
    found: list = []
    redacted = _redact_secrets(config, "", found)
    blob = json.dumps(redacted, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return {
        "config_digest": "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest(),
        "secret_config_fields": sorted(found),
        "config_keys": sorted(str(k) for k in config.keys()),
    }


_SECRET_FLAG = re.compile(
    r"^(--?[A-Za-z0-9_-]*(?:secret|token|key|password|passwd|credential|auth)[A-Za-z0-9_-]*)"
    r"(?:=(.*))?$",
    re.IGNORECASE,
)


def _redact_url_userinfo(token: str) -> str:
    if "://" not in token or "@" not in token:
        return token
    scheme, _, rest = token.partition("://")
    userinfo, _, host = rest.rpartition("@")
    return f"{scheme}://{credential_fingerprint(userinfo)}@{host}"


def redact_command(command: Optional[str]) -> Optional[str]:
    """Fingerprint credentials passed as flags in an upstream command line.

    A stdio upstream is a process, and its argv frequently carries a token
    (``--token``, ``--api-key=…``). Binding records the command, so the command has to
    be redacted first or the record becomes a credential store.

    Limit, stated because it matters: this covers secret-looking flags and URL
    userinfo, not arbitrary secrets embedded in free text (a header blob, a sentence).
    A deployment that must pass credentials in argv should pass them by environment
    variable or mounted file instead, and this function is a backstop rather than a
    licence to put secrets on a command line.
    """
    if not command:
        return command
    tokens = command.split()
    out: list = []
    expect_value = False
    for token in tokens:
        if expect_value:
            out.append(credential_fingerprint(token) or "")
            expect_value = False
            continue
        match = _SECRET_FLAG.match(token)
        if match:
            flag, value = match.group(1), match.group(2)
            if value is None:
                out.append(token)
                expect_value = True
            else:
                out.append(f"{flag}={credential_fingerprint(value)}")
            continue
        out.append(_redact_url_userinfo(token))
    if expect_value:
        out.append(credential_fingerprint("") or "")
    return " ".join(out)


def redact_endpoint(endpoint: Optional[str]) -> Optional[str]:
    """Redact URL userinfo and secret-looking query parameter values."""
    if not endpoint:
        return endpoint
    endpoint = _redact_url_userinfo(endpoint)
    base, sep, query = endpoint.partition("?")
    if not sep:
        return base
    params = []
    for pair in query.split("&"):
        name, eq, value = pair.partition("=")
        if eq and _looks_secret(name):
            params.append(f"{name}={credential_fingerprint(value)}")
        else:
            params.append(pair)
    return base + "?" + "&".join(params)


def credential_binding(
    *,
    runtime_secret: Optional[str],
    upstream: Optional[str],
    configured_secret: Optional[str] = None,
    source: str = "runtime-connection",
    scope: Optional[Iterable[str]] = None,
) -> Optional[dict]:
    """Which credential actually authenticated this connection to the upstream.

    A fingerprint taken from a static configuration file proves what was written down,
    not what was used: environment overrides, mounted secrets and runtime refresh all
    change the value after the file is read. This records the fingerprint of the value
    the connection presents, tagged with its source, bound to the upstream it reached,
    and notes whether a configured value matched it.
    """
    fingerprint = credential_fingerprint(runtime_secret)
    if fingerprint is None:
        return None
    configured = credential_fingerprint(configured_secret)
    binding = {
        "fingerprint": fingerprint,
        "source": source,
        # Explicit null rather than an absent key: "no configured value to compare"
        # and "no comparison performed" are different states and a reviewer needs both.
        "configured_matches": None if configured is None else configured == fingerprint,
    }
    if upstream:
        binding["upstream"] = upstream
    if scope:
        binding["scope"] = sorted({str(s) for s in scope})
    return binding


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
    tool_descriptors: Optional[Iterable[Any]] = None,
    credential: Optional[str] = None,
    runtime_credential: Optional[str] = None,
    configured_credential: Optional[str] = None,
    credential_scope: Optional[Iterable[str]] = None,
    config: Optional[dict] = None,
    entry_ids: Optional[Iterable[str]] = None,
) -> dict:
    """Assemble the binding payload for one running deployment.

    ``entry_ids`` are the inventory rows this process claims to implement, so a
    reviewer can diff the declaration against the inventory file rather than guess.
    """
    descriptors = list(tool_descriptors) if tool_descriptors is not None else None
    names = list(tool_names) if tool_names is not None else None
    if names is None and descriptors is not None:
        names = [(_descriptor(d).get("name") or "") for d in descriptors]

    payload = canonical_payload(
        deployment_id=deployment_id,
        build_commit=build_commit,
        transport=transport,
        upstream_command=redact_command(upstream_command),
        upstream_endpoint=redact_endpoint(upstream_endpoint),
        tool_list_digest=tool_list_digest(names) if names is not None else None,
        tool_descriptor_digest=tool_descriptor_digest(descriptors) if descriptors is not None else None,
        tool_count=len(names) if names is not None else None,
        credential_fingerprint=credential_fingerprint(credential),
        credential_binding=credential_binding(
            runtime_secret=runtime_credential,
            upstream=redact_endpoint(upstream_endpoint) or redact_command(upstream_command),
            configured_secret=configured_credential if configured_credential is not None else credential,
            scope=credential_scope,
        ),
        entry_ids=sorted({str(e) for e in entry_ids}) if entry_ids else None,
    )
    payload.update(config_digest(config))
    return canonical_payload(**payload)


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


# ---------------------------------------------------------------------------
# Startup binding — opt-in, and fail-closed when opted into.
#
# Rule 4 above says an implemented mechanism is not an established binding.
# This is the wiring that closes that gap for deployments that ask for it,
# and it deliberately stays off by default: a reference deployment that does
# not set CUSTOS_DEPLOYMENT_BINDING still leaves no record, and the inventory
# continues to say so.
# ---------------------------------------------------------------------------

STARTUP_ENV_FLAG = "CUSTOS_DEPLOYMENT_BINDING"


class BindingError(RuntimeError):
    """Raised when a deployment asked for a binding and could not be given one."""


def _truthy(value: Optional[str]) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def payload_from_env(env: Optional[dict] = None) -> Optional[dict]:
    """Assemble the startup payload from the environment.

    Returns ``None`` when binding is not enabled. Raises :class:`BindingError`
    when it is enabled but the deployment cannot identify itself: an unbound
    start that logs a warning is worse than a refused start, because the
    deployment then runs while the inventory claims a mechanism is in place.
    """
    env = dict(os.environ if env is None else env)
    if not _truthy(env.get(STARTUP_ENV_FLAG)):
        return None

    deployment_id = (env.get("CUSTOS_DEPLOYMENT_ID") or "").strip()
    if not deployment_id:
        raise BindingError(
            f"{STARTUP_ENV_FLAG} is set but CUSTOS_DEPLOYMENT_ID is empty; "
            "a binding record without a deployment identity binds nothing"
        )

    descriptors: Optional[list] = None
    raw_descriptors = env.get("CUSTOS_TOOL_DESCRIPTORS")
    if raw_descriptors:
        try:
            descriptors = json.loads(raw_descriptors)
        except ValueError as exc:
            raise BindingError(f"CUSTOS_TOOL_DESCRIPTORS is not valid JSON: {exc}") from exc
        if not isinstance(descriptors, list):
            raise BindingError("CUSTOS_TOOL_DESCRIPTORS must be a JSON list of tool descriptors")

    config: Optional[dict] = None
    raw_config = env.get("CUSTOS_BINDING_CONFIG")
    if raw_config:
        try:
            config = json.loads(raw_config)
        except ValueError as exc:
            raise BindingError(f"CUSTOS_BINDING_CONFIG is not valid JSON: {exc}") from exc
        if not isinstance(config, dict):
            raise BindingError("CUSTOS_BINDING_CONFIG must be a JSON object")

    entries = env.get("CUSTOS_BINDING_ENTRIES") or ""
    entry_ids = [e.strip() for e in entries.split(",") if e.strip()] or None

    return build_payload(
        deployment_id=deployment_id,
        build_commit=(env.get("CUSTOS_BUILD_COMMIT") or env.get("GIT_SHA") or "").strip() or None,
        transport=(env.get("CUSTOS_TRANSPORT") or "").strip() or None,
        upstream_command=(env.get("CUSTOS_UPSTREAM_COMMAND") or "").strip() or None,
        upstream_endpoint=(env.get("CUSTOS_UPSTREAM_ENDPOINT") or "").strip() or None,
        tool_descriptors=descriptors,
        runtime_credential=(env.get("CUSTOS_BINDING_CREDENTIAL") or "").strip() or None,
        config=config,
        entry_ids=entry_ids,
    )


def establish(chain, tenant_id: str = "default", env: Optional[dict] = None) -> Optional[dict]:
    """Write the startup binding when enabled by ``CUSTOS_DEPLOYMENT_BINDING``.

    Returns a small summary suitable for an info endpoint, or ``None`` when the
    deployment did not ask to be bound. Any failure raises :class:`BindingError`:
    the caller is expected to refuse to start, so that "bound" is never claimed
    for a process that could not write its record.
    """
    payload = payload_from_env(env)
    if payload is None:
        return None
    try:
        record, digest = record_binding(chain, tenant_id, payload)
    except Exception as exc:  # noqa: BLE001 - any write failure is a refused start
        raise BindingError(f"deployment binding could not be recorded: {exc}") from exc
    return {
        "enabled": True,
        "payload": payload,
        "deployment_id": payload.get("deployment_id"),
        "binding_digest": digest,
        "record_hash": record.record_hash,
        "established_at": record.timestamp,
        "entry_ids": payload.get("entry_ids") or [],
    }
