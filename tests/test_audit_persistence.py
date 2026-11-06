"""The served path reaches a durable, per-tenant audit store, and refuses without one.

Item 1's precondition. Before this wiring, ``TenantManager`` built every
tenant's chain with a bare ``AuditChain()``, so no configuration made the API's
records durable: the SQLite and PostgreSQL backends existed and were tested, and
nothing in the request path could reach either. A restore drill run against the
library would therefore have demonstrated the library.

Three things are checked here, and they are separate claims:

* the environment selects the store, and the store is scoped to one tenant;
* production refuses an ephemeral store, with a distinct reason when a store is
  configured but the chain was built without it;
* records written through the manager are readable by a later process, which is
  what "survives a restart" means and what a restart drill will exercise end to
  end over HTTP.
"""

import os
import sqlite3

import pytest

from custos.audit import AuditChain
from custos.audit_persistence import (
    AuditPersistenceRefused,
    audit_store_source,
    is_durable,
    require_durable_audit,
)
from custos.tenant import DEFAULT_QUOTA, TenantConfig, TenantManager


class TestEnvironmentSelectsTheStore:
    def test_without_a_store_the_chain_is_in_memory_and_says_so(self, monkeypatch):
        monkeypatch.delenv("AUDIT_DB_PATH", raising=False)
        monkeypatch.delenv("DATABASE_URL", raising=False)
        chain = AuditChain(tenant_id="acme")
        assert chain.backend_type == "InMemoryBackend"
        assert is_durable(chain.backend_type) is False

    def test_audit_db_path_makes_the_chain_durable(self, monkeypatch, tmp_path):
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.setenv("AUDIT_DB_PATH", str(tmp_path / "audit.sqlite"))
        chain = AuditChain(tenant_id="acme")
        assert chain.backend_type == "SQLiteBackend"
        assert is_durable(chain.backend_type) is True
        assert audit_store_source() == "AUDIT_DB_PATH"

    def test_a_tenant_manager_builds_scoped_durable_chains(self, monkeypatch, tmp_path):
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.setenv("AUDIT_DB_PATH", str(tmp_path / "audit.sqlite"))
        manager = TenantManager()
        acme = manager.register("acme", TenantConfig(tenant_id="acme", quota=DEFAULT_QUOTA))

        assert acme.audit_chain.backend_type == "SQLiteBackend"
        assert acme.audit_chain._tenant_id == "acme", (
            "the served path must build the chain already scoped, or every "
            "tenant writes into one shared scope"
        )

    def test_default_tenant_is_also_scoped(self, monkeypatch, tmp_path):
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.setenv("AUDIT_DB_PATH", str(tmp_path / "audit.sqlite"))
        manager = TenantManager()
        assert manager.get("default").audit_chain._tenant_id == "default"


class TestProductionRefusesAnEphemeralStore:
    def test_production_on_in_memory_is_refused_with_its_own_reason(self, monkeypatch):
        monkeypatch.setenv("CUSTOS_ENV", "production")
        monkeypatch.delenv("AUDIT_DB_PATH", raising=False)
        monkeypatch.delenv("DATABASE_URL", raising=False)
        with pytest.raises(AuditPersistenceRefused, match="keeps no records"):
            require_durable_audit("InMemoryBackend")

    def test_development_on_in_memory_is_allowed_and_named(self, monkeypatch):
        monkeypatch.delenv("AUDIT_DB_PATH", raising=False)
        monkeypatch.delenv("DATABASE_URL", raising=False)
        summary = require_durable_audit("InMemoryBackend", env="development")
        assert summary["audit_durable"] is False
        assert "do not survive a restart" in summary["audit_durability_note"]

    def test_a_configured_store_that_is_not_in_force_gets_a_different_reason(
        self, monkeypatch, tmp_path
    ):
        """The operator set the variable; telling them to set it is useless."""
        monkeypatch.setenv("CUSTOS_ENV", "production")
        monkeypatch.setenv("AUDIT_DB_PATH", str(tmp_path / "audit.sqlite"))
        with pytest.raises(AuditPersistenceRefused) as excinfo:
            require_durable_audit("InMemoryBackend")
        message = str(excinfo.value)
        assert "AUDIT_DB_PATH is set" in message
        assert "before import" in message
        assert "keeps no records" not in message

    def test_production_on_a_durable_store_is_allowed(self, monkeypatch, tmp_path):
        monkeypatch.setenv("CUSTOS_ENV", "production")
        monkeypatch.setenv("AUDIT_DB_PATH", str(tmp_path / "audit.sqlite"))
        summary = require_durable_audit("SQLiteBackend")
        assert summary["audit_durable"] is True
        assert summary["audit_store_source"] == "AUDIT_DB_PATH"

    def test_production_on_postgres_is_allowed(self, monkeypatch):
        monkeypatch.setenv("CUSTOS_ENV", "production")
        monkeypatch.setenv("DATABASE_URL", "postgresql://example/db")
        summary = require_durable_audit("PostgreSQLBackend")
        assert summary["audit_durable"] is True
        assert summary["audit_store_source"] == "DATABASE_URL"


class TestRecordsSurviveTheProcess:
    def test_a_record_written_through_the_manager_is_read_by_a_later_process(
        self, monkeypatch, tmp_path
    ):
        """Restart survival at the level the wiring reaches, without HTTP.

        The end-to-end version over /v1/evaluate belongs to the drill; this
        asserts the property the drill will rely on.
        """
        db = str(tmp_path / "audit.sqlite")
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.setenv("AUDIT_DB_PATH", db)

        first = TenantManager()
        ctx = first.get("default")
        ctx.audit_chain.record(
            client_id="alice", action="deny", reason="policy", content="payload"
        )
        assert os.path.exists(db)

        # A new manager stands in for a restarted process.
        second = TenantManager()
        reloaded = second.get("default").audit_chain
        assert len(reloaded._records) == 1
        assert reloaded.verify() == (True, "OK")
        assert reloaded._records[0].tenant_id == "default", (
            "records written by a scoped chain carry that chain's tenant; the "
            "served path never passes tenant_id, so without the default this "
            "would be NULL and every tenant would share one scope"
        )

    def test_two_tenants_sharing_one_file_stay_separate(self, monkeypatch, tmp_path):
        db = str(tmp_path / "audit.sqlite")
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.setenv("AUDIT_DB_PATH", db)

        manager = TenantManager()
        acme = manager.register("acme", TenantConfig(tenant_id="acme", quota=DEFAULT_QUOTA))
        beta = manager.register("beta", TenantConfig(tenant_id="beta", quota=DEFAULT_QUOTA))
        acme.audit_chain.record(client_id="a", action="deny", reason="r", content="c")
        beta.audit_chain.record(client_id="b", action="allow", reason="r", content="c")

        acme_reloaded = AuditChain(db_path=db, tenant_id="acme", _backend=None)
        beta_reloaded = AuditChain(db_path=db, tenant_id="beta")
        assert [r.client_id for r in acme_reloaded._records] == ["a"]
        assert [r.client_id for r in beta_reloaded._records] == ["b"]
        assert acme_reloaded.verify() == (True, "OK")
        assert beta_reloaded.verify() == (True, "OK")

    def test_the_store_holds_no_second_scope_for_these_records(
        self, monkeypatch, tmp_path
    ):
        db = str(tmp_path / "audit.sqlite")
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.setenv("AUDIT_DB_PATH", db)
        manager = TenantManager()
        manager.get("default").audit_chain.record(
            client_id="alice", action="deny", reason="r", content="c"
        )
        with sqlite3.connect(db) as conn:
            scopes = [r[0] for r in conn.execute("SELECT tenant_id FROM audit_records")]
        assert scopes == ["default"]


class TestTheChainRefusesAForeignTenant:
    def test_a_scoped_chain_fills_its_own_tenant(self, monkeypatch):
        monkeypatch.delenv("AUDIT_DB_PATH", raising=False)
        monkeypatch.delenv("DATABASE_URL", raising=False)
        chain = AuditChain(tenant_id="acme")
        record = chain.record(client_id="a", action="deny", reason="r", content="c")
        assert record.tenant_id == "acme"

    def test_a_scoped_chain_refuses_another_tenants_record(self, monkeypatch):
        monkeypatch.delenv("AUDIT_DB_PATH", raising=False)
        monkeypatch.delenv("DATABASE_URL", raising=False)
        chain = AuditChain(tenant_id="acme")
        with pytest.raises(ValueError, match="scoped to tenant 'acme'"):
            chain.record(
                client_id="b", action="deny", reason="r", content="c", tenant_id="beta"
            )
        assert chain._records == [], "a refused record must not be appended"

    def test_an_unscoped_chain_still_accepts_an_explicit_tenant(self, monkeypatch):
        """The library path stays open; only the served path is scoped."""
        monkeypatch.delenv("AUDIT_DB_PATH", raising=False)
        monkeypatch.delenv("DATABASE_URL", raising=False)
        chain = AuditChain()
        record = chain.record(
            client_id="a", action="deny", reason="r", content="c", tenant_id="acme"
        )
        assert record.tenant_id == "acme"


class TestTheServedPathInProduction:
    """The end-to-end shape a restart drill will use, asserted here first.

    Fixing the wiring exposed a second defect: production requires a bound
    record, and /v1/evaluate passed a trace_id but never a policy digest, so
    every production request to that endpoint failed with "the preimage would
    carry an unbound record" and returned 500. Verified on main before this
    change, so it was not introduced here.
    """

    def _start(self, monkeypatch, tmp_path):
        import main as app_module
        from fastapi.testclient import TestClient

        monkeypatch.setenv("CUSTOS_ENV", "production")
        monkeypatch.setenv("CUSTOS_JWT_SECRET", "a-real-unique-production-secret-32bytes")
        monkeypatch.delenv("DATABASE_URL", raising=False)
        db = str(tmp_path / "audit.sqlite")
        monkeypatch.setenv("AUDIT_DB_PATH", db)
        app_module.tenant_manager.register(
            "default", TenantConfig(tenant_id="default", quota=DEFAULT_QUOTA)
        )
        return app_module, TestClient(app_module.app), db

    def test_evaluate_writes_a_cited_record_and_returns_200(self, monkeypatch, tmp_path):
        app_module, client, db = self._start(monkeypatch, tmp_path)
        with client:
            resp = client.post("/v1/evaluate", json={"client_id": "pilot", "content": "hi"})
            assert resp.status_code == 200, resp.text
            assert resp.json()["action"] in ("allow", "deny", "log", "audit")
            info = client.get("/v1/info").json()
            assert info["audit_backend"] == "SQLiteBackend"
            assert info["audit_durable"] is True

        chain = AuditChain(db_path=db, tenant_id="default")
        assert len(chain._records) == 1
        record = chain._records[0]
        assert record.tenant_id == "default"
        assert record.policy_digest, "a production record must cite the policy it consulted"
        assert record.trace_id
        assert chain.verify() == (True, "OK")

    def test_a_restarted_process_reads_what_the_served_path_wrote(
        self, monkeypatch, tmp_path
    ):
        app_module, client, db = self._start(monkeypatch, tmp_path)
        with client:
            for content in ("first", "second"):
                assert client.post(
                    "/v1/evaluate", json={"client_id": "pilot", "content": content}
                ).status_code == 200

        reloaded = AuditChain(db_path=db, tenant_id="default")
        assert len(reloaded._records) == 2
        assert reloaded.verify() == (True, "OK")
        assert reloaded._records[0].previous_hash == AuditChain.GENESIS_HASH
        assert reloaded._records[1].previous_hash == reloaded._records[0].record_hash
