"""
A deployment cannot be described as horizontal while its state is process-local.

The failure this prevents: an operator runs three replicas against in-process
rate-limit counters and an in-memory audit chain. Every quota becomes three
times the configured limit, and each process accumulates its own hash chain, so
a verifier is handed whichever chain the load balancer routed them to and calls
it the chain. Nothing in the software reported a problem, because nothing had
been asked to compare the declared topology with the storage in hand.

The check refuses a declaration it cannot back. It cannot detect the real
replica count, and the tests below say so rather than implying otherwise.
"""
import pytest
from fastapi.testclient import TestClient

from custos.scaling import (
    REPLICA_ENV,
    STORE_ENV,
    ScalingConfigError,
    rate_limit_store,
    replica_count,
    validate_replica_configuration,
)


class TestDeclarationParsing:
    def test_unset_declaration_is_one_replica(self, monkeypatch):
        monkeypatch.delenv(REPLICA_ENV, raising=False)
        assert replica_count() == 1

    def test_non_integer_declaration_is_refused_not_defaulted(self, monkeypatch):
        monkeypatch.setenv(REPLICA_ENV, "three")
        with pytest.raises(ScalingConfigError, match=REPLICA_ENV):
            replica_count()

    def test_zero_replicas_is_refused(self, monkeypatch):
        monkeypatch.setenv(REPLICA_ENV, "0")
        with pytest.raises(ScalingConfigError, match="at least 1"):
            replica_count()

    def test_store_defaults_to_process(self, monkeypatch):
        monkeypatch.delenv(STORE_ENV, raising=False)
        assert rate_limit_store() == "process"

    def test_unknown_store_is_refused(self, monkeypatch):
        monkeypatch.setenv(STORE_ENV, "redis")
        with pytest.raises(ScalingConfigError, match=STORE_ENV):
            rate_limit_store()


class TestTopologyRefusal:
    def test_single_replica_passes_with_shared_state_enforced(self, monkeypatch):
        monkeypatch.delenv(REPLICA_ENV, raising=False)
        monkeypatch.delenv(STORE_ENV, raising=False)
        summary = validate_replica_configuration("postgresql")
        assert summary["replica_count"] == 1
        assert summary["shared_state_enforced"] is True

    def test_multiple_replicas_on_process_state_is_refused(self, monkeypatch):
        monkeypatch.setenv(REPLICA_ENV, "3")
        with pytest.raises(ScalingConfigError, match="per process"):
            validate_replica_configuration("postgresql")

    def test_multiple_replicas_on_memory_audit_chain_is_refused(self, monkeypatch):
        monkeypatch.setenv(REPLICA_ENV, "2")
        monkeypatch.delenv(STORE_ENV, raising=False)
        with pytest.raises(ScalingConfigError, match="audit chain|chains"):
            validate_replica_configuration("memory")

    def test_external_store_declaration_is_refused_when_unimplemented(self, monkeypatch):
        # The escape hatch must not be a silent downgrade: declaring a shared
        # store this build does not contain is a claim the code cannot keep.
        monkeypatch.setenv(STORE_ENV, "external")
        with pytest.raises(ScalingConfigError, match="no shared rate-limit store"):
            validate_replica_configuration("postgresql")

    def test_refusal_names_the_conflict_rather_than_warning(self, monkeypatch):
        monkeypatch.setenv(REPLICA_ENV, "2")
        with pytest.raises(ScalingConfigError) as excinfo:
            validate_replica_configuration("postgresql")
        message = str(excinfo.value)
        assert REPLICA_ENV in message and STORE_ENV in message


class TestStartupWiring:
    def test_app_refuses_to_start_when_topology_exceeds_storage(self, monkeypatch):
        import main as app_module
        monkeypatch.setenv(REPLICA_ENV, "2")
        monkeypatch.delenv(STORE_ENV, raising=False)
        monkeypatch.delenv("CUSTOS_ENV", raising=False)
        with pytest.raises(ScalingConfigError):
            with TestClient(app_module.app):
                pass

    def test_app_starts_when_the_declaration_is_backable(self, monkeypatch):
        import main as app_module
        monkeypatch.setenv(REPLICA_ENV, "1")
        monkeypatch.delenv(STORE_ENV, raising=False)
        with TestClient(app_module.app) as client:
            assert client.get("/health").status_code == 200
