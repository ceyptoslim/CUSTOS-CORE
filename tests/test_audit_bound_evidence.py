"""The citation and correlation fields are optional by construction, because old
records must keep verifying byte-identically. Optional is not the same as
unenforced: a deployment claiming every decision cites its policy should be able
to make that claim fail loudly. And a failed storage write must not leave the
in-memory chain longer than the store.
"""
import importlib

import pytest

import custos.audit as audit


class FailingBackend:
    def save(self, record):
        raise RuntimeError("storage unavailable")

    def load_all(self):
        return []


def _count(chain):
    try:
        return len(chain.get_records())
    except AttributeError:
        return len(chain._records)


def _reload(monkeypatch, strict):
    monkeypatch.setenv("CUSTOS_AUDIT_REQUIRE_BOUND", "1" if strict else "0")
    return importlib.reload(audit)


def test_strict_mode_refuses_a_record_with_no_citation(monkeypatch):
    mod = _reload(monkeypatch, True)
    chain = mod.AuditChain()
    with pytest.raises(ValueError) as exc:
        chain.record(client_id="t", action="a", reason="allow", content="x",
                     trace_id="tr-1")
    assert "policy_digest" in str(exc.value)
    assert _count(chain) == 0
    _reload(monkeypatch, False)


def test_strict_mode_refuses_a_record_with_no_correlation_id(monkeypatch):
    mod = _reload(monkeypatch, True)
    chain = mod.AuditChain()
    with pytest.raises(ValueError) as exc:
        chain.record(client_id="t", action="a", reason="allow", content="x",
                     policy_digest="b" * 64)
    assert "trace_id" in str(exc.value)
    _reload(monkeypatch, False)


def test_strict_mode_accepts_a_bound_record_and_it_verifies(monkeypatch):
    mod = _reload(monkeypatch, True)
    chain = mod.AuditChain()
    rec = chain.record(client_id="t", action="a", reason="allow", content="x",
                       policy_digest="b" * 64, trace_id="tr-1")
    assert rec.binding_version >= 1
    assert chain.verify() == (True, "OK")
    _reload(monkeypatch, False)


def test_failed_storage_write_leaves_the_chain_unchanged(monkeypatch):
    mod = _reload(monkeypatch, False)
    chain = mod.AuditChain()
    chain._backend = FailingBackend()
    with pytest.raises(RuntimeError):
        chain.record(client_id="t", action="a", reason="allow", content="x")
    # Memory must not run ahead of storage: a later successful write would
    # otherwise persist a record whose predecessor never reached the store.
    assert _count(chain) == 0
