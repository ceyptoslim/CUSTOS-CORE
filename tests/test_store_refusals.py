"""Two drill findings, held shut where they were found.

Issue 130: a full store reached the caller as an unhandled 500, which is
indistinguishable from a bug in the gate and teaches a caller to retry something
that will not succeed. The condition is now a named refusal, and the test derives
it from a real store rather than mocking the exception, because a mock proves the
handler and not the detection.

Issue 131: two processes cold-starting on an empty database raced inside schema
creation and one died. The lock is tested against a store that reproduces the
race, so removing the lock fails the test that says both boots come up.
"""

import sqlite3
import threading

import pytest

import custos.audit as audit_module
from custos.audit import (
    AuditChain,
    SQLiteBackend,
    is_full_store_error,
    schema_lock_key,
)


_CAP = {"pages": None}


def _cap_every_connection(monkeypatch, path: str) -> None:
    """Cap the store so it cannot allocate another page.

    ``PRAGMA max_page_count`` does not survive a reconnect, so the cap is applied
    by a wrapper on ``sqlite3.connect``: every connection the code opens is capped,
    which makes this a property of the store rather than of the test's connection.

    No filler is needed and no exception is invented. The capped store cannot grow,
    so an append larger than the space left in it produces SQLite's own "database
    or disk is full", which is the condition issue 130 is about. A record that fits
    in the remaining bytes would succeed, which is why the test appends a large one:
    whether a specific small write fits is a coincidence of page layout, and a test
    resting on that coincidence would go green and red for the wrong reasons.
    """
    with sqlite3.connect(path) as setup:
        _CAP["pages"] = setup.execute("PRAGMA page_count").fetchone()[0]

    real_connect = sqlite3.connect

    def capped_connect(*args, **kwargs):
        conn = real_connect(*args, **kwargs)
        if _CAP["pages"] is not None:
            conn.execute(f"PRAGMA max_page_count = {_CAP['pages']}")
        return conn

    monkeypatch.setattr(sqlite3, "connect", capped_connect)


# Larger than any space a capped store has left, so the append must allocate and
# must therefore fail. The record's reason is bound into the preimage, so this is
# an ordinary field of an ordinary record, not a crafted one.
_TOO_BIG = "r" * 200_000


class TestAFullStoreIsARefusal:
    def test_the_recognisable_texts_are_a_full_store(self):
        for text in (
            "database or disk is full",
            "No space left on device",
            "could not extend file: No space left",
            "disk full while writing",
        ):
            assert is_full_store_error(sqlite3.OperationalError(text)), text

    def test_the_sqlstates_for_disk_and_memory_are_a_full_store(self):
        class FakeOperationalError(Exception):
            pgcode = "53100"

        class FakeOutOfMemory(Exception):
            pgcode = "53200"

        assert is_full_store_error(FakeOperationalError("unrelated text"))
        assert is_full_store_error(FakeOutOfMemory("unrelated text"))

    def test_an_unrecognised_store_error_stays_unrecognised(self):
        """Recognising too little is recoverable; recognising too much tells a
        caller to wait for a condition that may never clear."""
        for kind_or_text in (
            sqlite3.OperationalError("unable to open database file"),
            sqlite3.OperationalError("database is locked"),
            sqlite3.IntegrityError("UNIQUE constraint failed"),
            RuntimeError("something else entirely"),
        ):
            assert not is_full_store_error(kind_or_text), kind_or_text

    def test_the_backend_raises_the_named_refusal_from_a_real_full_store(
        self, monkeypatch, tmp_path
    ):
        path = str(tmp_path / "audit.sqlite")
        chain = AuditChain(tenant_id="acme", _backend=SQLiteBackend(path, tenant_id="acme"))
        chain.record(client_id="c", action="ALLOW", reason="first", content="a")
        _cap_every_connection(monkeypatch, path)

        with pytest.raises(audit_module.AuditStoreFull) as caught:
            chain.record(client_id="c", action="ALLOW", reason=_TOO_BIG, content="b")
        assert "not recorded" in str(caught.value)
        assert "chain was not advanced" in str(caught.value)

    def test_the_chain_does_not_advance_past_what_the_store_refused(
        self, monkeypatch, tmp_path
    ):
        path = str(tmp_path / "audit.sqlite")
        chain = AuditChain(tenant_id="acme", _backend=SQLiteBackend(path, tenant_id="acme"))
        chain.record(client_id="c", action="ALLOW", reason="first", content="a")
        before = len(chain.get_records())
        _cap_every_connection(monkeypatch, path)

        with pytest.raises(audit_module.AuditStoreFull):
            chain.record(client_id="c", action="ALLOW", reason=_TOO_BIG, content="b")
        assert len(chain.get_records()) == before


class TestTheServedPathRefusesByName:
    def test_the_real_app_registers_the_refusal(self):
        import main as app_module

        registered = {cls.__name__ for cls in app_module.app.exception_handlers}
        assert "AuditStoreFull" in registered, (
            "an unregistered exception is a 500 again, whatever the handler says: "
            f"registered {sorted(registered)}"
        )

    def test_the_answer_is_a_503_with_a_reason_and_a_wait(self):
        """The shape a caller branches on, produced by the handler the app uses.

        Built on a route that raises the refusal rather than on a full store,
        because the app's tenant manager is constructed at import and a store
        arranged per test cannot reach it. The engine detection is covered above,
        where the store really is full.
        """
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        import main as app_module

        app = FastAPI()
        app.add_exception_handler(
            audit_module.AuditStoreFull, app_module.audit_store_full_handler
        )

        @app.get("/raise")
        def _raise():
            raise audit_module.AuditStoreFull("the audit store is full")

        response = TestClient(app).get("/raise")

        assert response.status_code == 503
        assert response.headers["X-CUSTOS-Refusal"] == "audit-store-full"
        assert response.headers["Retry-After"] == "30"
        body = response.json()
        assert body["reason"] == "audit_store_full"
        assert body["retry_after_seconds"] == 30
        assert "not recorded" in body["detail"]
        assert "nothing was served unrecorded" in body["detail"]


# ---------------------------------------------------------------------------
# Issue 131: the cold-start race, tested against a store that reproduces it.
# ---------------------------------------------------------------------------


class FakeDuplicateType(Exception):
    """What psycopg2 raises when two processes create the same composite type."""


class _SchemaStore:
    """A store that races the way PostgreSQL does, and serialises when locked.

    A real database is not available in every environment that runs this suite, and
    a test that skips is a test that does not hold the defect shut. This reproduces
    the mechanism instead of the engine: the DDL path checks whether the table
    exists, both threads arrive, and the loser raises the duplicate-type error.
    Holding the advisory lock takes the serialised path, where the second thread
    finds the table and creates nothing.
    """

    def __init__(self, parties: int = 2):
        self.created = False
        self.lock = threading.Lock()
        self.barrier = threading.Barrier(parties)
        self._holder = threading.local()

    def advisory_lock(self):
        self.lock.acquire()
        self._holder.held = True

    def release(self):
        if getattr(self._holder, "held", False):
            self._holder.held = False
            self.lock.release()

    def create_table(self):
        if getattr(self._holder, "held", False):
            self.created = True
            return
        # Unguarded: both threads reach the DDL before either commits.
        try:
            self.barrier.wait(timeout=2)
        except threading.BrokenBarrierError:
            pass
        if self.created:
            raise FakeDuplicateType(
                'duplicate key value violates unique constraint "pg_type_typname_nsp_index"'
            )
        self.created = True


class _FakeCursor:
    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql, params=None):
        if "pg_advisory_xact_lock" in sql:
            self._conn.store.advisory_lock()
        elif "CREATE TABLE" in sql:
            self._conn.store.create_table()
        self._conn.statements.append(sql.strip().split("(")[0].strip())

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class _FakeConn:
    def __init__(self, store):
        self.store = store
        self.statements = []

    def cursor(self):
        return _FakeCursor(self)

    def commit(self):
        self.store.release()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.store.release()


def _postgres_backend_over(store: _SchemaStore):
    """An audit backend whose connection is the racing store, with no real driver."""
    from custos.audit import PostgreSQLBackend

    backend = PostgreSQLBackend.__new__(PostgreSQLBackend)
    backend._url = "postgresql://fake/fake"
    backend._tenant_id = None
    backend._psycopg2 = None
    backend._connect = lambda: _FakeConn(store)
    return backend


class TestTheColdStartRace:
    def test_the_lock_is_held_before_any_schema_change(self):
        store = _SchemaStore(parties=1)
        backend = _postgres_backend_over(store)
        conn = backend._connect()
        backend._connect = lambda: conn
        backend._init()

        assert conn.statements[0] == "SELECT pg_advisory_xact_lock", conn.statements
        assert any("CREATE TABLE" in s for s in conn.statements), conn.statements
        first_ddl = next(i for i, s in enumerate(conn.statements) if "CREATE TABLE" in s)
        assert first_ddl > 0, "the DDL ran before the lock was taken"

    def test_two_cold_starts_both_come_up(self):
        """The defect itself: without the lock the second process dies here."""
        store = _SchemaStore(parties=2)
        results = {}

        def boot(name):
            backend = _postgres_backend_over(store)
            try:
                backend._init()
                results[name] = "up"
            except FakeDuplicateType as exc:
                results[name] = f"died: {exc}"

        threads = [threading.Thread(target=boot, args=(n,)) for n in ("a", "b")]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert results == {"a": "up", "b": "up"}, results

    def test_the_policy_store_takes_the_same_lock(self):
        from custos.policy_store import PostgreSQLPolicyBackend

        store = _SchemaStore(parties=1)
        backend = PostgreSQLPolicyBackend.__new__(PostgreSQLPolicyBackend)
        backend._url = "postgresql://fake/fake"
        conn = _FakeConn(store)
        backend._connect = lambda: conn
        backend._init()
        assert conn.statements[0] == "SELECT pg_advisory_xact_lock", conn.statements

    def test_the_lock_keys_are_derived_and_distinct(self):
        assert schema_lock_key("audit_records") == schema_lock_key("audit_records")
        assert schema_lock_key("audit_records") != schema_lock_key("policy_rules")
        key = schema_lock_key("audit_records")
        assert -(2**63) <= key < 2**63, "an advisory lock key must fit int8"
