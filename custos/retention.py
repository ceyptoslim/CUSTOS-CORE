"""
custos/retention.py — Content separation and the purge path.

The audit record binds ``content_hash``, the sha256 of the request content, and
never holds the content itself. That separation is what makes a purge possible
without splicing the chain: deleting a body changes nothing the chain hashes,
so a purged chain still verifies record for record.

This module adds the piece that separation alone does not give:

- ContentStore: a side store holding the content body for each
  ``content_hash``. Bodies live here and only here, so "purge the content"
  is a deletion with a boundary rather than an edit to the record.
- A per-record CSPRNG salt with a marker inside the commitment digest.
  ``sha256(body)`` over low-entropy content is reversible by enumeration, so a
  stored digest that could be opened by guessing is not a deletion control. The
  salt is generated, never derived, and destroying it is what makes a purged
  commitment unopenable. The marker is part of the digested bytes, so a salted
  commitment can never be mistaken for a bare digest of the body, and the
  distinction is readable from the store rather than inferred from context.
- purge(): deletes body, salt and commitment together, records the deletion,
  and appends an attestation to the audit chain. The chain record carries
  ``content_hash`` so the deletion is attributable to the record it affects,
  and carries no field that would let the body be reconstructed.

reconcile() compares the record side against the store side and reports the
disagreements by name. It exists because a restore can produce a state where the
chain is green, the records say the content is held, and the store says it was
purged, with nothing comparing the two. That finding gets its own name and its own
call rather than being folded into verify(), which is a statement about the chain
and would be lying if it claimed to know anything about a store it never read.

What this does not do, stated here rather than left to be discovered: a purge
cannot reach a copy of the side store taken before it. A backup retains the
body and the salt and restoring it resurrects both. That is a property of
copies, not of this code, and the measured run in
docs/restore-drills/2026-11-06-purge-path.md shows it rather than arguing it.

Copyright (C) 2024-2026 Tavares Heath Sr. (doing business as FroLife Productions)
Licensed under the GNU Affero General Public License v3.0 (AGPL-3.0)
Commercial license available upon request.
"""

import hashlib
import secrets
import sqlite3
import time
from dataclasses import dataclass
from typing import Iterable, Optional

from .audit import (
    COMMITMENT_NONE,
    COMMITMENT_PURGED_V1,
    COMMITMENT_SALTED_V1,
    COMMITMENT_UNSALTED_V0,
    AuditChain,
)

# The marker is digested with the body, so the two commitment forms are not
# interchangeable and a bare digest cannot be presented as a salted one.
MARKER_SALTED = b"CUSTOS-COMMIT-v1:salted\x00"
MARKER_UNSALTED = b"CUSTOS-COMMIT-v0:unsalted\x00"
COMMITMENT_VERSION = 1
SALT_BYTES = 32

STATUS_PRESENT = "present"
STATUS_PURGED = "purged"
STATUS_UNKNOWN = "unknown"

# Finding kinds. Named because a caller has to be able to act on one without
# parsing prose, and because collapsing them would make a deletion look like a
# missing body.
FINDING_BODY_MISSING = "body-missing"
FINDING_UNATTESTED_PURGE = "unattested-purge"
FINDING_UNEFFECTED_PURGE = "uneffected-purge"
FINDING_KINDS = (
    FINDING_BODY_MISSING,
    FINDING_UNATTESTED_PURGE,
    FINDING_UNEFFECTED_PURGE,
)


class PurgeRefused(RuntimeError):
    """A purge was asked for that the store will not perform, or a read of
    content that no longer exists. Refused with a reason rather than returning
    an empty body, because an empty body is indistinguishable from content that
    was always empty."""


class ContentPurged(PurgeRefused):
    """The content was purged earlier. Carries the time, so a caller can report
    when rather than only that."""


class ContentStore:
    """Side store for content bodies, their salts, and their purges."""

    def __init__(self, db_path: str):
        self._path = db_path
        self._init()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS content_bodies (
                    content_hash TEXT PRIMARY KEY,
                    algo_version INTEGER NOT NULL,
                    marker TEXT NOT NULL,
                    salt BLOB,
                    commitment TEXT NOT NULL,
                    body TEXT NOT NULL,
                    created_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS purges (
                    content_hash TEXT PRIMARY KEY,
                    purged_at REAL NOT NULL,
                    reason TEXT NOT NULL,
                    attestation_hash TEXT
                )
                """
            )

    # -- writing ---------------------------------------------------------

    def put(self, body: str) -> str:
        """Store a body and return its ``content_hash``.

        Idempotent by content: a body already present keeps its original salt and
        commitment, so storing the same content twice does not produce two
        commitments for one record.
        """
        content_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM content_bodies WHERE content_hash = ?", (content_hash,)
            ).fetchone()
            if row:
                return content_hash
            purged = conn.execute(
                "SELECT purged_at FROM purges WHERE content_hash = ?", (content_hash,)
            ).fetchone()
            if purged:
                raise ContentPurged(
                    f"content {content_hash[:16]} was purged at {purged['purged_at']} "
                    "and will not be stored again; a purge that can be undone by "
                    "re-offering the same bytes is not a purge"
                )
            salt = secrets.token_bytes(SALT_BYTES)
            conn.execute(
                "INSERT INTO content_bodies (content_hash, algo_version, marker, salt,"
                " commitment, body, created_at) VALUES (?,?,?,?,?,?,?)",
                (
                    content_hash,
                    COMMITMENT_VERSION,
                    "salted-v1",
                    salt,
                    _commitment(body, salt),
                    body,
                    time.time(),
                ),
            )
        return content_hash

    def put_and_record(
        self,
        body: str,
        *,
        chain: AuditChain,
        client_id: str,
        action: str,
        reason: str,
        triggered_rule: Optional[str] = None,
        trace_id: Optional[str] = None,
        policy_digest: Optional[str] = None,
        legacy: bool = False,
    ):
        """Store the body, then record it with the form it was stored in.

        The two calls are ordered and joined here so a record cannot be written
        claiming a form the store did not use, which would defeat the marker
        exactly where it is meant to help: a reader classifying digests from
        records alone.
        """
        content_hash = self.put_legacy(body) if legacy else self.put(body)
        form = self.commitment_form(content_hash)
        return chain.record(
            client_id=client_id,
            action=action,
            reason=reason,
            content=body,
            triggered_rule=triggered_rule,
            trace_id=trace_id,
            policy_digest=policy_digest,
            commitment=form,
        )

    def put_legacy(self, body: str) -> str:
        """Store a body with no salt, for content that arrived before this store.

        Kept as a separate call rather than a flag so that an unsalted commitment
        is always an explicit choice at the call site, and the marker records what
        was actually done.
        """
        content_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO content_bodies (content_hash, algo_version,"
                " marker, salt, commitment, body, created_at) VALUES (?,?,?,?,?,?,?)",
                (
                    content_hash,
                    0,
                    "unsalted-v0",
                    None,
                    _commitment(body, None),
                    body,
                    time.time(),
                ),
            )
        return content_hash

    def purge(
        self,
        content_hash: str,
        *,
        chain: AuditChain,
        client_id: str,
        reason: str,
        trace_id: Optional[str] = None,
        policy_digest: Optional[str] = None,
    ) -> str:
        """Delete the body, salt and commitment, then attest the deletion.

        Order matters and is deliberate: the deletion happens first and the
        attestation second, so the store cannot claim a purge it did not
        perform. The cost of that ordering is stated in the failure it raises,
        because the alternative is an attestation for a body that is still
        readable.
        """
        with self._connect() as conn:
            row = conn.execute(
                "SELECT body FROM content_bodies WHERE content_hash = ?", (content_hash,)
            ).fetchone()
            if row is None:
                prior = conn.execute(
                    "SELECT purged_at FROM purges WHERE content_hash = ?", (content_hash,)
                ).fetchone()
                if prior:
                    raise ContentPurged(
                        f"content {content_hash[:16]} was already purged at "
                        f"{prior['purged_at']}"
                    )
                raise PurgeRefused(
                    f"no content at {content_hash[:16]}; a purge of something the "
                    "store never held would be recorded as a deletion that never "
                    "happened"
                )
            body = row["body"]
            conn.execute("DELETE FROM content_bodies WHERE content_hash = ?", (content_hash,))
            conn.execute(
                "INSERT INTO purges (content_hash, purged_at, reason, attestation_hash)"
                " VALUES (?,?,?,NULL)",
                (content_hash, time.time(), reason),
            )

        record = chain.record(
            client_id=client_id,
            action="PURGE",
            reason=reason,
            content=body,
            triggered_rule="retention.purge",
            trace_id=trace_id,
            policy_digest=policy_digest,
            commitment=COMMITMENT_PURGED_V1,
        )
        if record.content_hash != content_hash:
            raise RuntimeError(
                "the attestation hashed to a different content than the row that was "
                "deleted, so the deletion is not attributable to this chain record"
            )
        with self._connect() as conn:
            conn.execute(
                "UPDATE purges SET attestation_hash = ? WHERE content_hash = ?",
                (record.record_hash, content_hash),
            )
        return record.record_hash

    # -- reading ---------------------------------------------------------

    def status(self, content_hash: str) -> str:
        with self._connect() as conn:
            if conn.execute(
                "SELECT 1 FROM content_bodies WHERE content_hash = ?", (content_hash,)
            ).fetchone():
                return STATUS_PRESENT
            if conn.execute(
                "SELECT 1 FROM purges WHERE content_hash = ?", (content_hash,)
            ).fetchone():
                return STATUS_PURGED
        return STATUS_UNKNOWN

    def commitment_form(self, content_hash: str) -> str:
        """The form to bind in the record, in this build's vocabulary.

        A reader of the record alone learns which form the digest is in, which is
        the half of the marker that lives outside this store. ``purged`` maps to
        its own form because "cannot be recomputed, by design" is a different
        fact from either stored form.
        """
        marker = self.marker(content_hash)
        return {
            "salted-v1": COMMITMENT_SALTED_V1,
            "unsalted-v0": COMMITMENT_UNSALTED_V0,
            "purged": COMMITMENT_PURGED_V1,
        }.get(marker, COMMITMENT_NONE)

    def marker(self, content_hash: str) -> str:
        """``salted-v1``, ``unsalted-v0``, ``purged``, or ``unknown``.

        Read rather than inferred: the whole point of a marker is that a reader
        can tell which commitment form it is holding without being told.
        """
        with self._connect() as conn:
            row = conn.execute(
                "SELECT marker FROM content_bodies WHERE content_hash = ?", (content_hash,)
            ).fetchone()
            if row:
                return row["marker"]
            purged = conn.execute(
                "SELECT 1 FROM purges WHERE content_hash = ?", (content_hash,)
            ).fetchone()
        return "purged" if purged else "unknown"

    def open_body(self, content_hash: str) -> str:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT body FROM content_bodies WHERE content_hash = ?", (content_hash,)
            ).fetchone()
            if row:
                return row["body"]
            prior = conn.execute(
                "SELECT purged_at FROM purges WHERE content_hash = ?", (content_hash,)
            ).fetchone()
        if prior:
            raise ContentPurged(
                f"content {content_hash[:16]} was purged at {prior['purged_at']}"
            )
        raise PurgeRefused(f"no content at {content_hash[:16]}")

    def verify_commitment(self, content_hash: str, body: str) -> bool:
        """Recompute the commitment from a supplied body.

        Raises rather than returning False when the content is gone: a mismatch
        and an absence are different findings and collapsing them would let a
        purge be reported as a failed integrity check.
        """
        with self._connect() as conn:
            row = conn.execute(
                "SELECT salt, commitment FROM content_bodies WHERE content_hash = ?",
                (content_hash,),
            ).fetchone()
            if row is None:
                prior = conn.execute(
                    "SELECT purged_at FROM purges WHERE content_hash = ?", (content_hash,)
                ).fetchone()
                if prior:
                    raise ContentPurged(
                        f"content {content_hash[:16]} was purged at "
                        f"{prior['purged_at']}; the commitment cannot be recomputed"
                    )
                raise PurgeRefused(f"no content at {content_hash[:16]}")
            salt = row["salt"]
            return _commitment(body, salt) == row["commitment"]

    def purge_record(self, content_hash: str) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT content_hash, purged_at, reason, attestation_hash FROM purges"
                " WHERE content_hash = ?",
                (content_hash,),
            ).fetchone()
        return dict(row) if row else None


def _commitment(body: str, salt: Optional[bytes]) -> str:
    """Digest of marker||salt||body.

    The marker is inside the digested bytes, not alongside them, so the two
    commitment forms cannot produce the same digest and a reader holding only a
    digest cannot relabel it.
    """
    marker = MARKER_SALTED if salt else MARKER_UNSALTED
    payload = hashlib.sha256(marker)
    if salt:
        payload.update(salt[:SALT_BYTES])
    payload.update(body.encode("utf-8"))
    return payload.hexdigest()


# -- comparing the two sides ---------------------------------------------


@dataclass(frozen=True)
class Finding:
    """One disagreement between a record and the store it points at.

    ``kind`` is one of the module constants, and the three are kept distinct
    because the operational response differs: a missing body is a loss, an
    unattested purge is a restore undoing an erasure, and an uneffected purge is
    an attestation the store does not honour.
    """

    kind: str
    content_hash: str
    detail: str
    record_indexes: tuple = ()


@dataclass
class Reconciliation:
    """The result of comparing records against a store. Read-only by design."""

    findings: list
    records_read: int
    digests_examined: int

    @property
    def ok(self) -> bool:
        return not self.findings

    def by_kind(self) -> dict:
        counts = {kind: 0 for kind in FINDING_KINDS}
        for finding in self.findings:
            counts[finding.kind] = counts.get(finding.kind, 0) + 1
        return {kind: n for kind, n in counts.items() if n}

    def describe(self) -> str:
        """One line per finding, or a single line saying there were none.

        Deliberately not a boolean: a caller who only learns "false" cannot tell
        which of the three situations it is in.
        """
        if self.ok:
            return (
                f"records and store agree ({self.records_read} records, "
                f"{self.digests_examined} digests examined)"
            )
        lines = [
            f"{finding.kind} {finding.content_hash[:16]}: {finding.detail}"
            for finding in self.findings
        ]
        return "\n".join(lines)


def _field(record, name: str, default=None):
    if isinstance(record, dict):
        return record.get(name, default)
    return getattr(record, name, default)


def reconcile(records: Iterable, store: ContentStore) -> Reconciliation:
    """Compare what the records claim about content against what the store holds.

    The three things this can find, and why each is separate:

    body-missing
        A record says the digest is in a stored form and the store has neither
        the body nor a purge record. Either the content was never in this store
        (a record read against the wrong store) or it was lost without a trace.

    unattested-purge
        A record says the digest is in a stored form and the store says it was
        purged, but the chain contains no purge attestation for that digest. This
        is the shape a restore produces: an audit store restored to a point
        before an erasure, beside a content store that is past it. The deletion
        happened and nothing in the records says so.

    uneffected-purge
        The chain carries a purge attestation and the store still holds the body.
        The mirror restore: the content store rolled back under an audit store
        that recorded the deletion.

    verify() is not consulted and is not affected. A green chain is a statement
    about record linkage, and it stays true in every one of these states, which
    is exactly why the comparison has to be made somewhere else.
    """
    attested = set()
    claims: dict = {}
    records_read = 0

    for index, record in enumerate(records):
        records_read += 1
        # AuditChain.get_records() yields dicts and the in-process list yields
        # records; the comparison is about two fields, so it reads both rather
        # than forcing a caller to hand it one shape.
        commitment = _field(record, "commitment", COMMITMENT_NONE)
        content_hash = _field(record, "content_hash", "")
        if commitment == COMMITMENT_PURGED_V1:
            attested.add(content_hash)
            continue
        if commitment in (COMMITMENT_SALTED_V1, COMMITMENT_UNSALTED_V0):
            claims.setdefault(content_hash, []).append(index)

    findings = []
    for content_hash, indexes in claims.items():
        status = store.status(content_hash)
        attested_here = content_hash in attested
        if status == STATUS_PURGED and not attested_here:
            findings.append(
                Finding(
                    kind=FINDING_UNATTESTED_PURGE,
                    content_hash=content_hash,
                    record_indexes=tuple(indexes),
                    detail=(
                        "the store says this digest was purged and no record "
                        "attests the purge; the deletion is invisible in the chain"
                    ),
                )
            )
        elif status == STATUS_UNKNOWN:
            findings.append(
                Finding(
                    kind=FINDING_BODY_MISSING,
                    content_hash=content_hash,
                    record_indexes=tuple(indexes),
                    detail=(
                        "a record claims a stored form and the store holds neither "
                        "the body nor a purge record"
                    ),
                )
            )

    for content_hash in attested:
        if store.status(content_hash) == STATUS_PRESENT:
            findings.append(
                Finding(
                    kind=FINDING_UNEFFECTED_PURGE,
                    content_hash=content_hash,
                    detail=(
                        "the chain attests a purge and the store still holds the "
                        "body; the attestation does not describe this store"
                    ),
                )
            )

    return Reconciliation(
        findings=findings,
        records_read=records_read,
        digests_examined=len(claims) + len(attested - set(claims)),
    )
