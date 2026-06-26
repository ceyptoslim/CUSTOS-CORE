"""
CUSTOS Rate Limiter
Near production-ready. Key fix applied: list(self._quotas.keys()) prevents
dict mutation during iteration in get_all_quotas().
"""

import threading
import time
from dataclasses import dataclass, field
from typing import Dict


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
        self._quotas: Dict[str, QuotaConfig] = {}
        self._state: Dict[str, QuotaState] = {}
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

    def get_all_quotas(self) -> Dict[str, dict]:
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
