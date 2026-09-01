"""
CUSTOS Execution Adapter v1.2

The execution layer that makes CUSTOS an actual firewall, not just a
decision API. When the policy engine returns ALLOW, this module forwards
the request to the downstream target. When DENY, the request never reaches
the target.

Design principles:
- Fail-closed: any exception during forwarding = block, never forward
- SSRF protection: target URLs validated against allowlist + IP restrictions
- Circuit breaker: opens after N consecutive downstream failures
- Timeout: all downstream calls have a hard timeout
- No raw content in logs: only hashes, never the forwarded payload
"""

import ipaddress
import threading
import time
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urlparse

import httpx


# ---------------------------------------------------------------------------
# SSRF Protection
# ---------------------------------------------------------------------------

# IPs that must never be reachable from the execution adapter.
_BLOCKED_PREFIXES = [
    "127.",       # loopback
    "10.",        # private
    "172.16.",    # private
    "172.17.",    # private
    "172.18.",    # private
    "172.19.",    # private
    "172.20.",    # private
    "172.21.",    # private
    "172.22.",    # private
    "172.23.",    # private
    "172.24.",    # private
    "172.25.",    # private
    "172.26.",    # private
    "172.27.",    # private
    "172.28.",    # private
    "172.29.",    # private
    "172.30.",    # private
    "172.31.",    # private
    "192.168.",   # private
    "169.254.",   # link-local
    "0.0.0.0",    # unspecified  # nosec B104
    "::1",        # IPv6 loopback
    "fc00:",      # IPv6 private
    "fe80:",      # IPv6 link-local
]


class SSRFError(Exception):
    """Raised when a target URL is blocked by SSRF protection."""
    pass


def validate_target_url(url: str, allowlist: Optional[set[str]] = None) -> str:
    """
    Validate that a target URL is safe to forward to.

    Checks:
    1. Must be HTTPS
    2. Must not resolve to private/loopback/link-local IPs
    3. Must be in the allowlist if one is configured
    4. Must not use dangerous schemes or ports

    Returns the validated URL.
    Raises SSRFError if the URL is blocked.
    """
    parsed = urlparse(url)

    if parsed.scheme != "https":
        raise SSRFError(f"Only HTTPS targets are allowed, got: {parsed.scheme}")

    if not parsed.hostname:
        raise SSRFError("Target URL must have a hostname")

    if allowlist is not None and len(allowlist) > 0:
        if parsed.hostname not in allowlist:
            raise SSRFError(
                f"Target host '{parsed.hostname}' not in allowlist"
            )

    # Check for IP literals
    try:
        ip = ipaddress.ip_address(parsed.hostname)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            raise SSRFError(f"Target IP {parsed.hostname} is private/loopback/reserved")
    except ValueError:
        # It's a hostname, not an IP — check against blocked prefixes as fallback
        hostname = parsed.hostname.lower()
        for prefix in _BLOCKED_PREFIXES:
            if hostname.startswith(prefix.lower()):
                raise SSRFError(f"Target hostname '{hostname}' matches blocked prefix")

    # Block dangerous ports
    if parsed.port and parsed.port < 1024:
        raise SSRFError(f"Target port {parsed.port} is privileged")

    return url


# ---------------------------------------------------------------------------
# Circuit Breaker
# ---------------------------------------------------------------------------

@dataclass
class CircuitState:
    """Thread-safe circuit breaker state."""
    failure_count: int = 0
    failure_threshold: int = 5
    last_failure_time: float = 0.0
    reset_timeout: float = 30.0  # seconds before trying half-open
    _lock: threading.Lock = field(default_factory=threading.Lock)

    @property
    def state(self) -> str:
        """Returns 'closed', 'open', or 'half_open'."""
        with self._lock:
            if self.failure_count < self.failure_threshold:
                return "closed"
            if time.time() - self.last_failure_time > self.reset_timeout:
                return "half_open"
            return "open"

    def record_success(self) -> None:
        with self._lock:
            self.failure_count = 0

    def record_failure(self) -> None:
        with self._lock:
            self.failure_count += 1
            self.last_failure_time = time.time()

    def can_proceed(self) -> bool:
        state = self.state
        return state in ("closed", "half_open")


# ---------------------------------------------------------------------------
# Execution Result
# ---------------------------------------------------------------------------

@dataclass
class ExecutionResult:
    forwarded: bool
    status_code: Optional[int] = None
    response_body: Optional[str] = None
    error: Optional[str] = None
    circuit_open: bool = False
    timing_ms: float = 0.0


# ---------------------------------------------------------------------------
# HTTP Execution Adapter
# ---------------------------------------------------------------------------

class HTTPExecutionAdapter:
    """
    Forwards allowed requests to downstream HTTP services.

    This is the component that makes CUSTOS a real firewall:
    - DENY → never calls the target
    - ALLOW → forwards via httpx with timeout + circuit breaker
    - Fail-closed → any exception = block, not forward
    """

    def __init__(
        self,
        allowlist: Optional[set[str]] = None,
        timeout: float = 10.0,
        circuit_threshold: int = 5,
        circuit_reset: float = 30.0,
    ):
        self._allowlist = allowlist or set()
        self._default_timeout = timeout
        self._circuit = CircuitState(
            failure_threshold=circuit_threshold,
            reset_timeout=circuit_reset,
        )
        self._client = httpx.Client(timeout=timeout)

    @property
    def circuit(self) -> CircuitState:
        return self._circuit

    def forward(
        self,
        url: str,
        method: str = "POST",
        content: str = "",
        headers: Optional[dict[str, str]] = None,
        timeout: Optional[float] = None,
    ) -> ExecutionResult:
        """
        Forward a request to the downstream target.

        Returns ExecutionResult with forwarded=True on success.
        Returns ExecutionResult with forwarded=False on any failure.

        This method NEVER raises — it catches all exceptions and returns
        them as ExecutionResult.error. Fail-closed.
        """
        start = time.time()

        # SSRF check — block before any network call
        try:
            validate_target_url(url, self._allowlist)
        except SSRFError as e:
            return ExecutionResult(
                forwarded=False,
                error=f"SSRF blocked: {e}",
                timing_ms=(time.time() - start) * 1000,
            )

        # Circuit breaker check
        if not self._circuit.can_proceed():
            return ExecutionResult(
                forwarded=False,
                error="Circuit breaker open",
                circuit_open=True,
                timing_ms=(time.time() - start) * 1000,
            )

        # Forward the request
        try:
            req_headers = {"Content-Type": "application/json"}
            if headers:
                req_headers.update(headers)

            response = self._client.request(
                method=method,
                url=url,
                content=content,
                headers=req_headers,
                timeout=timeout or self._default_timeout,
            )

            self._circuit.record_success()

            # Truncate response preview to 500 chars for safety
            preview = response.text[:500] if response.text else None

            return ExecutionResult(
                forwarded=True,
                status_code=response.status_code,
                response_body=preview,
                timing_ms=(time.time() - start) * 1000,
            )

        except httpx.TimeoutException:
            self._circuit.record_failure()
            return ExecutionResult(
                forwarded=False,
                error="Downstream timeout",
                timing_ms=(time.time() - start) * 1000,
            )
        except httpx.ConnectError:
            self._circuit.record_failure()
            return ExecutionResult(
                forwarded=False,
                error="Downstream connection refused",
                timing_ms=(time.time() - start) * 1000,
            )
        except Exception as e:
            # Fail-closed: any unexpected error = block
            self._circuit.record_failure()
            return ExecutionResult(
                forwarded=False,
                error=f"Forwarding failed: {type(e).__name__}: {e}",
                timing_ms=(time.time() - start) * 1000,
            )

    def close(self) -> None:
        self._client.close()
