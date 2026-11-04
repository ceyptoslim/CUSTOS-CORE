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


def test_strict_bound_mode_lets_the_binding_cite_the_policy_in_force(monkeypatch):
    """CUSTOS_AUDIT_REQUIRE_BOUND must not make a bound deployment unbootable.

    The binding record cites the policy enforcement would cite, not a digest of
    itself: a fabricated citation would satisfy the guard while defeating it.
    """
    monkeypatch.setenv("CUSTOS_AUDIT_REQUIRE_BOUND", "1")
    chain = AuditChain()
    summary = establish(chain, env=ENABLED, policy_digest="sha256:in-force")
    rows = [r for r in chain_records(chain) if r.triggered_rule == BINDING_RULE]
    assert len(rows) == 1
    assert rows[0].policy_digest == "sha256:in-force"
    assert rows[0].trace_id == summary["trace_id"]
    assert summary["policy_digest"] == "sha256:in-force"


def test_strict_bound_mode_refuses_rather_than_fabricating_a_citation(monkeypatch):
    """No policy digest available = no binding record = no start. Not a guess."""
    monkeypatch.setenv("CUSTOS_AUDIT_REQUIRE_BOUND", "1")
    chain = AuditChain()
    with pytest.raises(BindingError, match="could not be recorded"):
        establish(chain, env=ENABLED)
    assert [r for r in chain_records(chain) if r.triggered_rule == BINDING_RULE] == []


def test_startup_refuses_when_the_binding_cannot_be_written(monkeypatch):
    """The refusal is the whole claim, so it needs a test at the app boundary.

    establish() raising is covered above; what was not covered is whether the
    lifespan lets that failure stop the process. A try/except that logs and
    continues would keep every unit test green while shipping the exact failure
    the binding exists to prevent.
    """
    import main
    from fastapi.testclient import TestClient

    monkeypatch.setenv(STARTUP_ENV_FLAG, "1")
    monkeypatch.setenv("CUSTOS_DEPLOYMENT_ID", "ref-refusal")

    def _write_fails(*_args, **_kwargs):
        raise BindingError("storage unavailable")

    monkeypatch.setattr(main, "establish_startup_binding", _write_fails)
    chain = main.tenant_manager.get("default").audit_chain
    before = len(chain_records(chain))
    with pytest.raises(BindingError):
        with TestClient(main.app):
            pass
    assert len(chain_records(chain)) == before, "a refused start must not leave a record"


def test_startup_writes_no_binding_when_the_flag_is_off(monkeypatch):
    """Off is the default, and off must mean nothing at all is written."""
    import main
    from fastapi.testclient import TestClient

    monkeypatch.delenv(STARTUP_ENV_FLAG, raising=False)
    chain = main.tenant_manager.get("default").audit_chain
    before = len(chain_records(chain))
    with TestClient(main.app) as client:
        assert client.get("/v1/info").json()["deployment_binding"] == {
            "enabled": False,
            "established": False,
        }
    assert len(chain_records(chain)) == before
