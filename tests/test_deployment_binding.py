"""Deployment binding: evidence that does not leak what it is evidence about."""
import json
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from custos.deployment_binding import (  # noqa: E402
    BINDING_RULE,
    build_payload,
    canonical_payload,
    credential_fingerprint,
    payload_digest,
    record_binding,
    tool_list_digest,
)


def test_credential_is_fingerprinted_never_embedded():
    token = "super-secret-jwt-value"
    fp = credential_fingerprint(token)
    assert fp.startswith("sha256:")
    assert token not in fp
    payload = build_payload(deployment_id="d1", credential=token)
    assert token not in json.dumps(payload)


def test_digest_is_order_independent():
    a = build_payload(deployment_id="d", build_commit="abc1234", transport="stdio")
    b = build_payload(transport="stdio", build_commit="abc1234", deployment_id="d")
    assert payload_digest(a) == payload_digest(b)


def test_digest_changes_when_the_deployment_changes():
    base = build_payload(deployment_id="d", build_commit="abc1234")
    moved = build_payload(deployment_id="d", build_commit="def5678")
    assert payload_digest(base) != payload_digest(moved)


def test_tool_list_digest_ignores_order_and_duplicates():
    assert tool_list_digest(["b", "a", "b"]) == tool_list_digest(["a", "b"])
    assert tool_list_digest(["a"]) != tool_list_digest(["a", "b"])


def test_empty_fields_are_dropped_so_absent_equals_unset():
    payload = canonical_payload(deployment_id="d", upstream_command=None, entry_ids=[])
    assert "upstream_command" not in payload
    assert "entry_ids" not in payload
    assert payload["binding_schema"] == 1


def test_entry_ids_are_sorted_for_stable_output():
    payload = build_payload(deployment_id="d", entry_ids=["P3", "P1", "P2", "P1"])
    assert payload["entry_ids"] == ["P1", "P2", "P3"]


def test_record_lands_in_the_chain_with_the_binding_rule():
    from custos.audit import AuditChain

    chain = AuditChain()
    payload = build_payload(deployment_id="d", build_commit="abc1234", entry_ids=["P1"])
    record, digest = record_binding(chain, "tenant-a", payload, trace_id=uuid.uuid4().hex)

    assert record.triggered_rule == BINDING_RULE
    assert record.trace_id
    assert digest.startswith("sha256:")
    assert len(chain._records) == 1
    ok, errors = chain.verify()
    assert ok, errors


def test_two_deployments_produce_distinguishable_binding_records():
    from custos.audit import AuditChain

    chain = AuditChain()
    a, da = record_binding(chain, "t", build_payload(deployment_id="a", build_commit="1111111"))
    b, db = record_binding(chain, "t", build_payload(deployment_id="b", build_commit="1111111"))
    assert da != db
    assert a.content_hash != b.content_hash
