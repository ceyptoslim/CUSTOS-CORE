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
    config_digest,
    credential_binding,
    credential_fingerprint,
    payload_digest,
    record_binding,
    tool_descriptor_digest,
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
    assert payload["binding_schema"] == 2


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


def test_descriptor_digest_tracks_schema_not_just_names():
    """A tool that keeps its name and widens its schema changes what it can do."""
    narrow = [{"name": "update_record", "inputSchema": {"type": "object"}}]
    wide = [{"name": "update_record", "inputSchema": {"type": "object", "properties": {"bulk": {}}}}]
    assert tool_list_digest(["update_record"]) == tool_list_digest(["update_record"])
    assert tool_descriptor_digest(narrow) != tool_descriptor_digest(wide)


def test_descriptor_digest_covers_description_and_annotations():
    a = [{"name": "t", "description": "reads one record"}]
    b = [{"name": "t", "description": "reads one record and sends it to a third party"}]
    assert tool_descriptor_digest(a) != tool_descriptor_digest(b)


def test_descriptor_digest_ignores_order_and_spelling_of_the_schema_field():
    a = [{"name": "x", "inputSchema": {"type": "object"}}, {"name": "y"}]
    b = [{"name": "y"}, {"name": "x", "input_schema": {"type": "object"}}]
    assert tool_descriptor_digest(a) == tool_descriptor_digest(b)


def test_payload_carries_both_identity_digests_and_a_count():
    payload = build_payload(
        deployment_id="d",
        tool_descriptors=[{"name": "a", "inputSchema": {"type": "object"}}, {"name": "b"}],
    )
    assert payload["tool_count"] == 2
    assert payload["tool_list_digest"] and payload["tool_descriptor_digest"]


def test_config_digest_detects_a_rotated_secret_without_revealing_it():
    first = config_digest({"CUSTOS_JWT": "token-one", "timeout": 5})
    second = config_digest({"CUSTOS_JWT": "token-two", "timeout": 5})
    assert first["config_digest"] != second["config_digest"]
    assert first["secret_config_fields"] == ["CUSTOS_JWT"]
    blob = json.dumps(first) + json.dumps(second)
    assert "token-one" not in blob and "token-two" not in blob


def test_config_digest_is_stable_for_equal_config():
    assert config_digest({"a": 1, "b": 2})["config_digest"] == config_digest({"b": 2, "a": 1})["config_digest"]


def test_credential_binding_names_the_runtime_value_and_its_upstream():
    binding = credential_binding(
        runtime_secret="live-token",
        upstream="https://upstream.example/mcp",
        configured_secret="stale-config-token",
    )
    assert binding["source"] == "runtime-connection"
    assert binding["upstream"] == "https://upstream.example/mcp"
    assert binding["configured_matches"] is False
    assert "live-token" not in json.dumps(binding)


def test_credential_binding_reports_a_match_when_config_was_the_source():
    same = credential_binding(runtime_secret="t", upstream="u", configured_secret="t")
    unknown = credential_binding(runtime_secret="t", upstream="u")
    assert same["configured_matches"] is True
    assert unknown["configured_matches"] is None


def test_no_secret_survives_anywhere_in_the_payload():
    payload = build_payload(
        deployment_id="d",
        transport="stdio",
        upstream_command="python -m upstream --token live-token",
        runtime_credential="live-token",
        config={"DATABASE_URL": "postgres://user:live-token@db/app", "timeout": 3},
    )
    blob = json.dumps(payload)
    assert "live-token" not in blob
    assert payload["credential_binding"]["fingerprint"].startswith("sha256:")


def test_command_line_credentials_are_redacted_before_recording():
    payload = build_payload(
        deployment_id="d",
        upstream_command="python -m upstream --token abc123 --api-key=def456 --verbose",
    )
    blob = json.dumps(payload)
    assert "abc123" not in blob and "def456" not in blob
    assert "sha256:" in payload["upstream_command"]
    assert "--verbose" in payload["upstream_command"]


def test_endpoint_credentials_are_redacted_before_recording():
    payload = build_payload(
        deployment_id="d",
        upstream_endpoint="https://user:pass@upstream.example/mcp?token=abc123&limit=5",
    )
    blob = json.dumps(payload)
    assert "pass" not in blob and "abc123" not in blob
    assert "limit=5" in payload["upstream_endpoint"]


def test_redaction_is_stable_so_digests_compare_across_identical_deployments():
    a = build_payload(deployment_id="d", upstream_command="up --token abc123")
    b = build_payload(deployment_id="d", upstream_command="up --token abc123")
    assert payload_digest(a) == payload_digest(b)
