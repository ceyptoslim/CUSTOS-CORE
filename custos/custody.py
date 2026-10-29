"""
custos/custody.py — External custody of audit chain heads.

Implements docs/design/chain-head-custody.md (PR #60):

- AnchorRecord: hash-chained, per-tenant anchor over (epoch, chain_length,
  head_hash). Anchors form their own chain so reordering, dropping, or
  substituting an anchor is detectable.
- CustodySink: append-only external custody target. GitAnchorSink commits
  anchors to an external git repository (append rights, not history-rewrite
  rights — the red-proof pattern generalized to deployment). TSAAnchorSink
  obtains an RFC 3161 timestamp over the anchor (token stored as opaque
  bytes; verify externally with `openssl ts -verify`).
- AnchorManager: background anchoring every N records / T seconds per
  tenant. Fail-visible, not fail-blocking: a sink outage never blocks
  enforcement; the gap is recorded in the next successful anchor and
  surfaced through health()/metrics.
- verify_custody(): the external re-walk. Recomputes the record chain from
  a backend copy, reconciles it against the external anchor log, and emits
  ESTABLISHED / CANNOT ESTABLISH / CONTRADICTION per proposition. The
  verification path never loads evidence from the system under
  investigation alone.

Custody is additive and disabled by default (CUSTOS_CUSTODY_ENABLED).

Copyright (C) 2024-2026 FroLife Productions
Licensed under the GNU Affero General Public License v3.0 (AGPL-3.0)
Commercial license available upon request.
"""

import collections
import hashlib
import json
import os
import subprocess
import threading
import urllib.request
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional, Tuple

from custos.audit import compute_record_hash

GENESIS_ANCHOR_HASH = "0" * 64
_GENESIS_RECORD_HASH = "0" * 64

ESTABLISHED = "ESTABLISHED"
CANNOT_ESTABLISH = "CANNOT ESTABLISH"
CONTRADICTION = "CONTRADICTION"


# ---------------------------------------------------------------------------
# Anchor records
# ---------------------------------------------------------------------------

@dataclass
class AnchorRecord:
    """A per-tenant snapshot of the audit chain head, externally anchored."""

    tenant_id: str
    epoch: int
    chain_length: int
    head_hash: str
    anchored_at_utc: str
    prev_anchor_hash: str
    gap: Optional[dict] = None
    anchor_hash: str = ""

    def compute_hash(self) -> str:
        payload = json.dumps(
            {
                "tenant_id": self.tenant_id,
                "epoch": self.epoch,
                "chain_length": self.chain_length,
                "head_hash": self.head_hash,
                "anchored_at_utc": self.anchored_at_utc,
                "prev_anchor_hash": self.prev_anchor_hash,
                "gap": self.gap,
            },
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "AnchorRecord":
        return AnchorRecord(
            tenant_id=d["tenant_id"],
            epoch=int(d["epoch"]),
            chain_length=int(d["chain_length"]),
            head_hash=d["head_hash"],
            anchored_at_utc=d["anchored_at_utc"],
            prev_anchor_hash=d["prev_anchor_hash"],
            gap=d.get("gap"),
            anchor_hash=d.get("anchor_hash", ""),
        )


@dataclass
class PolicyCommitRecord(AnchorRecord):
    """An anchored policy-commit citation object (R3).

    Same append-only custody machinery as chain-head anchors: the system
    appends a commitment of the in-force policy set to the sinks, but can
    never rewrite one. head_hash carries the policy digest; canonical_json
    carries the exact canonical bytes the digest was computed from, so a
    third party re-hashes the commitment and compares it against the digest
    cited by runtime records — one step, never two reconciled assertions.
    """

    kind: str = "policy_commit"
    canonical_json: str = ""

    def compute_hash(self) -> str:
        payload = json.dumps(
            {
                "tenant_id": self.tenant_id,
                "epoch": self.epoch,
                "head_hash": self.head_hash,
                "anchored_at_utc": self.anchored_at_utc,
                "prev_anchor_hash": self.prev_anchor_hash,
                "kind": self.kind,
                "canonical_json": self.canonical_json,
            },
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def from_dict(d: dict) -> "PolicyCommitRecord":
        return PolicyCommitRecord(
            tenant_id=d["tenant_id"],
            epoch=int(d["epoch"]),
            chain_length=int(d.get("chain_length", 0)),
            head_hash=d["head_hash"],
            anchored_at_utc=d["anchored_at_utc"],
            prev_anchor_hash=d["prev_anchor_hash"],
            kind=d.get("kind", "policy_commit"),
            canonical_json=d.get("canonical_json", ""),
            anchor_hash=d.get("anchor_hash", ""),
        )


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Custody sinks
# ---------------------------------------------------------------------------

class CustodySink(ABC):
    """Append-only external custody target for anchor records.

    A sink holds anchors somewhere the deployment cannot silently rewrite.
    Sinks are write-path infrastructure only: verification never depends on
    the deployment's cooperation beyond the anchors it already published.
    """

    name: str = "sink"

    @abstractmethod
    def append(self, anchor: AnchorRecord) -> str:
        """Persist one anchor; returns a sink reference (e.g. commit sha)."""

    @abstractmethod
    def healthcheck(self) -> bool:
        """Cheap liveness check; used for fail-visible surfacing."""


class MemorySink(CustodySink):
    """In-memory sink — TESTING ONLY. Provides no external custody."""

    name = "memory"

    def __init__(self) -> None:
        self.anchors: List[AnchorRecord] = []
        self._fail = False

    def append(self, anchor: AnchorRecord) -> str:
        if self._fail:
            raise RuntimeError("memory sink: simulated outage")
        self.anchors.append(anchor)
        return f"memory:{anchor.epoch}"

    def healthcheck(self) -> bool:
        return not self._fail

    def fail(self, flag: bool) -> None:
        """Test hook: simulate a sink outage."""
        self._fail = flag


class GitAnchorSink(CustodySink):
    """Commits anchors into an external git repository.

    The repository must be a working clone the process may commit to but
    whose history it cannot silently rewrite (branch protection on the
    external host; append rights only). This is the red-proof pattern
    generalized to deployment. Honest boundary: an org-admin compromise of
    the external host can bypass branch protection; a public mirror narrows
    that to detectable collusion, not impossibility.
    """

    name = "git"

    def __init__(self, repo_path: str, branch: str = "main") -> None:
        self._repo = repo_path
        self._branch = branch
        self._local_config()

    def _local_config(self) -> None:
        subprocess.run(
            ["git", "config", "user.name", "custos-custody"],
            cwd=self._repo, check=True, capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.email", "custody@custos.invalid"],
            cwd=self._repo, check=True, capture_output=True,
        )

    def append(self, anchor: AnchorRecord) -> str:
        rel = os.path.join(
            "anchors", anchor.tenant_id, f"epoch-{anchor.epoch}.json"
        )
        path = os.path.join(self._repo, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(anchor.to_dict(), fh, indent=2, sort_keys=True)
        subprocess.run(["git", "add", rel], cwd=self._repo, check=True,
                       capture_output=True)
        msg = f"custody anchor {anchor.tenant_id} epoch {anchor.epoch}"
        subprocess.run(
            ["git", "commit", "-m", msg],
            cwd=self._repo, check=True, capture_output=True,
        )
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=self._repo, check=True, capture_output=True, text=True,
        )
        return sha.stdout.strip()

    def healthcheck(self) -> bool:
        try:
            subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=self._repo, check=True, capture_output=True,
            )
            return True
        except Exception:
            return False

    def load_anchors(self) -> List[dict]:
        """Read back every anchor JSON committed under anchors/."""
        out: List[dict] = []
        base = os.path.join(self._repo, "anchors")
        if not os.path.isdir(base):
            return out
        for root, _dirs, files in os.walk(base):
            for fn in sorted(files):
                if fn.endswith(".json"):
                    with open(os.path.join(root, fn), encoding="utf-8") as fh:
                        out.append(json.load(fh))
        out.sort(key=lambda d: int(d["epoch"]))
        return out


# ---------------------------------------------------------------------------
# RFC 3161 (TSA) sink
# ---------------------------------------------------------------------------

def _der_len(n: int) -> bytes:
    if n < 0x80:
        return bytes([n])
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return bytes([0x80 | len(raw)]) + raw


def _der_tlv(tag: int, value: bytes) -> bytes:
    return bytes([tag]) + _der_len(len(value)) + value


def build_tsa_request(data: bytes, nonce: int) -> bytes:
    """Minimal RFC 3161 TimeStampReq for a SHA-256 digest of `data`."""
    digest = hashlib.sha256(data).digest()
    oid_sha256 = bytes.fromhex("0609608648016503040201")
    algorithm_id = _der_tlv(0x30, oid_sha256 + _der_tlv(0x05, b""))
    message_imprint = _der_tlv(0x30, algorithm_id + _der_tlv(0x04, digest))
    version = _der_tlv(0x02, b"\x01")
    nonce = _der_tlv(0x02, nonce.to_bytes(max(1, (nonce.bit_length() + 7) // 8), "big"))
    cert_req = _der_tlv(0x01, b"\xff")
    return _der_tlv(0x30, version + message_imprint + nonce + cert_req)


class TSAAnchorSink(CustodySink):
    """RFC 3161 timestamp over the anchor; token stored as opaque bytes.

    The token is third-party evidence (TSA signature over digest+time).
    Verify externally: `openssl ts -verify -data anchor.json -in token.tsr
    -CAfile tsa.pem`. No CRL/OCSP handling here; that is the verifier's job.
    """

    name = "tsa"

    def __init__(self, url: str, token_dir: str) -> None:
        self._url = url
        self._dir = token_dir
        os.makedirs(self._dir, exist_ok=True)

    def append(self, anchor: AnchorRecord) -> str:
        canonical = json.dumps(anchor.to_dict(), sort_keys=True).encode("utf-8")
        nonce = uuid.uuid4().int >> 64
        request = build_tsa_request(canonical, nonce)
        req = urllib.request.Request(
            self._url,
            data=request,
            headers={"Content-Type": "application/timestamp-query"},
            method="POST",
        )
        # The TSA URL is operator-configured infrastructure
        # (CUSTOS_CUSTODY_TSA_URL), not attacker-controlled input — same
        # trust posture as the execution adapter's configurable targets.
        with urllib.request.urlopen(req, timeout=10) as resp:  # nosec B310
            token = resp.read()
        rel = os.path.join(anchor.tenant_id, f"epoch-{anchor.epoch}.tsr")
        path = os.path.join(self._dir, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(token)
        return f"tsa:{anchor.epoch}"

    def healthcheck(self) -> bool:
        return bool(self._url)


# ---------------------------------------------------------------------------
# AnchorManager
# ---------------------------------------------------------------------------

class AnchorManager:
    """Background anchoring of audit chain heads, per tenant.

    Fail-visible, not fail-blocking: enforcement never waits on a sink.
    Every anchor attempt either lands in all healthy sinks or is recorded
    as a growing gap that the next successful anchor carries in-band.
    """

    def __init__(
        self,
        sinks: List[CustodySink],
        get_chains: Callable[[], Dict[str, "object"]],
        anchor_n: int = 50,
        anchor_t: float = 300.0,
    ) -> None:
        self._sinks = sinks
        self._get_chains = get_chains
        self._anchor_n = max(1, int(anchor_n))
        self._anchor_t = max(0.05, float(anchor_t))
        self._lock = threading.Lock()
        self._state: Dict[str, dict] = {}
        self._policy_state: Dict[str, dict] = {}
        self._policy_queue: "collections.deque" = collections.deque()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.last_error: Optional[str] = None

    # -- state ----------------------------------------------------------

    def _tenant_state(self, tenant_id: str) -> dict:
        if tenant_id not in self._state:
            self._state[tenant_id] = {
                "epoch": 0,
                "length": 0,
                "anchor_hash": GENESIS_ANCHOR_HASH,
                "last_anchor_utc": None,
                "pending_gap": None,
            }
        return self._state[tenant_id]

    # -- anchoring ------------------------------------------------------

    def anchor_due(self, force: bool = False) -> None:
        """Anchor every tenant whose chain advanced by >= anchor_n."""
        self.drain_policy_commits()
        for tenant_id, chain in self._get_chains().items():
            length, head = chain.head()
            st = self._tenant_state(tenant_id)
            if force or (length - st["length"]) >= self._anchor_n:
                self._emit(tenant_id, length, head)

    # -- policy-commit anchoring (R3) ---------------------------------

    def anchor_policy_commit(
        self, tenant_id: str, digest: str, canonical_json: str
    ) -> None:
        """Queue an anchored commitment of a new in-force policy set.

        Asynchronous and fail-visible: never blocks enforcement. A sink
        outage leaves the commit unanchored and the external re-walk
        surfaces the next records' citations as unanchored
        (CONTRADICTION) — the gap is carried in-band, never hidden.
        Failed commits are requeued and retried on later ticks.
        """
        with self._lock:
            self._policy_queue.append((tenant_id, digest, canonical_json))

    def drain_policy_commits(self) -> bool:
        """Emit queued policy commits to all sinks (called by the anchor loop).

        Returns True when every drained commit landed in all sinks; False
        means at least one sink was unhealthy and the failed commits were
        requeued for retry on a later tick (fail-visible, never blocking).
        """
        failed = []
        while True:
            with self._lock:
                if not self._policy_queue:
                    break
                tenant_id, digest, canonical_json = self._policy_queue.popleft()
            if not self._emit_policy_commit(tenant_id, digest, canonical_json):
                failed.append((tenant_id, digest, canonical_json))
        if failed:
            with self._lock:
                for item in reversed(failed):
                    self._policy_queue.appendleft(item)
        return not failed

    def _emit_policy_commit(
        self, tenant_id: str, digest: str, canonical_json: str
    ) -> None:
        st = self._policy_state.setdefault(
            f"policy::{tenant_id}",
            {"epoch": 0, "anchor_hash": GENESIS_ANCHOR_HASH},
        )
        commit = PolicyCommitRecord(
            tenant_id=tenant_id,
            epoch=st["epoch"] + 1,
            chain_length=0,
            head_hash=digest,
            anchored_at_utc=_utc_now(),
            prev_anchor_hash=st["anchor_hash"],
            kind="policy_commit",
            canonical_json=canonical_json,
        )
        commit.anchor_hash = commit.compute_hash()

        errors: List[str] = []
        for sink in self._sinks:
            try:
                sink.append(commit)
            except Exception as exc:  # noqa: BLE001 — fail-visible, never fail-blocking
                errors.append(f"{sink.name}: {exc}")

        if errors:
            # Fail-visible: surface the outage, do not advance state; the
            # caller requeues for retry on a later tick.
            self.last_error = "policy_commit: " + "; ".join(errors)
            return False
        st["epoch"] += 1
        st["anchor_hash"] = commit.anchor_hash
        return True

    def _emit(self, tenant_id: str, length: int, head: str) -> None:
        st = self._tenant_state(tenant_id)
        anchor = AnchorRecord(
            tenant_id=tenant_id,
            epoch=st["epoch"] + 1,
            chain_length=length,
            head_hash=head,
            anchored_at_utc=_utc_now(),
            prev_anchor_hash=st["anchor_hash"],
            gap=st["pending_gap"],
        )
        anchor.anchor_hash = anchor.compute_hash()

        refs: List[Tuple[str, str]] = []
        errors: List[str] = []
        for sink in self._sinks:
            try:
                refs.append((sink.name, sink.append(anchor)))
            except Exception as exc:  # fail-visible: record, never raise
                errors.append(f"{sink.name}: {exc}")
        if errors:
            gap = st["pending_gap"] or {
                "from_epoch": anchor.epoch,
                "attempts": 0,
                "first_attempt_utc": anchor.anchored_at_utc,
            }
            gap["attempts"] += 1
            gap["last_attempt_utc"] = anchor.anchored_at_utc
            st["pending_gap"] = gap
            self.last_error = "; ".join(errors)
            return

        st["epoch"] = anchor.epoch
        st["length"] = length
        st["anchor_hash"] = anchor.anchor_hash
        st["last_anchor_utc"] = anchor.anchored_at_utc
        st["pending_gap"] = None
        self.last_error = None

    # -- background loop -------------------------------------------------

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name="custos-custody", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def _loop(self) -> None:
        while not self._stop.wait(self._anchor_t):
            try:
                self.anchor_due()
            except Exception:  # pragma: no cover - defensive
                continue

    # -- health ----------------------------------------------------------

    def health(self) -> dict:
        """Fail-visible surface for /ready and /metrics."""
        tenants = {}
        stale_after = 2 * self._anchor_t
        with self._lock:
            for tenant_id, st in self._state.items():
                age = None
                if st["last_anchor_utc"]:
                    dt = datetime.strptime(
                        st["last_anchor_utc"], "%Y-%m-%dT%H:%M:%SZ"
                    ).replace(tzinfo=timezone.utc)
                    age = (datetime.now(timezone.utc) - dt).total_seconds()
                tenants[tenant_id] = {
                    "epoch": st["epoch"],
                    "pending_gap": st["pending_gap"] is not None,
                    "anchor_age_seconds": age,
                    "stale": age is not None and age > stale_after,
                }
        sinks_ok = all(s.healthcheck() for s in self._sinks) if self._sinks else False
        return {
            "sinks": [s.name for s in self._sinks],
            "sinks_healthy": sinks_ok,
            "tenants": tenants,
            "last_error": self.last_error,
        }


# ---------------------------------------------------------------------------
# External verification
# ---------------------------------------------------------------------------

def _record_hash(record: dict, previous_hash: str) -> str:
    """Recompute the record hash with the emitter's own preimage.

    Delegates to custos.audit.compute_record_hash so the external re-walk and
    the internal chain cannot drift apart: the citation (policy_digest), the
    tenant binding and the trace binding are all part of what gets recomputed,
    not silently dropped from the external view.
    """
    return compute_record_hash(record, previous_hash)


def verify_custody(records: List[dict], anchors: List[dict]) -> dict:
    """External re-walk of a backend copy against an external anchor log.

    `records` is a copy of the audit store as dicts (AuditRecord.to_dict).
    `anchors` is the externally held anchor log (any order; sorted here).

    Propositions:
      P1 record-chain internal consistency (recomputed from the copy)
      P2 every anchored head matches the recomputed record hash at that length
      P3 anchor-chain integrity (epochs, prev links, anchor hashes)
      P4 store completeness against the anchors (truncation detection)

    Verdicts: ESTABLISHED / CANNOT ESTABLISH / CONTRADICTION.

    P2 is the boundary the internal chain cannot draw: a consistent
    rewrite-and-rehash of the store passes P1 and fails P2, because the
    recomputed head no longer matches the externally anchored head.
    """
    policy_commit_dicts = [
        a for a in anchors if a.get("kind") == "policy_commit"
    ]
    head_anchor_dicts = [
        a for a in anchors if a.get("kind") != "policy_commit"
    ]
    anchors = sorted(
        [AnchorRecord.from_dict(a) for a in head_anchor_dicts],
        key=lambda a: a.epoch,
    )
    verdicts: Dict[str, str] = {}
    detail: Dict[str, object] = {}

    # -- P1: recompute the record chain --------------------------------
    prev = _GENESIS_RECORD_HASH
    p1 = ESTABLISHED
    recomputed: List[str] = []
    for i, rec in enumerate(records):
        if rec.get("previous_hash") != prev:
            p1 = CONTRADICTION
            detail["p1_break"] = f"record {i}: previous_hash mismatch"
            prev = rec.get("record_hash", "")
            recomputed.append(prev)
            continue
        expected = _record_hash(rec, prev)
        if rec.get("record_hash") != expected:
            p1 = CONTRADICTION
            detail.setdefault("p1_break", f"record {i}: hash mismatch")
        recomputed.append(expected)
        prev = expected
    verdicts["P1_record_chain_consistency"] = p1

    # -- P3: anchor-chain integrity ------------------------------------
    if not anchors:
        verdicts["P3_anchor_chain_integrity"] = CANNOT_ESTABLISH
    else:
        p3 = ESTABLISHED
        prev_anch = GENESIS_ANCHOR_HASH
        last_epoch = 0
        for a in anchors:
            if a.epoch <= last_epoch:
                p3 = CONTRADICTION
                detail["p3_break"] = f"epoch not strictly increasing at {a.epoch}"
                break
            if a.prev_anchor_hash != prev_anch:
                p3 = CONTRADICTION
                detail["p3_break"] = f"anchor {a.epoch}: prev link mismatch"
                break
            if a.anchor_hash != a.compute_hash():
                p3 = CONTRADICTION
                detail["p3_break"] = f"anchor {a.epoch}: hash mismatch"
                break
            prev_anch = a.anchor_hash
            last_epoch = a.epoch
        verdicts["P3_anchor_chain_integrity"] = p3

    # -- P2: anchored heads match the recomputed chain ------------------
    if not anchors:
        verdicts["P2_anchored_heads_match_store"] = CANNOT_ESTABLISH
    else:
        p2 = ESTABLISHED
        for a in anchors:
            if a.chain_length < 1 or a.chain_length > len(recomputed):
                p2 = CONTRADICTION
                detail["p2_break"] = (
                    f"anchor {a.epoch}: chain_length {a.chain_length} outside "
                    f"store length {len(recomputed)} (truncated or forged)"
                )
                break
            head = recomputed[a.chain_length - 1]
            if head != a.head_hash:
                p2 = CONTRADICTION
                detail["p2_break"] = (
                    f"anchor {a.epoch}: recomputed head {head[:12]}… != "
                    f"anchored head {a.head_hash[:12]}… (rewrite detected)"
                )
                break
        verdicts["P2_anchored_heads_match_store"] = p2

    # -- P4: store completeness against anchors --------------------------
    if not anchors:
        verdicts["P4_store_completeness"] = CANNOT_ESTABLISH
    else:
        last = max(a.chain_length for a in anchors)
        if len(records) < last:
            verdicts["P4_store_completeness"] = CONTRADICTION
            detail["p4_break"] = (
                f"store holds {len(records)} records; anchors cover {last} "
                "(truncation detected)"
            )
        else:
            verdicts["P4_store_completeness"] = ESTABLISHED
            detail["p4_note"] = (
                f"anchored prefix: {last}/{len(records)} records; "
                f"{len(records) - last} records newer than the last anchor "
                "are covered by the next anchor"
            )

    # -- P5/P6: policy-commit citation dimension (R3/R4) ------------------
    # Additive (R5): when no citations and no policy commits exist, the
    # dimension is absent and no P5/P6 keys are reported — stores that
    # predate citation keep their P1-P4 verdicts byte-identically.
    if policy_commit_dicts:
        p5 = ESTABLISHED
        for d in policy_commit_dicts:
            pc = PolicyCommitRecord.from_dict(d)
            if pc.anchor_hash != pc.compute_hash():
                p5 = CONTRADICTION
                detail["p5_break"] = f"policy commit {pc.epoch}: hash mismatch"
                break
            if (
                hashlib.sha256(
                    pc.canonical_json.encode("utf-8")
                ).hexdigest()
                != pc.head_hash
            ):
                p5 = CONTRADICTION
                detail["p5_break"] = (
                    f"policy commit {pc.epoch}: canonical_json does not "
                    "re-hash to the committed digest"
                )
                break
        verdicts["P5_policy_commit_integrity"] = p5

    anchored_digests: Dict[str, set] = {}
    for d in policy_commit_dicts:
        anchored_digests.setdefault(d["tenant_id"], set()).add(d["head_hash"])
    cited = [
        (i, rec.get("tenant_id") or rec.get("client_id", ""),
         rec.get("policy_digest", ""))
        for i, rec in enumerate(records)
        if rec.get("policy_digest")
    ]
    if cited:
        p6 = ESTABLISHED
        unanchored = []
        for i, tenant, dg in cited:
            if dg not in anchored_digests.get(tenant, set()):
                unanchored.append({"record": i, "tenant": tenant, "digest": dg})
        if unanchored:
            p6 = CONTRADICTION
            detail["p6_unanchored_citations"] = unanchored
        verdicts["P6_citation_membership"] = p6

    overall = (
        CONTRADICTION if CONTRADICTION in verdicts.values()
        else (ESTABLISHED if all(v == ESTABLISHED for v in verdicts.values())
              else CANNOT_ESTABLISH)
    )
    return {"verdicts": verdicts, "overall": overall, "detail": detail}


# ---------------------------------------------------------------------------
# Configuration helper (main.py wiring)
# ---------------------------------------------------------------------------

def build_custody_from_env(get_chains: Callable[[], Dict[str, object]]) -> Optional[AnchorManager]:
    """Build an AnchorManager from CUSTOS_CUSTODY_* env; None when disabled."""
    enabled = os.getenv("CUSTOS_CUSTODY_ENABLED", "").strip().lower() in ("1", "true", "yes")
    if not enabled:
        return None
    sink_names = [
        s.strip().lower()
        for s in os.getenv("CUSTOS_CUSTODY_SINKS", "git").split(",")
        if s.strip()
    ]
    sinks: List[CustodySink] = []
    for name in sink_names:
        if name == "git":
            repo = os.getenv("CUSTOS_CUSTODY_GIT_REPO", "").strip()
            if not repo:
                raise RuntimeError(
                    "CUSTOS_CUSTODY_GIT_REPO is required for the git sink"
                )
            sinks.append(GitAnchorSink(repo))
        elif name == "tsa":
            url = os.getenv("CUSTOS_CUSTODY_TSA_URL", "").strip()
            if not url:
                raise RuntimeError(
                    "CUSTOS_CUSTODY_TSA_URL is required for the tsa sink"
                )
            token_dir = os.getenv("CUSTOS_CUSTODY_TSA_DIR", "custody-tokens")
            sinks.append(TSAAnchorSink(url, token_dir))
        else:
            raise RuntimeError(f"unknown custody sink: {name}")
    if not sinks:
        raise RuntimeError("CUSTOS_CUSTODY_ENABLED but no sinks configured")
    anchor_n = int(os.getenv("CUSTOS_CUSTODY_ANCHOR_N", "50"))
    anchor_t = float(os.getenv("CUSTOS_CUSTODY_ANCHOR_T", "300"))
    return AnchorManager(sinks, get_chains, anchor_n=anchor_n, anchor_t=anchor_t)
