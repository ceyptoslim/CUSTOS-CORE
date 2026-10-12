"""
CUSTOS Execution Adapter

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
# Copyright (C) 2024-2026 FroLife Productions
# Licensed under the GNU Affero General Public License v3.0 (AGPL-3.0)
# See LICENSE file for details. Commercial license available upon request.



import ipaddress
import socket
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


def _validate_target_url(
    url: str, allowlist: Optional[set[str]] = None
) -> tuple[str, set[str]]:
    """
    Validate that a target URL is safe to forward to, resolving the
    hostname exactly ONCE (fail-closed) and returning the set of IPs
    the live request is pinned to (DNS-rebinding TOCTOU protection).

    Returns (validated_url, pinned_ips).
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

    # Port validation (fail-closed on unparseable ports). Standard HTTPS
    # port 443 is always allowed; other privileged ports are blocked.
    try:
        port = parsed.port
    except ValueError as exc:
        raise SSRFError(f"Target URL has an invalid port: {exc}")
    if port is not None and (port == 0 or (port < 1024 and port != 443)):
        raise SSRFError(f"Target port {port} is privileged")

    # IP-literal targets: validate the literal itself and pin to it.
    try:
        ip = ipaddress.ip_address(parsed.hostname)
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_unspecified
        ):
            raise SSRFError(
                f"Target IP {parsed.hostname} is private/loopback/reserved"
            )
        return url, {str(ip)}
    except ValueError:
        # It's a hostname — check blocked prefixes, then resolve ONCE and
        # validate every resolved address (fail-closed, no fallthrough).
        hostname = parsed.hostname.lower()
        for prefix in _BLOCKED_PREFIXES:
            if hostname.startswith(prefix.lower()):
                raise SSRFError(
                    f"Target hostname '{hostname}' matches blocked prefix"
                )

    try:
        addr_info = socket.getaddrinfo(parsed.hostname, None)
    except socket.gaierror as exc:
        # Fail-closed: an unresolvable hostname must BLOCK the request,
        # never fall through to weaker checks (fixes fail-open finding).
        raise SSRFError(
            f"DNS resolution failed for '{parsed.hostname}' — failing closed: {exc}"
        )

    pinned: set[str] = set()
    for entry in addr_info:
        ip_str = entry[4][0]
        try:
            resolved = ipaddress.ip_address(ip_str)
        except ValueError:
            continue  # skip malformed entries
        if (
            resolved.is_private
            or resolved.is_loopback
            or resolved.is_link_local
            or resolved.is_reserved
            or resolved.is_unspecified
        ):
            raise SSRFError(
                f"Target IP {ip_str} for '{parsed.hostname}' is private/loopback/reserved"
            )
        pinned.add(str(resolved))

    if not pinned:
        raise SSRFError(
            f"DNS returned no usable addresses for '{parsed.hostname}'"
        )

    return url, pinned


def validate_target_url(url: str, allowlist: Optional[set[str]] = None) -> str:
    """Backward-compatible wrapper: validate and return the URL only."""
    return _validate_target_url(url, allowlist)[0]



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
        self._circuit_threshold = circuit_threshold
        self._circuit_reset = circuit_reset
        self._circuits: dict[str, CircuitState] = {}
        self._lock = threading.Lock()
        self._client = httpx.Client(timeout=timeout)

    def _get_host(self, url: str) -> str:
        parsed = urlparse(url)
        return (parsed.hostname or url).lower()

    def get_circuit(self, target_host: str = "default") -> CircuitState:
        with self._lock:
            if target_host not in self._circuits:
                self._circuits[target_host] = CircuitState(
                    failure_threshold=self._circuit_threshold,
                    reset_timeout=self._circuit_reset,
                )
            return self._circuits[target_host]

    @property
    def circuit(self) -> CircuitState:
        return self.get_circuit("default")

    def can_request(self, target_host: str = "default") -> bool:
        host_ok = self.get_circuit(target_host).can_proceed()
        default_ok = self.get_circuit("default").can_proceed()
        return host_ok and default_ok

    def record_failure(self, target_host: str = "default") -> None:
        self.get_circuit(target_host).record_failure()

    def record_success(self, target_host: str = "default") -> None:
        if target_host == "default":
            with self._lock:
                for c in self._circuits.values():
                    c.record_success()
        else:
            self.get_circuit(target_host).record_success()

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
        target_host = self._get_host(url)

        # SSRF check — block before any network call. Single resolution,
        # validated and pinned: the live request may only connect to an
        # address that passed validation (DNS-rebinding TOCTOU protection).
        try:
            _, pinned_ips = _validate_target_url(url, self._allowlist)
        except SSRFError as e:
            return ExecutionResult(
                forwarded=False,
                error=f"SSRF blocked: {e}",
                timing_ms=(time.time() - start) * 1000,
            )

        # Circuit breaker check
        if not self.can_request(target_host):
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

            # Pin the request to a validated IP. SNI + Host keep TLS
            # verification and routing against the real hostname while
            # the connection can only reach a validated address.
            parsed = urlparse(url)
            host = parsed.hostname
            pinned_ip = sorted(pinned_ips, key=lambda a: (":" in a, a))[0]
            req_ip = f"[{pinned_ip}]" if ":" in pinned_ip else pinned_ip
            port = parsed.port
            req_url = f"https://{req_ip}" + (f":{port}" if port else "")
            req_url += parsed.path or "/"
            if parsed.query:
                req_url += f"?{parsed.query}"
            req_headers["Host"] = host

            response = self._client.request(
                method=method,
                url=req_url,
                content=content,
                headers=req_headers,
                timeout=timeout or self._default_timeout,
                extensions={"sni_hostname": host},
            )

            self.record_success(target_host)

            # Truncate response preview to 500 chars for safety
            preview = response.text[:500] if response.text else None

            return ExecutionResult(
                forwarded=True,
                status_code=response.status_code,
                response_body=preview,
                timing_ms=(time.time() - start) * 1000,
            )

        except httpx.TimeoutException:
            self.record_failure(target_host)
            return ExecutionResult(
                forwarded=False,
                error="Downstream timeout",
                timing_ms=(time.time() - start) * 1000,
            )
        except httpx.ConnectError:
            self.record_failure(target_host)
            return ExecutionResult(
                forwarded=False,
                error="Downstream connection refused",
                timing_ms=(time.time() - start) * 1000,
            )
        except Exception as e:
            # Fail-closed: any unexpected error = block
            self.record_failure(target_host)
            return ExecutionResult(
                forwarded=False,
                error=f"Forwarding failed: {type(e).__name__}: {e}",
                timing_ms=(time.time() - start) * 1000,
            )

    def close(self) -> None:
        self._client.close()
