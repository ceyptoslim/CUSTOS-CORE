"""Durable progress and provider-quota handling for the AgentDojo arms.

Two defects in the first runner are fixed here, and both of them would have
damaged a result rather than merely annoyed an operator.

**A quota wall was scored as a case.** ``run_agentdojo_ab.py`` turns any exception
from a case into a row carrying ``error``, and the pre-registration allows no
exclusions, so a single HTTP 429 entered the frozen record as a failed case and
stayed there. A provider refusing to serve is not an observation about the gate,
so it must stop the run instead of becoming a data point. Transient failures now
raise out of the loop as an interruption (exit 3) with the journal intact, and an
authentication failure is a refusal (exit 2) because a run without a working key
would otherwise manufacture 144 error rows and call that a measurement.

**A run that died lost every completed case.** Results and decisions were written
after the loop, so an interruption at case 130 discarded 129 observations and, at
one run per arm, the arm itself. The journal below is append-only, fsynced per
case, and bound to a digest of the run's identity: arm, model, attack, case-list
hash, case count, allowlist, pre-registration commit and suite pin. ``results`` and
``decisions`` are now views derived from the journal, so a resumed run produces
the same files a clean run would have produced.

Resumption is not a rerun. It replays only cases with no journal entry, it refuses
when the identity digest differs, and it refuses when the journal is incomplete in
a way it cannot read. There is still no flag that discards a finished arm.

Retries are recorded rather than hidden. ``max_retries=0`` is set on the provider
client on purpose, so the only retry in the stack is this one, it is bounded, and
every attempt it makes lands in the journal as an ``event`` line before the delay
is slept. A reader of the record can therefore see that a case needed three
attempts, which is the difference between a benchmark and a story.

The module imports nothing outside the standard library and does not import
AgentDojo, so it is exercised in CI where the benchmark package is absent.
"""
# Copyright (C) 2024-2026 Tavares Heath Sr. (doing business as FroLife Productions)
# Licensed under the GNU Affero General Public License v3.0 (AGPL-3.0)
# See LICENSE file for details. Commercial license available upon request.

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Mapping, Sequence

EXIT_INTERRUPTED = 3

#: Status codes that mean "the provider is busy", never "the answer is this".
TRANSIENT_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})
#: Status codes that mean the run cannot proceed at all.
AUTH_STATUS = frozenset({401, 403})

_TRANSIENT_CLASS_MARKERS = (
    "ratelimit",
    "timeout",
    "connectionerror",
    "apiconnection",
    "internalserver",
    "serviceunavailable",
    "resourceexhausted",
    "deadlineexceeded",
    "overloaded",
)
_TRANSIENT_TEXT_MARKERS = (
    "429",
    "rate limit",
    "rate_limit",
    "quota",
    "resource_exhausted",
    "resource exhausted",
    "overloaded",
    "temporarily unavailable",
    "timed out",
    "timeout",
    "connection reset",
    "503",
    "502",
    "504",
)
_AUTH_CLASS_MARKERS = ("authentication", "permissiondenied", "unauthenticated")
_AUTH_TEXT_MARKERS = (
    "invalid_api_key",
    "incorrect api key",
    "invalid api key",
    "authentication",
    "unauthenticated",
    "permission denied",
    "api key not valid",
)


class RunInterrupted(RuntimeError):
    """The run stopped for a reason that says nothing about the gate.

    Carries the exit code the caller should return and enough context for an
    operator to know whether resuming is the correct next action.
    """

    def __init__(self, message: str, *, case_id: str | None = None, attempts: int = 0):
        super().__init__(message)
        self.case_id = case_id
        self.attempts = attempts
        self.exit_code = EXIT_INTERRUPTED


class JournalConflict(RuntimeError):
    """The journal on disk does not belong to the run being attempted."""


class JournalCorrupt(RuntimeError):
    """The journal cannot be read, so its contents cannot be trusted."""


def _text(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}".lower()


def _status_codes(exc: BaseException) -> set[int]:
    """Every integer status the exception offers, without importing a provider SDK."""
    codes: set[int] = set()
    for attribute in ("status_code", "status", "http_status", "code", "http_code"):
        value = getattr(exc, attribute, None)
        if isinstance(value, int):
            codes.add(value)
        elif isinstance(value, str) and value.isdigit():
            codes.add(int(value))
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    if isinstance(status, int):
        codes.add(status)
    return codes


def is_transient(exc: BaseException) -> bool:
    """True when the provider, not the case, caused this failure."""
    if isinstance(exc, RunInterrupted):
        return True
    if is_auth_failure(exc):
        return False
    codes = _status_codes(exc)
    if codes & TRANSIENT_STATUS:
        return True
    name = type(exc).__name__.lower()
    if any(marker in name for marker in _TRANSIENT_CLASS_MARKERS):
        return True
    text = _text(exc)
    return any(marker in text for marker in _TRANSIENT_TEXT_MARKERS)


def is_auth_failure(exc: BaseException) -> bool:
    """True when no amount of waiting will make this provider answer."""
    if _status_codes(exc) & AUTH_STATUS:
        return True
    name = type(exc).__name__.lower()
    if any(marker in name for marker in _AUTH_CLASS_MARKERS):
        return True
    text = _text(exc)
    return any(marker in text for marker in _AUTH_TEXT_MARKERS)


def retry_after_seconds(exc: BaseException) -> float | None:
    """The delay the provider asked for, when it asked for one."""
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if headers is None:
        headers = getattr(exc, "headers", None)
    if not headers:
        return None
    try:
        raw = headers.get("retry-after") or headers.get("Retry-After")
    except AttributeError:
        return None
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if value >= 0 else None


@dataclass
class RetryPolicy:
    """Bounded, recorded, jittered backoff for provider-side failures only.

    ``sleep`` and ``rng`` are injectable so the tests run without waiting, which is
    the only reason a backoff is ever untested.
    """

    max_attempts: int = 5
    base_delay: float = 2.0
    max_delay: float = 60.0
    sleep: Callable[[float], None] = time.sleep
    rng: random.Random = field(default_factory=lambda: random.Random(0))
    on_retry: Callable[[int, float, BaseException], None] | None = None

    def delay_for(self, attempt: int, exc: BaseException) -> float:
        asked = retry_after_seconds(exc)
        if asked is not None:
            return min(asked, self.max_delay)
        raw = self.base_delay * (2 ** max(0, attempt - 1))
        jittered = raw * (0.5 + self.rng.random() / 2)
        return min(jittered, self.max_delay)

    def run(self, operation: Callable[[], Any], *, case_id: str | None = None) -> Any:
        attempt = 0
        while True:
            attempt += 1
            try:
                return operation()
            except BaseException as exc:  # noqa: BLE001 - classification is the point
                if is_auth_failure(exc):
                    raise
                if not is_transient(exc):
                    raise
                if attempt >= self.max_attempts:
                    raise RunInterrupted(
                        f"provider still failing after {attempt} attempts: "
                        f"{type(exc).__name__}: {exc}",
                        case_id=case_id,
                        attempts=attempt,
                    ) from exc
                delay = self.delay_for(attempt, exc)
                if self.on_retry is not None:
                    self.on_retry(attempt, delay, exc)
                self.sleep(delay)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


@dataclass
class Journal:
    """Append-only, fsynced, identity-bound record of one arm's progress.

    The header carries a digest of the binding, and every resume compares it, so a
    journal from a different model, attack or case list cannot be resumed into this
    run no matter which directory it is pointed at.
    """

    path: pathlib.Path
    VERSION = 1

    def __post_init__(self) -> None:
        self.path = pathlib.Path(self.path)

    def exists(self) -> bool:
        return self.path.exists() and self.path.stat().st_size > 0

    @staticmethod
    def binding(
        *,
        arm: str,
        model: str,
        attack: str,
        case_list_sha256: str,
        case_count: int,
        allowlist: Iterable[str],
        prereg_commit: str,
        suite_pin: str,
    ) -> dict[str, Any]:
        """The identity a resumed run must match exactly."""
        return {
            "journal_version": Journal.VERSION,
            "arm": arm,
            "model": model,
            "attack": attack,
            "case_list_sha256": case_list_sha256,
            "case_count": int(case_count),
            "allowlist": sorted(allowlist),
            "prereg_commit": prereg_commit,
            "suite_pin": suite_pin,
        }

    @staticmethod
    def digest(binding: Mapping[str, Any]) -> str:
        return hashlib.sha256(_canonical(binding)).hexdigest()

    def _write_line(self, payload: Mapping[str, Any]) -> None:
        line = json.dumps(payload, sort_keys=True) + "\n"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())

    def start(self, binding: Mapping[str, Any]) -> None:
        """Open a new journal. Refuses to write over an existing one."""
        if self.exists():
            raise JournalConflict(
                f"{self.path} already holds a journal; resume it instead of starting over"
            )
        self._write_line(
            {
                "type": "header",
                "journal_version": self.VERSION,
                "binding": dict(binding),
                "binding_sha256": self.digest(binding),
                "opened_utc": _utc_now(),
            }
        )

    def append_case(
        self,
        case_id: str,
        row: Mapping[str, Any],
        decisions: Sequence[Mapping[str, Any]] = (),
    ) -> None:
        self._write_line(
            {
                "type": "case",
                "case_id": case_id,
                "row": dict(row),
                "decisions": [dict(record) for record in decisions],
                "recorded_utc": _utc_now(),
            }
        )

    def append_event(self, event: str, **fields: Any) -> None:
        self._write_line({"type": "event", "event": event, "recorded_utc": _utc_now(), **fields})

    def append_abort(self, reason: str, **fields: Any) -> None:
        self._write_line(
            {"type": "abort", "reason": reason, "recorded_utc": _utc_now(), **fields}
        )

    def read(self) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """Return ``(header, entries)`` or raise, never returning a half-read journal.

        A truncated final line is the signature of a crash mid-write, and the one
        thing that must not happen is reading it as a completed case.
        """
        if not self.exists():
            raise JournalCorrupt(f"{self.path} does not exist")
        raw_lines = self.path.read_text(encoding="utf-8").splitlines()
        header: dict[str, Any] | None = None
        entries: list[dict[str, Any]] = []
        for index, raw in enumerate(raw_lines, start=1):
            if not raw.strip():
                continue
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise JournalCorrupt(
                    f"{self.path} line {index} is not valid JSON ({exc}). A partial "
                    "line means a case was being written when the process died; "
                    "remove that final line only if it is the last one, then resume."
                ) from exc
            if payload.get("type") == "header":
                if header is not None:
                    raise JournalCorrupt(f"{self.path} holds more than one header")
                header = payload
            else:
                entries.append(payload)
        if header is None:
            raise JournalCorrupt(f"{self.path} has no header; it is not a journal")
        return header, entries

    def open_resume(self, binding: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
        """Verify identity and return the cases already recorded."""
        header, entries = self.read()
        recorded = header.get("binding_sha256")
        expected = self.digest(binding)
        if recorded != expected:
            raise JournalConflict(
                "journal belongs to a different run: recorded digest "
                f"{recorded}, this invocation computes {expected}. Refusing to "
                "resume across changed arms."
            )
        if header.get("binding") != dict(binding):
            raise JournalConflict(
                "journal digest matched but its binding fields differ, which should "
                "be impossible; refusing rather than trusting the digest alone"
            )
        completed: dict[str, dict[str, Any]] = {}
        for entry in entries:
            if entry.get("type") == "case":
                completed[entry["case_id"]] = {
                    "row": entry.get("row", {}),
                    "decisions": entry.get("decisions", []),
                }
        return completed


class RetryingQuery:
    """Wrap a pipeline model element so provider failures back off instead of scoring.

    Duck-typed on purpose: importing AgentDojo here would make this module
    unavailable in CI, where the benchmark package is an optional extra and the
    only place these branches can be tested without a provider.
    """

    def __init__(
        self,
        inner: Any,
        policy: RetryPolicy,
        *,
        case_id: str = "",
        name: str | None = None,
    ) -> None:
        self.inner = inner
        self.policy = policy
        self.case_id = case_id
        self.name = name or getattr(inner, "name", None) or "retrying-query"

    def query(self, query, runtime, env=None, messages=(), extra_args=None):
        def attempt():
            return self.inner.query(
                query,
                runtime,
                env,
                list(messages),
                dict(extra_args or {}),
            )

        return self.policy.run(attempt, case_id=self.case_id or None)
