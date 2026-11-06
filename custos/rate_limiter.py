"""
CUSTOS Rate Limiter
Near production-ready. Key fix applied: list(self._quotas.keys()) prevents
dict mutation during iteration in get_all_quotas().
"""
# Copyright (C) 2024-2026 Tavares Heath Sr. (doing business as FroLife Productions)
# Licensed under the GNU Affero General Public License v3.0 (AGPL-3.0)
# See LICENSE file for details. Commercial license available upon request.



import math
import threading
import time
from dataclasses import dataclass, field



@dataclass
class QuotaConfig:
    requests_per_minute: int
    requests_per_hour: int
    tokens_per_minute: int = 100_000


@dataclass
class QuotaState:
    minute_count: int = 0
    hour_count: int = 0
    token_count: int = 0
    minute_window_start: float = field(default_factory=time.time)
    hour_window_start: float = field(default_factory=time.time)


class RateLimiter:
    def __init__(self):
        self._quotas: dict[str, QuotaConfig] = {}
        self._state: dict[str, QuotaState] = {}
        self._lock = threading.RLock()  # RLock prevents re-entrant deadlock

    def register(self, client_id: str, config: QuotaConfig) -> None:
        with self._lock:
            self._quotas[client_id] = config
            self._state[client_id] = QuotaState()

    def check_and_consume(self, client_id: str, tokens: int = 1) -> tuple[bool, str]:
        with self._lock:
            if client_id not in self._quotas:
                return False, f"Unknown client: {client_id}"

            config = self._quotas[client_id]
            state = self._state[client_id]
            now = time.time()

            # Reset minute window
            if now - state.minute_window_start >= 60:
                state.minute_count = 0
                state.token_count = 0
                state.minute_window_start = now

            # Reset hour window
            if now - state.hour_window_start >= 3600:
                state.hour_count = 0
                state.hour_window_start = now

            if state.minute_count >= config.requests_per_minute:
                return False, "Minute request quota exceeded"

            if state.hour_count >= config.requests_per_hour:
                return False, "Hour request quota exceeded"

            if state.token_count + tokens > config.tokens_per_minute:
                return False, "Token quota exceeded"

            state.minute_count += 1
            state.hour_count += 1
            state.token_count += tokens
            return True, "OK"

    def retry_after_seconds(self, client_id: str, tokens: int = 1) -> int | None:
        """Seconds until the first exceeded quota window resets, or None.

        Read-only mirror of check_and_consume(): it consumes nothing and does
        not advance a window, so a caller can ask "how long" after a refusal
        without changing the refusal. Window resets are applied the same way
        check_and_consume() applies them, so an elapsed window reports None
        rather than a stale wait.

        None means no quota is currently exceeded, which includes an unknown
        key (a configuration fault, not a rate-limit refusal). Callers should
        omit Retry-After in that case rather than invent a wait that has no
        window behind it.
        """
        with self._lock:
            config = self._quotas.get(client_id)
            state = self._state.get(client_id)
            if config is None or state is None:
                return None

            now = time.time()
            minute_left = 60.0 - (now - state.minute_window_start)
            hour_left = 3600.0 - (now - state.hour_window_start)
            minute_elapsed = minute_left <= 0
            hour_elapsed = hour_left <= 0

            minute_count = 0 if minute_elapsed else state.minute_count
            token_count = 0 if minute_elapsed else state.token_count
            hour_count = 0 if hour_elapsed else state.hour_count

            if minute_count >= config.requests_per_minute:
                return max(1, math.ceil(minute_left))
            if hour_count >= config.requests_per_hour:
                return max(1, math.ceil(hour_left))
            if token_count + tokens > config.tokens_per_minute:
                return max(1, math.ceil(minute_left))
            return None

    def get_quota(self, client_id: str) -> QuotaConfig | None:
        """Return the registered QuotaConfig for a key, or None.

        Unlike get_all_quotas() (a display dump), this returns the raw
        config object so callers can inherit it for new keys.
        """
        with self._lock:
            return self._quotas.get(client_id)

    def get_all_quotas(self) -> dict[str, dict]:
        """
        FIX APPLIED: list(self._quotas.keys()) snapshot prevents
        RuntimeError from dict mutation during iteration.
        """
        with self._lock:
            result = {}
            for client_id in list(self._quotas.keys()):
                config = self._quotas[client_id]
                state = self._state[client_id]
                result[client_id] = {
                    "requests_per_minute": config.requests_per_minute,
                    "requests_per_hour": config.requests_per_hour,
                    "tokens_per_minute": config.tokens_per_minute,
                    "current_minute_count": state.minute_count,
                    "current_hour_count": state.hour_count,
                    "current_token_count": state.token_count,
                }
            return result

    def unregister(self, client_id: str) -> bool:
        with self._lock:
            if client_id in self._quotas:
                del self._quotas[client_id]
                del self._state[client_id]
                return True
            return False
