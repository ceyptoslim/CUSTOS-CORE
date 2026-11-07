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


class TestTheCitationSurvivesAnyEngine:
    """The served path cites a decision without knowing which engine made it.

    The first version of this fix read ``ctx.policy_engine.rules_digest``
    directly. The regex engine has that property; the OPA and hybrid engines do
    not, so `/v1/evaluate` raised AttributeError under
    CUSTOS_POLICY_ENGINE=hybrid and the CI smoke test caught it. The action gate
    hit this same trap once before, which is why the shared helper reads through
    getattr instead of assuming the shape.
    """

    def test_the_regex_engine_cites(self):
        from custos.policy_citation import content_engine_digest
        from custos.policy_engine import PolicyEngine

        digest = content_engine_digest(PolicyEngine())
        assert isinstance(digest, str) and len(digest) == 64

    def test_a_hybrid_engine_without_a_rego_pin_refuses_to_cite(self):
        """None is the honest answer, not a failure to compute one.

        A hybrid engine consults Rego that lives in a server this process does
        not hold, so no digest covers what it read. Returning a digest over the
        local rules alone would cite a set narrower than the one consulted,
        which is what the citation module exists to prevent. The consequence is
        stated in the design doc: in production, a hybrid tenant needs
        CUSTOS_OPA_POLICY_DIGEST set or this endpoint cannot bind a record.
        """
        from custos.policy_citation import content_engine_digest

        class Hybridish:
            engine_kind = "hybrid"
            citation_rules = []

        assert content_engine_digest(Hybridish()) is None

    def test_a_hybrid_engine_with_a_rego_pin_cites(self):
        from custos.policy_citation import content_engine_digest

        class HybridPinned:
            engine_kind = "hybrid"
            citation_rules = []
            opa_policy_digest = "b" * 64

        assert isinstance(content_engine_digest(HybridPinned()), str)

    def test_an_engine_with_no_citation_attributes_does_not_raise(self):
        from custos.policy_citation import content_engine_digest

        assert isinstance(content_engine_digest(object()), str), (
            "an engine shaped like nothing in particular must still cite or "
            "return None, never raise while a decision is being recorded"
        )

    def test_a_rego_pin_changes_the_digest(self):
        from custos.policy_citation import content_engine_digest

        class Pinned:
            engine_kind = "opa"
            citation_rules = []
            opa_policy_digest = "a" * 64

        class Unpinned:
            engine_kind = "opa"
            citation_rules = []

        assert content_engine_digest(Pinned()) != content_engine_digest(Unpinned())


class TestTheDrillRecordStaysTrue:
    """The transcript is evidence, so its quotations must be the code's.

    A drill record that quotes a startup field the code no longer emits, or a
    refusal message that has since been reworded, is worse than no record: it
    reads as a measurement and is a memory. These cases bind the transcript to
    the strings it quotes, so a rename fails a test instead of ageing quietly.
    """

    DOC = "docs/restore-drills/2026-11-06-served-path-postgres.md"

    def _doc(self):
        import pathlib

        return pathlib.Path(self.DOC).read_text()

    def test_it_exists_and_names_both_commands_it_used(self):
        doc = self._doc()
        assert "pg_dump" in doc and "DATABASE_URL" in doc
        assert "verify:  (True, \"OK\")" in doc

    def test_every_startup_field_it_quotes_is_still_emitted(self):
        from custos.audit_persistence import require_durable_audit

        doc = self._doc()
        emitted = require_durable_audit("PostgreSQLBackend", env="production")
        for field in ("audit_backend", "audit_durable", "audit_store_source"):
            assert field in doc, f"the drill no longer quotes {field}"
            assert field in emitted, f"the code no longer emits {field}"

    def test_the_refusal_it_quotes_is_the_refusal_that_fires(self, monkeypatch):
        from custos.audit_persistence import AuditPersistenceRefused, require_durable_audit

        # No store configured, which is the branch the transcript records. With
        # either variable set the refusal takes the other branch, whose message
        # is deliberately different.
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.delenv("AUDIT_DB_PATH", raising=False)
        quoted = "A production process must not serve an audit trail it cannot keep."
        assert quoted in self._doc()
        try:
            require_durable_audit("InMemoryBackend", env="production")
        except AuditPersistenceRefused as exc:
            assert quoted in str(exc)
        else:
            raise AssertionError("the refusal did not fire, so the drill quotes nothing")


class TestInfoNamesTheStoreSource:
    """/v1/info is the surface a reader has, so it carries the source too.

    The startup log names which variable is in force. A reader who reaches the
    API and not the log was being told half of what the process knows, and
    "audit_backend: SQLiteBackend" does not say whether that came from
    AUDIT_DB_PATH or from a process that resolved it some other way.
    """

    def test_the_endpoint_reports_the_source_the_process_resolved(self, monkeypatch):
        import asyncio

        import main

        monkeypatch.setenv("AUDIT_DB_PATH", "/tmp/info-source-test.sqlite")
        monkeypatch.delenv("DATABASE_URL", raising=False)
        body = asyncio.run(main.info())
        assert body["audit_store_source"] == "AUDIT_DB_PATH"
        assert body["audit_backend"] == main.tenant_manager.get("default").audit_chain.backend_type

    def test_it_reports_none_rather_than_omitting_the_field(self, monkeypatch):
        import asyncio

        import main

        monkeypatch.delenv("AUDIT_DB_PATH", raising=False)
        monkeypatch.delenv("DATABASE_URL", raising=False)
        body = asyncio.run(main.info())
        assert "audit_store_source" in body
        assert body["audit_store_source"] == "none"


class TestTheRefusalPathIsBoundLikeTheDecisionPath:
    """A rate-limited refusal is a decision and must be recorded as one.

    Production requires bound evidence, and the refusal used to be written
    without a policy citation, so every request past a client's quota raised
    inside the refusal and returned 500 instead of 429. The caller was never
    told to wait, and the Retry-After header added for exactly that caller
    could not reach them. Found by the restore drill's write loop, which
    stopped at precisely the quota.
    """

    def test_the_refusal_returns_429_and_records_a_bound_record(self, monkeypatch):
        import time

        import jwt
        from fastapi.testclient import TestClient

        import main
        from custos.audit import bound_evidence_required

        # The same requirement production imposes, set directly: a production
        # app cannot boot on an in-memory chain (that refusal is tested
        # elsewhere), so binding the flag keeps this test on the refusal path
        # rather than on the startup path.
        monkeypatch.setenv("CUSTOS_AUDIT_REQUIRE_BOUND", "1")
        monkeypatch.delenv("CUSTOS_ENV", raising=False)
        assert bound_evidence_required() is True

        secret = "drill-secret-32-bytes-long-enough-here"
        monkeypatch.setenv("CUSTOS_JWT_SECRET", secret)
        token = jwt.encode({"sub": "quota-client", "exp": int(time.time()) + 600}, secret, algorithm="HS256")
        headers = {"Authorization": f"Bearer {token}"}

        chain = main.tenant_manager.get("default").audit_chain
        before = len(chain._records)

        with TestClient(main.app) as client:
            statuses = [
                client.post(
                    "/v1/evaluate",
                    json={"client_id": "quota-client", "content": f"probe {i}"},
                    headers=headers,
                ).status_code
                for i in range(80)
            ]

        assert 429 in statuses, "the quota never engaged, so nothing was tested"
        assert 500 not in statuses, "a refusal returned 500 instead of 429"
        refusals = [r for r in chain._records[before:] if r.action == "rate_limited"]
        assert refusals, "no refusal record was written"
        assert all(r.policy_digest for r in refusals), "a refusal was recorded unbound"
        assert chain.verify()[0] is True


class TestTheInjectionPhasesStayTiedToTheCode:
    """Phases 8 to 10 quote refusal messages and errnos, so bind them too.

    Same reason as the drill guard above. A transcript that names a failure mode
    whose message has since changed reads as a measurement and is a memory, and
    the three injections are the part of the record a reader is most likely to
    try to reproduce.
    """

    DOC = "docs/restore-drills/2026-11-06-served-path-postgres.md"

    def _doc(self):
        import pathlib

        return pathlib.Path(self.DOC).read_text()

    def test_all_three_injections_are_named_as_phases(self):
        doc = self._doc()
        assert "## Phase 8: the process is killed while writing" in doc
        assert "## Phase 9: the store fills mid-append" in doc
        assert "## Phase 10: two replicas, one store" in doc
        # the mechanisms, not just the headings
        assert "kill -9" in doc
        assert "ENOSPC" in doc
        assert "ChainForkError" in doc

    def test_the_fork_refusal_it_quotes_is_the_one_the_store_raises(self):
        from custos import audit as audit_module

        doc = self._doc()
        source = __import__("pathlib").Path(audit_module.__file__).read_text()
        sentence = "another writer extended this chain after this process loaded it"
        # the transcript quotes this sentence, so it has to still be the sentence
        # (the quote is wrapped in the document, so compare on collapsed space)
        assert sentence in " ".join(doc.split())
        # raised by both durable backends, so the quote is not bound to one
        assert source.count(sentence) >= 2, "one backend no longer raises this message"

    def test_the_full_store_phase_names_the_engine_it_was_measured_on(self):
        # The quoted sentence is SQLite's own message for SQLITE_FULL, and the
        # engine exposes no portable constant to assert it against (the module
        # level constants differ across Python versions, which is how the first
        # version of this guard failed on 3.10 while passing on 3.11 and 3.12).
        # What can be bound is that the phase says which engine produced it, so
        # a reader does not carry a PostgreSQL message home from a SQLite run.
        doc = self._doc()
        assert "database or disk is full" in doc
        phase9 = doc.split("## Phase 9")[1].split("## Phase 10")[0]
        assert "SQLite" in phase9
        assert "SQLite here rather than PostgreSQL" in phase9


class TestTheDrillDriversAreReExecutable:
    """The injections behind the drill are in the repository, not in a temporary
    directory.

    The transcript was checkable against its numbers and not against its code,
    which meant it could not be re-run by a reader and could not be checked
    against a later build. These guards bind the document to the drivers it now
    tells a reader to run, so deleting or renaming one fails here rather than
    leaving a document that instructs a reader to run something that is gone.
    """

    DRIVERS = (
        "writer_loop.py",
        "phase8_kill_mid_append.py",
        "phase9_disk_full.py",
        "phase10_two_writers.py",
        "phase10_worker.py",
        "phase11_export_backup.py",
        "enospc.c",
    )

    def _drills(self):
        import pathlib

        return pathlib.Path("scripts/drills")

    def _doc(self):
        import pathlib

        return pathlib.Path("docs/restore-drills/2026-11-06-served-path-postgres.md").read_text()

    def test_every_driver_exists_and_is_named_in_the_readme(self):
        readme = (self._drills() / "README.md").read_text()
        for name in self.DRIVERS:
            assert (self._drills() / name).exists(), f"{name} is missing from scripts/drills"
            assert name in readme, f"{name} is not named in the drills README"

    def test_the_document_points_at_the_committed_drivers(self):
        doc = self._doc()
        assert "scripts/drills/" in doc
        # the section that says so carries the re-run it claims
        section = doc.split("## The drivers are in the repository, and re-run")[1].split("## Defects")[0]
        assert "phase 8" in section and "phase 9" in section and "phase 10" in section
        assert "reported writes: 98" in section
        assert "RESULT audit backend: SQLiteBackend" in section
        assert "ChainForkError" in section

    def test_the_section_quotes_lines_the_scripts_actually_print(self):
        """A quoted line that no script emits is a restatement, not a record."""
        phase8 = (self._drills() / "phase8_kill_mid_append.py").read_text()
        phase9 = (self._drills() / "phase9_disk_full.py").read_text()
        phase10 = (self._drills() / "phase10_two_writers.py").read_text()
        section = self._doc().split("## The drivers are in the repository, and re-run")[1]

        assert "RESULT acknowledged <= durable" in phase8
        assert "RESULT acknowledged <= durable" in section
        assert "RESULT audit backend" in phase9
        assert "RESULT audit backend" in section
        assert "RESULT in-memory never ahead of the store" in phase9
        assert "RESULT appends accepted" in phase10

    def test_the_shim_intercepts_positional_writes(self):
        """The first version hooked only write() and never tripped, because the
        engine issues positional writes. The injection has to reach the call the
        engine makes."""
        shim = (self._drills() / "enospc.c").read_text()
        for fn in ("ssize_t write(", "ssize_t pwrite(", "ssize_t pwrite64(", "ssize_t writev("):
            assert fn in shim, f"{fn} is not intercepted"
        doc = self._doc()
        assert "LD_PRELOAD" in doc

    def test_phase_nine_refuses_to_measure_nothing(self):
        """A dev process defaults to the in-memory store, where the injection has
        nothing to fill. The first re-run reported 39 accepted and nothing wrong;
        the script now refuses instead."""
        phase9 = (self._drills() / "phase9_disk_full.py").read_text()
        assert "InMemoryBackend" in phase9
        assert "refusing to run" in phase9
