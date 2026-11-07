"""Issue 137: whether the served path keeps content, said out loud.

The defect these tests hold shut is a claim, not a crash. Every record the
service wrote bound a content hash and stored nothing, so "the service supports
erasure" was empty: there was nothing to erase, and no endpoint accepted a
request to erase it. Two modes now exist and neither is inferred from the other's
configuration, because the failure mode of guessing here is a process that looks
configured for retention and records that it kept nothing.

The HTTP tests go through a real startup, so the refusals are exercised where they
happen rather than through the helper alone.
"""

import hashlib
import os

import pytest
from fastapi.testclient import TestClient

from custos.retention import ContentPurged

from custos.content_retention import (
    ADMIN_TOKEN_ENV,
    MODE_ENV,
    MODE_OFF,
    MODE_STORE,
    STORE_DIR_ENV,
    RetentionConfigRefused,
    content_retention_mode,
    content_store_for,
    reset_store_cache,
    store_path_for,
    validate_content_retention,
)

TOKEN = "retention-token-for-tests"
BODY = "patient 5510, 77 Brickell Ave, dob 1981-04-02"


@pytest.fixture(autouse=True)
def _clean(monkeypatch, tmp_path):
    monkeypatch.delenv(MODE_ENV, raising=False)
    monkeypatch.delenv(STORE_DIR_ENV, raising=False)
    monkeypatch.delenv(ADMIN_TOKEN_ENV, raising=False)
    monkeypatch.delenv("CUSTOS_ENV", raising=False)
    monkeypatch.delenv("AUDIT_DB_PATH", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    reset_store_cache()
    yield
    reset_store_cache()


def _enable(monkeypatch, tmp_path, token=TOKEN):
    directory = tmp_path / "content"
    directory.mkdir()
    monkeypatch.setenv(MODE_ENV, MODE_STORE)
    monkeypatch.setenv(STORE_DIR_ENV, str(directory))
    if token is not None:
        monkeypatch.setenv(ADMIN_TOKEN_ENV, token)
    return directory


def _fresh_manager(monkeypatch, app_module):
    """Replace the tenant manager the way a fresh process would, in both places.

    The manager is module state and the action gate keeps the one it was built
    with, so rebinding only ``tenant_manager`` leaves the gate deciding against a
    manager the app no longer serves: its records land in a chain ``/v1/audit``
    does not read. These tests rebind to pick up a new AUDIT_DB_PATH, so they have
    to rebind both. ``monkeypatch.setattr`` restores them at the end of the test,
    which the assignments did not.
    """
    manager = app_module.TenantManager()
    monkeypatch.setattr(app_module, "tenant_manager", manager)
    monkeypatch.setattr(app_module, "action_gate", app_module.ActionGate(manager))
    return manager


class TestTheModeIsReadNotGuessed:
    def test_default_is_off(self):
        assert content_retention_mode() == MODE_OFF

    def test_an_unknown_mode_is_refused_by_name(self, monkeypatch):
        monkeypatch.setenv(MODE_ENV, "sometimes")
        with pytest.raises(RetentionConfigRefused, match=MODE_ENV):
            content_retention_mode()

    def test_a_store_directory_with_the_mode_off_is_refused_not_ignored(self, monkeypatch, tmp_path):
        """A configured store the process does not use reads as retention that is
        on, which is the specific misreading this module exists to prevent."""
        monkeypatch.setenv(STORE_DIR_ENV, str(tmp_path))
        with pytest.raises(RetentionConfigRefused, match=STORE_DIR_ENV):
            validate_content_retention()

    def test_an_admin_token_with_the_mode_off_is_refused(self, monkeypatch):
        monkeypatch.setenv(ADMIN_TOKEN_ENV, TOKEN)
        with pytest.raises(RetentionConfigRefused, match=ADMIN_TOKEN_ENV):
            validate_content_retention()

    def test_store_mode_without_a_directory_is_refused(self, monkeypatch):
        monkeypatch.setenv(MODE_ENV, MODE_STORE)
        with pytest.raises(RetentionConfigRefused, match=STORE_DIR_ENV):
            validate_content_retention()

    def test_store_mode_with_a_missing_directory_is_refused_not_created(self, monkeypatch, tmp_path):
        monkeypatch.setenv(MODE_ENV, MODE_STORE)
        missing = tmp_path / "not-there"
        monkeypatch.setenv(STORE_DIR_ENV, str(missing))
        monkeypatch.setenv(ADMIN_TOKEN_ENV, TOKEN)
        with pytest.raises(RetentionConfigRefused, match="not a directory"):
            validate_content_retention()
        assert not missing.exists(), "the process must not invent a store path"

    def test_store_mode_without_an_admin_token_is_refused(self, monkeypatch, tmp_path):
        """Content that is kept and cannot be erased is the state the mode exists
        to make impossible, so it does not start."""
        monkeypatch.setenv(MODE_ENV, MODE_STORE)
        directory = tmp_path / "content"
        directory.mkdir()
        monkeypatch.setenv(STORE_DIR_ENV, str(directory))
        with pytest.raises(RetentionConfigRefused, match=ADMIN_TOKEN_ENV):
            validate_content_retention()

    def test_a_valid_configuration_reports_what_is_in_force(self, monkeypatch, tmp_path):
        _enable(monkeypatch, tmp_path)
        summary = validate_content_retention()
        assert summary["content_retention"] == MODE_STORE
        assert summary["retention_admin_configured"] is True

    def test_any_accepted_tenant_id_gets_a_store_inside_the_directory(self, monkeypatch, tmp_path):
        """Tenant ids are accepted by POST /v1/tenants with no character policy, so
        naming their files must not be the place one becomes illegal: a refusal
        here would turn a legal tenant into a 500 on the decision path."""
        _enable(monkeypatch, tmp_path)
        directory = str(tmp_path)
        names = {}
        for tenant_id in ("acme", "acme corp", "../other", "t-abc", "", "a" * 64):
            path = store_path_for(directory, tenant_id)
            assert os.path.dirname(path) == directory, tenant_id
            names[tenant_id] = os.path.basename(path)
        assert len(set(names.values())) == len(names), names

    def test_the_reserved_prefix_keeps_the_two_name_forms_apart(self, monkeypatch, tmp_path):
        """A readable name can never collide with a hashed one, because the
        hashed form reserves its prefix and a tenant that looks like it is hashed."""
        _enable(monkeypatch, tmp_path)
        readable = os.path.basename(store_path_for(str(tmp_path), "acme"))
        hashed = os.path.basename(store_path_for(str(tmp_path), "acme corp"))
        assert readable == "content-acme.sqlite"
        assert hashed.startswith("content-t-") and hashed != readable
        # "t-" itself is pushed into the hashed form rather than owning that name.
        assert not os.path.basename(store_path_for(str(tmp_path), "t-x")).startswith("content-t-x")


class TestTheServedPathWithRetentionOff:
    def test_a_record_says_none_because_nothing_was_kept(self, monkeypatch):
        import main as app_module

        with TestClient(app_module.app) as client:
            response = client.post(
                "/v1/evaluate",
                json={"client_id": "c", "content": BODY, "tenant_id": "default"},
            )
            assert response.status_code == 200
            info = client.get("/v1/info").json()
            assert info["content_retention"] == MODE_OFF

            records = client.get("/v1/audit").json()
            assert records, "the decision must still be recorded"
            assert records[-1]["commitment"] == "none"
            # Nothing stored, and the store is not silently created at a default path.
            assert content_store_for("default") is None

    def test_an_erasure_request_is_refused_for_having_nothing_to_erase(self, monkeypatch):
        import main as app_module

        with TestClient(app_module.app) as client:
            response = client.post(
                "/v1/retention/purge",
                json={"content_hash": "a" * 64, "reason": "erasure request"},
                headers={"X-CUSTOS-Retention-Token": TOKEN},
            )
            assert response.status_code == 503
            detail = response.json()["detail"]
            assert MODE_OFF in detail
            assert "nothing to act on" in detail


class TestTheServedPathWithRetentionOn:
    def _client(self, monkeypatch, tmp_path):
        import main as app_module

        directory = _enable(monkeypatch, tmp_path)
        return TestClient(app_module.app), directory

    def test_the_body_is_kept_and_the_record_says_which_form(self, monkeypatch, tmp_path):
        client, directory = self._client(monkeypatch, tmp_path)
        with client:
            response = client.post(
                "/v1/evaluate",
                json={"client_id": "c", "content": BODY, "tenant_id": "default"},
            )
            assert response.status_code == 200
            records = client.get("/v1/audit").json()
            assert records[-1]["commitment"] == "salted-v1"
            content_hash = records[-1]["content_hash"]

            store = content_store_for("default")
            assert store.open_body(content_hash) == BODY
            assert (directory / "content-default.sqlite").exists()

    def test_status_compares_the_two_sides_and_reports_clean(self, monkeypatch, tmp_path):
        client, _ = self._client(monkeypatch, tmp_path)
        with client:
            client.post("/v1/evaluate", json={"client_id": "c", "content": BODY})
            status = client.get(
                "/v1/retention/status",
                headers={"X-CUSTOS-Retention-Token": TOKEN},
            )
            assert status.status_code == 200
            body = status.json()
            assert body["ok"] is True
            assert body["findings"] == []
            assert body["records_read"] == 1

    def test_the_erasure_path_deletes_and_attests(self, monkeypatch, tmp_path):
        client, _ = self._client(monkeypatch, tmp_path)
        with client:
            client.post("/v1/evaluate", json={"client_id": "c", "content": BODY})
            content_hash = client.get("/v1/audit").json()[-1]["content_hash"]

            purge = client.post(
                "/v1/retention/purge",
                json={"content_hash": content_hash, "reason": "customer erasure request"},
                headers={"X-CUSTOS-Retention-Token": TOKEN},
            )
            assert purge.status_code == 200, purge.text
            assert purge.json()["purged"] is True
            assert purge.json()["store_status"] == "purged"

            records = client.get("/v1/audit").json()
            assert records[-1]["action"] == "PURGE"
            assert records[-1]["commitment"] == "purged-v1"
            assert records[-1]["content_hash"] == content_hash

            # The deletion holds in the record side and the store side at once.
            status = client.get(
                "/v1/retention/status",
                headers={"X-CUSTOS-Retention-Token": TOKEN},
            ).json()
            assert status["ok"] is True, status["findings"]

            # And the body is gone from the file, not only from the view.
            store_file = next(tmp_path.glob("content/content-default.sqlite"))
            assert BODY.encode() not in store_file.read_bytes()

    def test_wrong_or_missing_admin_token_is_refused(self, monkeypatch, tmp_path):
        client, _ = self._client(monkeypatch, tmp_path)
        with client:
            client.post("/v1/evaluate", json={"client_id": "c", "content": BODY})
            content_hash = client.get("/v1/audit").json()[-1]["content_hash"]
            for headers in ({}, {"X-CUSTOS-Retention-Token": "wrong"}):
                response = client.post(
                    "/v1/retention/purge",
                    json={"content_hash": content_hash, "reason": "erasure"},
                    headers=headers,
                )
                assert response.status_code == 401
            # Refused twice, and the content is still there.
            assert content_store_for("default").status(content_hash) == "present"

    def test_purging_something_never_stored_is_refused(self, monkeypatch, tmp_path):
        client, _ = self._client(monkeypatch, tmp_path)
        with client:
            response = client.post(
                "/v1/retention/purge",
                json={"content_hash": hashlib.sha256(b"never seen").hexdigest(), "reason": "x"},
                headers={"X-CUSTOS-Retention-Token": TOKEN},
            )
            assert response.status_code == 409
            assert "never stored" in response.json()["detail"]

    def test_purging_twice_is_refused_with_the_prior_time(self, monkeypatch, tmp_path):
        client, _ = self._client(monkeypatch, tmp_path)
        with client:
            client.post("/v1/evaluate", json={"client_id": "c", "content": BODY})
            content_hash = client.get("/v1/audit").json()[-1]["content_hash"]
            first = client.post(
                "/v1/retention/purge",
                json={"content_hash": content_hash, "reason": "erasure"},
                headers={"X-CUSTOS-Retention-Token": TOKEN},
            )
            assert first.status_code == 200
            second = client.post(
                "/v1/retention/purge",
                json={"content_hash": content_hash, "reason": "erasure again"},
                headers={"X-CUSTOS-Retention-Token": TOKEN},
            )
            assert second.status_code == 409
            assert "already purged" in second.json()["detail"]

    def test_a_restored_chain_beside_a_live_store_is_reported_by_the_endpoint(self, monkeypatch, tmp_path):
        """The split restore, end to end: this is issue 136 seen from the API.

        The chain is rolled back to before the erasure and the store is left past
        it. verify() stays green because it is a statement about linkage; the
        status endpoint is what says the two sides disagree.
        """
        import shutil

        import main as app_module
        from custos.audit import AuditChain

        client, _ = self._client(monkeypatch, tmp_path)
        audit_path = tmp_path / "audit.sqlite"
        monkeypatch.setenv("AUDIT_DB_PATH", str(audit_path))
        # A fresh manager so the chain is built against the file we will copy.
        _fresh_manager(monkeypatch, app_module)
        with TestClient(app_module.app) as c:
            c.post("/v1/evaluate", json={"client_id": "c", "content": BODY})
            content_hash = c.get("/v1/audit").json()[-1]["content_hash"]
            shutil.copy2(audit_path, tmp_path / "audit-pre-purge.sqlite")
            purge = c.post(
                "/v1/retention/purge",
                json={"content_hash": content_hash, "reason": "erasure"},
                headers={"X-CUSTOS-Retention-Token": TOKEN},
            )
            assert purge.status_code == 200

            shutil.copy2(tmp_path / "audit-pre-purge.sqlite", audit_path)
            _fresh_manager(monkeypatch, app_module)
            restored_chain = AuditChain(tenant_id="default")
            assert restored_chain.verify() == (True, "OK")

            status = c.get(
                "/v1/retention/status",
                headers={"X-CUSTOS-Retention-Token": TOKEN},
            )
            assert status.status_code == 200
            body = status.json()
            assert body["ok"] is False
            assert [f["kind"] for f in body["findings"]] == ["unattested-purge"]
            assert body["findings"][0]["content_hash"] == content_hash


class TestStartupRefusalsReachTheProcess:
    def test_the_app_refuses_to_start_with_retention_misconfigured(self, monkeypatch, tmp_path):
        """A store mode with nowhere to store is refused at startup, not at the
        first request, so a process cannot serve traffic with an erasure path it
        cannot honour."""
        import main as app_module

        missing = tmp_path / "not-there"
        monkeypatch.setenv(MODE_ENV, MODE_STORE)
        monkeypatch.setenv(STORE_DIR_ENV, str(missing))
        monkeypatch.setenv(ADMIN_TOKEN_ENV, TOKEN)
        with pytest.raises(RetentionConfigRefused):
            with TestClient(app_module.app):
                pass
        assert not missing.exists()

    def test_the_app_starts_with_retention_on_and_reports_it(self, monkeypatch, tmp_path):
        import main as app_module

        _enable(monkeypatch, tmp_path)
        with TestClient(app_module.app) as client:
            info = client.get("/v1/info").json()
            assert info["content_retention"] == MODE_STORE


class TestTheEdgeCasesFoundByFactChecking:
    """Two states that only appear once retention is on, both of which failed
    before they were tested: a legal tenant id that is not a filename, and content
    that was purged and then submitted again."""

    def _client(self, monkeypatch, tmp_path):
        import main as app_module

        _enable(monkeypatch, tmp_path)
        os.environ["AUTH_DISABLED"] = "1"
        monkeypatch.setenv("AUTH_DISABLED", "1")
        return TestClient(app_module.app)

    def test_a_tenant_id_with_a_space_still_evaluates(self, monkeypatch, tmp_path):
        client = self._client(monkeypatch, tmp_path)
        with client:
            created = client.post("/v1/tenants", json={"tenant_id": "acme corp"})
            assert created.status_code == 200, created.text
            response = client.post(
                "/v1/evaluate",
                json={"client_id": "c", "content": BODY, "tenant_id": "acme corp"},
            )
            assert response.status_code == 200, response.text
            record = client.get("/v1/audit?tenant_id=acme%20corp").json()[-1]
            assert record["commitment"] == "salted-v1"
            assert content_store_for("acme corp").open_body(record["content_hash"]) == BODY

    def test_purged_content_is_still_decided_and_recorded_as_none(self, monkeypatch, tmp_path):
        """An erasure must not become a blacklist: the gate decides on content it
        is given, and whether it keeps a copy is a separate question."""
        client = self._client(monkeypatch, tmp_path)
        with client:
            first = client.post("/v1/evaluate", json={"client_id": "c", "content": BODY})
            assert first.status_code == 200
            content_hash = client.get("/v1/audit").json()[-1]["content_hash"]
            purged = client.post(
                "/v1/retention/purge",
                json={"content_hash": content_hash, "reason": "erasure"},
                headers={"X-CUSTOS-Retention-Token": TOKEN},
            )
            assert purged.status_code == 200

            again = client.post("/v1/evaluate", json={"client_id": "c", "content": BODY})
            assert again.status_code == 200, again.text
            record = client.get("/v1/audit").json()[-1]
            assert record["commitment"] == "none", (
                "the store will not re-hold purged content, so the record must not "
                "claim a stored form"
            )
            assert record["content_hash"] == content_hash
            assert content_store_for("default").status(content_hash) == "purged"

            # And the two sides still agree: the attestation is in the chain.
            status = client.get(
                "/v1/retention/status", headers={"X-CUSTOS-Retention-Token": TOKEN}
            ).json()
            assert status["ok"] is True, status["findings"]

    def test_a_failed_record_write_leaves_a_body_that_is_announced(self, monkeypatch, tmp_path):
        """The write order is store-then-record because the record must state the
        form the store used, so a failed record write can leave an unattributed
        body. It is logged with its digest rather than deleted, because bodies are
        addressed by content and may belong to another record's body.

        The custos logger does not propagate to root, so the handler is attached
        where the message is actually emitted.
        """
        import logging

        import main as app_module

        client = self._client(monkeypatch, tmp_path)
        seen = []

        class Capture(logging.Handler):
            def emit(self, record):
                seen.append(record.getMessage())

        handler = Capture()
        # The event is emitted by the shared retention-aware record path, which both
        # the evaluate endpoint and the action gate call. It used to be logged from
        # custos.main because the ordering lived there; capturing the old logger now
        # would pass on silence.
        logger = logging.getLogger("custos.retention")
        logger.addHandler(handler)
        try:
            with client:
                store = content_store_for("default")

                def boom(*args, **kwargs):
                    store.put(kwargs.get("content") or args[0])
                    raise RuntimeError("record write failed")

                monkeypatch.setattr(store, "put_and_record", boom)
                failing = TestClient(app_module.app, raise_server_exceptions=False)
                with failing:
                    response = failing.post(
                        "/v1/evaluate", json={"client_id": "c", "content": BODY}
                    )
                assert response.status_code == 500
                assert any("body_without_record" in message for message in seen), seen
        finally:
            logger.removeHandler(handler)


class TestTheActionGateKeepsWhatItDecidedOn:
    """Issue 140: the gate decides on a proposed action and kept nothing.

    That was coherent and empty at the same time. ``commitment none`` is a true
    statement about a gate that stores no body, so nothing in the chain was wrong;
    but it also meant an erasure request could never reach a decision to run a
    command, which is the record an operator most wants to be able to respond to.
    The gate now records through the same retention-aware path as /v1/evaluate, so
    the two cannot disagree about which form was used.
    """

    def _client(self, monkeypatch, tmp_path):
        import main as app_module

        directory = _enable(monkeypatch, tmp_path)
        app_module.action_gate.register_tools("default", {"lookup"})
        return TestClient(app_module.app), directory

    @staticmethod
    def _action(command="lookup --id 42"):
        from custos.action_gate import ActionRequest

        return ActionRequest(tool="lookup", command=command)

    def test_the_gate_keeps_the_action_and_the_record_says_which_form(self, monkeypatch, tmp_path):
        client, _ = self._client(monkeypatch, tmp_path)
        with client:
            response = client.post(
                "/v1/evaluate_action",
                json={"tool": "lookup", "command": "lookup --id 42", "tenant_id": "default"},
            )
            assert response.status_code == 200
            assert response.json()["allowed"] is True

            record = client.get("/v1/audit").json()[-1]
            assert record["commitment"] == "salted-v1", (
                "the gate claimed no stored form while retention was on"
            )
            store = content_store_for("default")
            assert store.open_body(record["content_hash"]) == self._action().serialize()

    def test_a_purge_reaches_the_gates_records(self, monkeypatch, tmp_path):
        client, _ = self._client(monkeypatch, tmp_path)
        with client:
            client.post(
                "/v1/evaluate_action",
                json={"tool": "lookup", "command": "lookup --id 42", "tenant_id": "default"},
            )
            content_hash = client.get("/v1/audit").json()[-1]["content_hash"]

            response = client.post(
                "/v1/retention/purge",
                json={
                    "tenant_id": "default",
                    "content_hash": content_hash,
                    "reason": "erasure request from the operator",
                },
                headers={"X-CUSTOS-Retention-Token": TOKEN},
            )
            assert response.status_code == 200, response.text

            store = content_store_for("default")
            # The store raises rather than answering False for content it purged:
            # absence is not a mismatch, and a caller that gets a body-less None
            # back cannot tell a purge from a store that never held the digest.
            with pytest.raises(ContentPurged):
                store.open_body(content_hash)
            status = client.get(
                "/v1/retention/status", headers={"X-CUSTOS-Retention-Token": TOKEN}
            ).json()
            assert status["ok"] is True, status
            assert status["findings"] == [], status

    def test_purged_action_content_is_still_decided(self, monkeypatch, tmp_path):
        """An erasure must not become a blacklist: the gate still decides, and the
        new record says ``none`` because the store will not hold that body again."""
        client, _ = self._client(monkeypatch, tmp_path)
        with client:
            client.post(
                "/v1/evaluate_action",
                json={"tool": "lookup", "command": "lookup --id 42", "tenant_id": "default"},
            )
            content_hash = client.get("/v1/audit").json()[-1]["content_hash"]
            client.post(
                "/v1/retention/purge",
                json={
                    "tenant_id": "default",
                    "content_hash": content_hash,
                    "reason": "erasure request from the operator",
                },
                headers={"X-CUSTOS-Retention-Token": TOKEN},
            )

            response = client.post(
                "/v1/evaluate_action",
                json={"tool": "lookup", "command": "lookup --id 42", "tenant_id": "default"},
            )
            assert response.status_code == 200, response.text
            assert response.json()["allowed"] is True
            assert client.get("/v1/audit").json()[-1]["commitment"] == "none"

    def test_an_unrecordable_allow_is_refused_not_raised(self, monkeypatch, tmp_path):
        """Storing the body is now on the gate's path, so a store failure has to
        land as a decision. An allow the gate could not record is a deny."""
        client, _ = self._client(monkeypatch, tmp_path)
        with client:
            store = content_store_for("default")

            def boom(*args, **kwargs):
                raise OSError(28, "No space left on device")

            monkeypatch.setattr(store, "put_and_record", boom)
            response = client.post(
                "/v1/evaluate_action",
                json={"tool": "lookup", "command": "lookup --id 42", "tenant_id": "default"},
            )
            assert response.status_code == 200, response.text
            body = response.json()
            assert body["allowed"] is False, body
            assert "could not be recorded" in body["reason"], body
            assert body["audit_record_hash"] is None, body
