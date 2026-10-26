"""
Tests for custos/custody.py — external chain-head custody.

Implements the verification properties of docs/design/chain-head-custody.md:

- P1 record-chain consistency vs P2 anchored-head reconciliation: a
  consistent rewrite-and-rehash of the store (the exact attack the
  internal chain cannot catch) passes internal verification and must
  CONTRADICT the external anchors.
- Truncation detection (P4), anchor-log integrity (P3), gap recording
  (fail-visible), sink behavior, and main.py wiring (disabled by default).
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from custos.audit import AuditChain
from custos.custody import (
    AnchorManager,
    AnchorRecord,
    MemorySink,
    GitAnchorSink,
    build_tsa_request,
    verify_custody,
)
from custos.tenant import TenantManager, TenantConfig


def _make_chain(n: int = 10) -> AuditChain:
    chain = AuditChain()  # in-memory backend
    for i in range(n):
        chain.record(
            client_id="default",
            action="allow" if i % 2 == 0 else "deny",
            reason=f"decision {i}",
            content=f"content {i}",
        )
    return chain


def _chain_dict() -> dict:
    tm = TenantManager()
    tm.register("default", TenantConfig(tenant_id="default"))
    return {"default": tm.get("default").audit_chain}


class TestHeadAccessor:
    def test_head_returns_length_and_hash(self):
        chain = _make_chain(5)
        length, head = chain.head()
        assert length == 5
        assert len(head) == 64
        ok, _ = chain.verify()
        assert ok

    def test_head_empty_chain_is_genesis(self):
        chain = AuditChain()
        assert chain.head() == (0, "0" * 64)


class TestAnchoring:
    def test_anchor_emitted_after_n_records(self):
        chain = _make_chain(10)
        sink = MemorySink()
        mgr = AnchorManager([sink], lambda: {"default": chain}, anchor_n=5)
        mgr.anchor_due()
        assert len(sink.anchors) == 1
        a = sink.anchors[0]
        assert a.chain_length == 10
        assert a.epoch == 1
        assert a.head_hash == chain.head()[1]
        assert a.gap is None

    def test_no_anchor_when_below_threshold(self):
        chain = _make_chain(3)
        sink = MemorySink()
        mgr = AnchorManager([sink], lambda: {"default": chain}, anchor_n=50)
        mgr.anchor_due()
        assert sink.anchors == []

    def test_epochs_and_prev_links_chain(self):
        chain = _make_chain(2)
        sink = MemorySink()
        mgr = AnchorManager([sink], lambda: {"default": chain}, anchor_n=1)
        mgr.anchor_due()
        chain.record(client_id="default", action="deny", reason="d", content="c")
        chain.record(client_id="default", action="deny", reason="d2", content="c2")
        mgr.anchor_due()
        a1, a2 = sink.anchors
        assert a2.epoch == 2
        assert a2.prev_anchor_hash == a1.anchor_hash
        assert a1.prev_anchor_hash == "0" * 64
        assert a1.anchor_hash == a1.compute_hash()


class TestGapRecording:
    def test_sink_outage_records_gap_then_next_anchor_carries_it(self):
        chain = _make_chain(5)
        sink = MemorySink()
        mgr = AnchorManager([sink], lambda: {"default": chain}, anchor_n=1)

        sink.fail(True)
        mgr.anchor_due()
        assert sink.anchors == []  # nothing landed
        st = mgr._tenant_state("default")
        assert st["pending_gap"] is not None
        assert st["epoch"] == 0  # epoch not consumed by a failed attempt

        sink.fail(False)
        mgr.anchor_due()
        assert len(sink.anchors) == 1
        assert sink.anchors[0].gap is not None
        assert sink.anchors[0].gap["from_epoch"] == 1
        assert sink.anchors[0].gap["attempts"] == 1

    def test_outage_never_raises(self):
        chain = _make_chain(5)
        sink = MemorySink()
        sink.fail(True)
        mgr = AnchorManager([sink], lambda: {"default": chain}, anchor_n=1)
        mgr.anchor_due()  # must not raise — fail-visible, not crash
        assert mgr.last_error is not None


class TestExternalVerifyClean:
    def test_clean_store_all_established(self):
        chain = _make_chain(10)
        sink = MemorySink()
        mgr = AnchorManager([sink], lambda: {"default": chain}, anchor_n=1)
        mgr.anchor_due()

        records = chain.get_records()
        anchors = [a.to_dict() for a in sink.anchors]
        result = verify_custody(records, anchors)
        assert result["overall"] == "ESTABLISHED"
        assert all(v == "ESTABLISHED" for v in result["verdicts"].values())

    def test_no_anchors_cannot_establish(self):
        chain = _make_chain(5)
        records = chain.get_records()
        result = verify_custody(records, [])
        assert result["verdicts"]["P2_anchored_heads_match_store"] == "CANNOT ESTABLISH"
        assert result["overall"] == "CANNOT ESTABLISH"


class TestRewriteAndRehash:
    """The boundary case: a consistent store rewrite passes the internal
    chain verification and must CONTRADICT the external anchors (P2)."""

    def _rewrite_in_place(self, chain: AuditChain, index: int, new_reason: str):
        """Attacker simulation: change one mid-chain record, then recompute
        every subsequent hash so the store is internally consistent again."""
        recs = chain._records
        recs[index].reason = new_reason
        prev = recs[index].previous_hash
        for r in recs[index:]:
            r.previous_hash = prev
            r.record_hash = chain._compute_record_hash(r, prev)
            prev = r.record_hash
        # The in-memory chain now verifies clean; the backend is bypassed
        # the same way a compromised backend would be.

    def test_internal_verify_passes_but_custody_contradicts(self):
        chain = _make_chain(10)
        sink = MemorySink()
        mgr = AnchorManager([sink], lambda: {"default": chain}, anchor_n=1)
        mgr.anchor_due()  # head anchored at length 10

        self._rewrite_in_place(chain, 3, "tampered: attacker reason")

        ok, _ = chain.verify()  # internal check: passes (consistent rewrite)
        assert ok, "internal verification must pass after consistent rewrite"

        records = chain.get_records()
        anchors = [a.to_dict() for a in sink.anchors]
        result = verify_custody(records, anchors)

        v = result["verdicts"]
        assert v["P1_record_chain_consistency"] == "ESTABLISHED"
        assert v["P2_anchored_heads_match_store"] == "CONTRADICTION"
        assert result["overall"] == "CONTRADICTION"
        assert "rewrite detected" in str(result["detail"].get("p2_break", ""))


class TestTruncation:
    def test_truncated_tail_contradicts(self):
        chain = _make_chain(10)
        sink = MemorySink()
        mgr = AnchorManager([sink], lambda: {"default": chain}, anchor_n=1)
        mgr.anchor_due()

        # Attacker deletes the newest 4 records
        chain._records = chain._records[:6]

        records = chain.get_records()
        anchors = [a.to_dict() for a in sink.anchors]
        result = verify_custody(records, anchors)
        assert result["verdicts"]["P4_store_completeness"] == "CONTRADICTION"
        assert "truncation detected" in str(result["detail"].get("p4_break", ""))


class TestAnchorLogTamper:
    def test_modified_anchor_hash_contradicts(self):
        chain = _make_chain(4)
        sink = MemorySink()
        mgr = AnchorManager([sink], lambda: {"default": chain}, anchor_n=1)
        mgr.anchor_due()

        anchors = [a.to_dict() for a in sink.anchors]
        anchors[0]["head_hash"] = "f" * 64  # forged head

        records = chain.get_records()
        result = verify_custody(records, anchors)
        assert result["verdicts"]["P3_anchor_chain_integrity"] == "CONTRADICTION"

    def test_dropped_anchor_contradicts(self):
        chain = _make_chain(2)
        sink = MemorySink()
        mgr = AnchorManager([sink], lambda: {"default": chain}, anchor_n=1)
        mgr.anchor_due()
        chain.record(client_id="default", action="deny", reason="d", content="c")
        chain.record(client_id="default", action="deny", reason="d2", content="c2")
        mgr.anchor_due()
        assert len(sink.anchors) == 2

        anchors = [a.to_dict() for a in sink.anchors]
        del anchors[0]  # attacker removes the first anchor

        records = chain.get_records()
        result = verify_custody(records, anchors)
        assert result["verdicts"]["P3_anchor_chain_integrity"] == "CONTRADICTION"


class TestGitAnchorSink:
    def _tmp_repo(self):
        d = tempfile.mkdtemp(prefix="custos-git-")
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=d, check=True)
        with open(os.path.join(d, ".gitkeep"), "w") as fh:
            fh.write("")
        subprocess.run(["git", "add", ".gitkeep"], cwd=d, check=True)
        subprocess.run(
            ["git", "-c", "user.name=test", "-c",
             "user.email=test@invalid", "commit", "-q", "-m", "init"],
            cwd=d, check=True,
        )
        return d

    def test_append_commit_and_load_back(self):
        repo = self._tmp_repo()
        try:
            sink = GitAnchorSink(repo)
            a = AnchorRecord(
                tenant_id="default", epoch=1, chain_length=5,
                head_hash="a" * 64, anchored_at_utc="2026-10-27T00:00:00Z",
                prev_anchor_hash="0" * 64,
            )
            a.anchor_hash = a.compute_hash()
            ref = sink.append(a)
            assert len(ref) == 40  # commit sha
            assert sink.healthcheck() is True

            loaded = sink.load_anchors()
            assert len(loaded) == 1
            assert loaded[0]["anchor_hash"] == a.anchor_hash
        finally:
            shutil.rmtree(repo)

    def test_external_verify_over_git_log(self):
        repo = self._tmp_repo()
        try:
            sink = GitAnchorSink(repo)
            chain = _make_chain(6)
            mgr = AnchorManager([sink], lambda: {"default": chain}, anchor_n=1)
            mgr.anchor_due()

            records = chain.get_records()
            result = verify_custody(records, sink.load_anchors())
            assert result["overall"] == "ESTABLISHED"
        finally:
            shutil.rmtree(repo)

    def test_tampered_git_log_contradicts(self):
        repo = self._tmp_repo()
        try:
            sink = GitAnchorSink(repo)
            chain = _make_chain(3)
            mgr = AnchorManager([sink], lambda: {"default": chain}, anchor_n=1)
            mgr.anchor_due()

            # Attacker edits the anchor file in the external repo
            path = os.path.join(repo, "anchors", "default", "epoch-1.json")
            with open(path) as fh:
                d = json.load(fh)
            d["head_hash"] = "e" * 64
            with open(path, "w") as fh:
                json.dump(d, fh)

            records = chain.get_records()
            result = verify_custody(records, sink.load_anchors())
            assert result["verdicts"]["P3_anchor_chain_integrity"] == "CONTRADICTION"
        finally:
            shutil.rmtree(repo)


class TestTSADer:
    def test_request_is_der_sequence_with_digest(self):
        import hashlib
        data = b"anchor bytes"
        req = build_tsa_request(data, nonce=12345)
        assert req[0] == 0x30  # SEQUENCE
        digest = hashlib.sha256(data).digest()
        assert digest in req  # the SHA-256 digest rides in the request
        assert len(req) > 40

    def test_tsa_roundtrip(self):
        """End-to-end TSA stamp — skipped unless CUSTOS_CUSTODY_TSA_URL is
        set (same pattern as the OPA integration tests)."""
        url = os.getenv("CUSTOS_CUSTODY_TSA_URL")
        if not url:
            pytest.skip(
                "CUSTOS_CUSTODY_TSA_URL not set — TSA integration tests "
                "require a running RFC 3161 timestamping service"
            )
        from custos.custody import TSAAnchorSink
        sink = TSAAnchorSink(url, tempfile.mkdtemp(prefix="custos-tsa-"))
        a = AnchorRecord(
            tenant_id="default", epoch=1, chain_length=1,
            head_hash="b" * 64, anchored_at_utc="2026-10-27T00:00:00Z",
            prev_anchor_hash="0" * 64,
        )
        a.anchor_hash = a.compute_hash()
        ref = sink.append(a)
        assert ref == "tsa:1"
        assert sink.healthcheck() is True


class TestEnvConfig:
    def test_disabled_by_default(self, monkeypatch):
        monkeypatch.delenv("CUSTOS_CUSTODY_ENABLED", raising=False)
        from custos.custody import build_custody_from_env
        assert build_custody_from_env(_chain_dict()) is None

    def test_enabled_git_sink(self, monkeypatch):
        repo = tempfile.mkdtemp(prefix="custos-cfg-")
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
        try:
            subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@invalid",
                           "commit", "-q", "--allow-empty", "-m", "init"],
                           cwd=repo, check=True)
            monkeypatch.setenv("CUSTOS_CUSTODY_ENABLED", "true")
            monkeypatch.setenv("CUSTOS_CUSTODY_SINKS", "git")
            monkeypatch.setenv("CUSTOS_CUSTODY_GIT_REPO", repo)
            monkeypatch.setenv("CUSTOS_CUSTODY_ANCHOR_N", "1")

            from custos.custody import build_custody_from_env
            mgr = build_custody_from_env(_chain_dict())
            assert mgr is not None
            assert mgr._sinks[0].name == "git"
        finally:
            shutil.rmtree(repo)

    def test_missing_git_repo_raises(self, monkeypatch):
        monkeypatch.setenv("CUSTOS_CUSTODY_ENABLED", "1")
        monkeypatch.setenv("CUSTOS_CUSTODY_SINKS", "git")
        monkeypatch.delenv("CUSTOS_CUSTODY_GIT_REPO", raising=False)
        from custos.custody import build_custody_from_env
        with pytest.raises(RuntimeError, match="CUSTOS_CUSTODY_GIT_REPO"):
            build_custody_from_env(_chain_dict())


class TestApiWiring:
    def test_ready_reports_custody_disabled_by_default(self, client):
        import main as app_module
        if app_module.custody_manager is not None:
            pytest.skip("custody enabled in this environment")
        r = client.get("/ready")
        assert r.status_code == 200
        assert r.json()["checks"]["custody"] == "disabled"

    def test_metrics_carries_custody_enabled_line(self, client):
        r = client.get("/metrics")
        assert r.status_code == 200
        text = r.text
        assert "custos_custody_enabled" in text
        assert "# HELP custos_custody_enabled" in text
