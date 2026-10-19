"""
CUSTOS JWKS — RSA key management and JWKS discovery

RS256 support for production multi-tenant use:

* The service holds an RSA private key (PEM) for issuing tokens.
* ``/.well-known/jwks.json`` publishes the matching public key so any
  client (or external verifier) can confirm token signatures without
  sharing a secret.
* Tenants may register a JWKS URL (``CUSTOS_TENANT_JWKS_URL`` per
  issuer); inbound RS256 tokens from those issuers are verified against
  the tenant's own keys — the service never holds tenant secrets.

Key sourcing (fail-closed in production):
* ``CUSTOS_JWT_PRIVATE_KEY`` — PEM content (or a file path) for the
  private key. Required when ``CUSTOS_JWT_ALGORITHM=RS256`` and
  ``CUSTOS_ENV=production``.
* Development only: an ephemeral keypair is generated at first use so
  local flows work without configuration. Tokens do not survive
  restarts in this mode.

Key identity:
* ``CUSTOS_JWT_KEY_ID`` — explicit ``kid``. Defaults to the SHA-256
  thumbprint of the public key (RFC 7638 style), so the JWKS ``kid``
  is deterministic and stable for a given key.
"""
# Copyright (C) 2024-2026 FroLife Productions
# Licensed under the GNU Affero General Public License v3.0 (AGPL-3.0)
# See LICENSE file for details. Commercial license available upon request.

import hashlib
import json
import os
import threading
import time
from typing import Any, Dict, Optional, Tuple

import jwt
import jwt.algorithms
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from custos.logging import get_logger

logger = get_logger("jwks")

_DEV_KEY_BITS = 2048
_JWKS_CACHE_TTL_SECONDS = 300  # 5 minutes
_JWKS_REFRESH_BACKOFF_SECONDS = 30  # min spacing between failed refreshes


# ---------------------------------------------------------------------------
# Service keypair
# ---------------------------------------------------------------------------

_service_key_lock = threading.Lock()
_service_key: Optional[Tuple[Any, str]] = None  # (RSAPrivateKey, kid)


def _load_private_key_from_env() -> Optional[Any]:
    """Load the RSA private key from CUSTOS_JWT_PRIVATE_KEY if configured.

    Accepts either raw PEM content or a path to a PEM file.
    Returns None when the variable is unset/unreadable.
    """
    raw = os.getenv("CUSTOS_JWT_PRIVATE_KEY")
    if not raw:
        return None
    if "-----BEGIN" not in raw:
        # treat as a file path
        try:
            with open(os.path.expanduser(raw), "r", encoding="utf-8") as fh:
                raw = fh.read()
        except OSError:
            logger.warning("custos.jwks.key_load_failed", extra={"reason": "unreadable path"})
            return None
    try:
        return serialization.load_pem_private_key(raw.encode("utf-8"), password=None)
    except (ValueError, TypeError) as exc:
        logger.warning("custos.jwks.key_load_failed", extra={"reason": str(exc)[:80]})
        return None


def _kid_for_public_key(public_key: Any) -> str:
    """RFC 7638-style thumbprint kid: SHA-256 of the JWK members (n, e)."""
    jwk = _jwk_from_public_key(public_key)
    canonical = json.dumps({"e": jwk["e"], "kty": jwk["kty"], "n": jwk["n"]},
                           separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _jwk_from_public_key(public_key: Any) -> Dict[str, str]:
    """Convert an RSA public key to a JWK dict (n, e base64url)."""
    import base64

    def b64url_uint(value: int) -> str:
        raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")

    pub_numbers = public_key.public_numbers()
    return {
        "kty": "RSA",
        "n": b64url_uint(pub_numbers.n),
        "e": b64url_uint(pub_numbers.e),
    }


def get_service_keypair() -> Tuple[Any, str]:
    """Return (private_key, kid) for the service keypair, loading once.

    Dev fallback: generates an ephemeral key on first use. Production
    callers must call validate_production_key() at startup — the
    ephemeral fallback is refused there.
    """
    global _service_key
    with _service_key_lock:
        if _service_key is not None:
            return _service_key
        private_key = _load_private_key_from_env()
        if private_key is None:
            logger.warning(
                "custos.jwks.ephemeral_key_generated",
                extra={"note": "dev-mode ephemeral RSA key; tokens invalid after restart"},
            )
            private_key = rsa.generate_private_key(public_exponent=65537, key_size=_DEV_KEY_BITS)
        if not isinstance(private_key, rsa.RSAPrivateKey):
            raise RuntimeError("CUSTOS_JWT_PRIVATE_KEY must be an RSA private key for RS256")
        kid = os.getenv("CUSTOS_JWT_KEY_ID") or _kid_for_public_key(private_key.public_key())
        _service_key = (private_key, kid)
        return _service_key


def get_service_public_jwk() -> Dict[str, Any]:
    """The service's public key as a JWK, tagged with kid/alg/use."""
    private_key, kid = get_service_keypair()
    jwk = _jwk_from_public_key(private_key.public_key())
    jwk.update({"kid": kid, "alg": "RS256", "use": "sig"})
    return jwk


def get_jwks_document() -> Dict[str, Any]:
    """The JWKS document served at /.well-known/jwks.json."""
    return {"keys": [get_service_public_jwk()]}


def sign_rs256(payload: Dict[str, Any]) -> str:
    """Sign a token with the service RSA key (RS256)."""
    private_key, kid = get_service_keypair()
    headers = {"kid": kid}
    return jwt.encode(payload, private_key, algorithm="RS256", headers=headers)


def validate_production_key() -> None:
    """Fail-closed: RS256 in production requires an explicit private key.

    An ephemeral key in production would silently invalidate tokens on
    every restart and hide a missing deployment secret — so refuse to
    start, mirroring validate_production_secrets().
    """
    env = os.getenv("CUSTOS_ENV", "development").lower()
    if env != "production":
        return
    algorithm = (os.getenv("CUSTOS_JWT_ALGORITHM") or "HS256").upper()
    if algorithm != "RS256":
        return
    if _load_private_key_from_env() is None:
        raise RuntimeError(
            "CUSTOS_JWT_ALGORITHM=RS256 in production requires "
            "CUSTOS_JWT_PRIVATE_KEY (PEM content or path). Fail-closed."
        )


# ---------------------------------------------------------------------------
# Tenant JWKS verification (outbound fetch + cache)
# ---------------------------------------------------------------------------

class JWKSCache:
    """Fetches and caches a remote JWKS by URL, keyed by kid.

    Refresh policy: TTL expiry or an unknown-kid lookup triggers a
    refetch; a failed refetch backs off and the previous keys remain
    in force (fail-closed against surprise unavailability is NOT
    attempted — a JWKS that disappears should deny its tokens, which
    falls out naturally because the kid lookup fails).
    """

    def __init__(self, ttl_seconds: int = _JWKS_CACHE_TTL_SECONDS):
        self._ttl = ttl_seconds
        self._lock = threading.Lock()
        self._by_url: Dict[str, Dict[str, Any]] = {}   # url -> {"keys": {}, "fetched": ts}
        self._last_attempt: Dict[str, float] = {}     # url -> ts (backoff guard)

    def _fetch(self, url: str) -> Dict[str, Any]:
        import urllib.request

        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            doc = json.loads(resp.read().decode("utf-8"))
        keys: Dict[str, Any] = {}
        for jwk in doc.get("keys", []):
            if jwk.get("kty") == "RSA" and jwk.get("kid"):
                keys[jwk["kid"]] = jwk
        return {"keys": keys, "fetched": time.time()}

    def get_key(self, url: str, kid: str) -> Optional[Dict[str, Any]]:
        """Return the cached JWK for (url, kid), refreshing when needed.

        Returns None when the kid is unknown after a refresh — callers
        must treat that as verification failure (401).
        """
        with self._lock:
            entry = self._by_url.get(url)
            now = time.time()
            stale = entry is None or (now - entry["fetched"] > self._ttl)
            if stale and (now - self._last_attempt.get(url, 0) > _JWKS_REFRESH_BACKOFF_SECONDS):
                self._last_attempt[url] = now
                try:
                    entry = self._fetch(url)
                    self._by_url[url] = entry
                except Exception as exc:  # noqa: BLE001 — any fetch error denies
                    logger.warning("custos.jwks.fetch_failed", extra={"reason": str(exc)[:80]})
            if entry is None:
                return None
            return entry["keys"].get(kid)


_jwks_cache = JWKSCache()


def tenant_jwks_url_for_issuer(iss: Optional[str]) -> Optional[str]:
    """Resolve the JWKS URL for a token issuer, if one is configured.

    Configuration: CUSTOS_TENANT_JWKS_URL (single-tenant deployments) or
    CUSTOS_TENANT_JWKS_URL_<SLUG> where <SLUG> is the issuer string with
    non-alphanumerics replaced by underscore. Exact-match lookup.
    """
    if not iss:
        return os.getenv("CUSTOS_TENANT_JWKS_URL") or None
    import re

    slug = re.sub(r"[^A-Za-z0-9]", "_", iss).upper()
    return (
        os.getenv(f"CUSTOS_TENANT_JWKS_URL_{slug}")
        or os.getenv("CUSTOS_TENANT_JWKS_URL")
        or None
    )


def verify_rs256_token(token: str) -> Dict[str, Any]:
    """Verify an RS256 token against the appropriate key.

    Resolution order:
    1. kid matches the service's own key -> verify with the service
       public key (tokens we issued).
    2. issuer resolves to a tenant JWKS URL -> fetch JWK by kid from
       the tenant's JWKS and verify with it (tenant-issued tokens).

    Raises jwt.InvalidTokenError on any failure path.
    """
    header = jwt.get_unverified_header(token)
    kid = header.get("kid")

    payload: Optional[Dict[str, Any]] = None

    # 1. our own key
    _, service_kid = get_service_keypair()
    if kid == service_kid:
        private_key, _ = get_service_keypair()
        payload = jwt.decode(
            token,
            private_key.public_key(),
            algorithms=["RS256"],
            options={"require": ["exp", "sub"]},
        )
        return payload

    # 2. tenant JWKS by issuer
    unverified = jwt.decode(token, options={"verify_signature": False}) or {}
    iss = unverified.get("iss")
    jwks_url = tenant_jwks_url_for_issuer(iss)
    if jwks_url:
        jwk = _jwks_cache.get_key(jwks_url, kid or "")
        if jwk:
            from jwt.algorithms import RSAAlgorithm

            public_key = RSAAlgorithm.from_jwk(json.dumps(jwk))
            payload = jwt.decode(
                token,
                public_key,
                algorithms=["RS256"],
                audience=os.getenv("CUSTOS_JWT_AUDIENCE") or None,
                issuer=iss if iss else None,
                options={"require": ["exp", "sub"]},
            )
            return payload

    raise jwt.InvalidTokenError("RS256 token: no matching key (kid unknown or issuer unconfigured)")
