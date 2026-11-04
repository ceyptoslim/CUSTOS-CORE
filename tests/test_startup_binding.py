"""Startup binding: opt-in, fail-closed, and never a claim without a record.

Rule 4 of the module says an implemented mechanism is not an established binding.
These tests hold the wiring to that rule from both sides: a deployment that does
not ask for a binding gets none and says so, and a deployment that asks for one
either gets a record or refuses to start.
"""
import hashlib
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from custos.audit import AuditChain  # noqa: E402
from custos.deployment_binding import (  # noqa: E402
    BINDING_RULE,
    STARTUP_ENV_FLAG,
    BindingError,
    establish,
    payload_digest,
    payload_from_env,
)

def chain_records(chain):
    """The chain's own record list, read through one place for the whole file."""
    return chain._records  # noqa: SLF001 - tests observe storage directly


ENABLED = {
    STARTUP_ENV_FLAG: "1",
    "CUSTOS_DEPLOYMENT_ID": "ref-deployment",
    "CUSTOS_BUILD_COMMIT": "abc1234",
    "CUSTOS_TRANSPORT": "stdio",
    "CUSTOS_BINDING_ENTRIES": "P1,P4",
}


class FailingBackend:
    """A backend whose every save fails, so the record never reaches storage."""

    backend_type = "failing"

    def save(self, record):  # noqa: D401 - test double
        raise IOError("storage unavailable")

    def load_all(self):
        return []


def test_binding_is_off_unless_the_deployment_asks_for_it():
    assert payload_from_env({}) is None
    assert payload_from_env({"CUSTOS_DEPLOYMENT_ID": "ignored-without-flag"}) is None


def test_enabled_without_an_identity_is_refused_not_guessed():
    with pytest.raises(BindingError, match="CUSTOS_DEPLOYMENT_ID"):
        payload_from_env({STARTUP_ENV_FLAG: "1"})


def test_enabled_with_a_malformed_descriptor_list_is_refused():
    with pytest.raises(BindingError, match="CUSTOS_TOOL_DESCRIPTORS"):
        payload_from_env({**ENABLED, "CUSTOS_TOOL_DESCRIPTORS": "{not json"})


def test_establish_writes_exactly_one_record_carrying_the_payload_digest():
    chain = AuditChain()
    summary = establish(chain, "default", env=ENABLED)

    rows = [r for r in chain_records(chain) if r.triggered_rule == BINDING_RULE]
    assert len(rows) == 1
    assert summary["deployment_id"] == "ref-deployment"
    assert summary["record_hash"] == rows[0].record_hash
    assert summary["binding_digest"] == payload_digest(summary["payload"])
    # The chain holds the hash of the payload, never the payload itself: rule 3.
    canonical = json.dumps(
        summary["payload"], sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    assert rows[0].content_hash == hashlib.sha256(canonical.encode()).hexdigest()
    assert chain.verify()[0] is True


def test_disabled_deployment_records_nothing():
    chain = AuditChain()
    assert establish(chain, "default", env={}) is None
    assert chain_records(chain) == []


def test_a_failed_write_refuses_the_start_rather_than_going_unbound():
    chain = AuditChain(_backend=FailingBackend())
    with pytest.raises(BindingError, match="could not be recorded"):
        establish(chain, "default", env=ENABLED)


def test_credentials_are_never_written_into_the_record():
    chain = AuditChain()
    secret = "live-connection-token"
    summary = establish(chain, "default", env={**ENABLED, "CUSTOS_BINDING_CREDENTIAL": secret})
    blob = json.dumps(summary["payload"])
    assert secret not in blob
    assert "sha256:" in blob


def test_the_record_states_which_inventory_rows_the_process_claims():
    chain = AuditChain()
    summary = establish(chain, "default", env=ENABLED)
    assert summary["payload"]["entry_ids"] == ["P1", "P4"]


def test_restarting_writes_a_second_record_with_the_same_digest():
    """Each start is an event, not a mutation: the digest identifies the deployment."""
    chain = AuditChain()
    first = establish(chain, "default", env=ENABLED)
    second = establish(chain, "default", env=ENABLED)
    assert len([r for r in chain_records(chain) if r.triggered_rule == BINDING_RULE]) == 2
    assert first["binding_digest"] == second["binding_digest"]
    assert first["record_hash"] != second["record_hash"]
    assert chain.verify()[0] is True


def test_changing_the_deployment_changes_the_digest():
    chain = AuditChain()
    base = establish(chain, "default", env=ENABLED)
    moved = establish(chain, "default", env={**ENABLED, "CUSTOS_BUILD_COMMIT": "def5678"})
    assert base["binding_digest"] != moved["binding_digest"]
