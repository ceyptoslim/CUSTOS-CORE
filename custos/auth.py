"""
CUSTOS JWT Authentication

JWT verification middleware for /v1/evaluate and the admin router.

Two algorithms, selected per token header and configuration:

* HS256 (default, backward compatible): shared secret from
  CUSTOS_JWT_SECRET. Suitable for single-tenant deployments.
* RS256 (production multi-tenant): asymmetric keys. The service
  publishes its public key at /.well-known/jwks.json (see custos/jwks.py);
  tenant-issued tokens are verified against tenant JWKS URLs configured
  via CUSTOS_TENANT_JWKS_URL[_<ISSUER_SLUG>].

Set CUSTOS_JWT_ALGORITHM=RS256 (plus CUSTOS_JWT_PRIVATE_KEY in production)
to activate the RS256 path. Both algorithms are accepted during the
transition; each token is verified strictly against the key material its
own header selects — algorithm-confusion tokens are rejected.
"""
# Copyright (C) 2024-2026 FroLife Productions
# Licensed under the GNU Affero General Public License v3.0 (AGPL-3.0)
# See LICENSE file for details. Commercial license available upon request.



import os
import time
from typing import Optional

import jwt
from fastapi import HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from custos.logging import get_logger

logger = get_logger("auth")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
_JWT_SECRET = os.getenv("CUSTOS_JWT_SECRET", "dev-secret-change-in-production")
_JWT_ALGORITHM = (os.getenv("CUSTOS_JWT_ALGORITHM") or "HS256").upper()
if _JWT_ALGORITHM not in ("HS256", "RS256"):
    raise RuntimeError(f"CUSTOS_JWT_ALGORITHM must be HS256 or RS256, got {_JWT_ALGORITHM!r}")
_JWT_EXPIRY_SECONDS = int(os.getenv("CUSTOS_JWT_EXPIRY", "3600"))  # 1 hour default

_bearer_scheme = HTTPBearer(auto_error=False)


# ---------------------------------------------------------------------------
# Token creation (for testing / dev token issuance)
# ---------------------------------------------------------------------------

def create_token(client_id: str, expires_in: int = _JWT_EXPIRY_SECONDS) -> str:
    """Create a signed JWT for the given client_id.

    HS256 mode signs with the shared secret; RS256 mode signs with the
    service RSA keypair (kid header included) — see custos/jwks.py.
    """
    payload = {
        "sub": client_id,
        "iat": int(time.time()),
        "exp": int(time.time()) + expires_in,
    }
    if _JWT_ALGORITHM == "RS256":
        from custos.jwks import sign_rs256
        return sign_rs256(payload)
    return jwt.encode(payload, _JWT_SECRET, algorithm=_JWT_ALGORITHM)


# ---------------------------------------------------------------------------
# Token verification dependency
# ---------------------------------------------------------------------------

def verify_token(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(_bearer_scheme),
) -> str:
    """
    FastAPI dependency. Extracts and verifies the Bearer JWT.
    Returns the client_id (sub claim) on success.
    Raises HTTP 401 on missing, invalid, or expired token (RFC 6750).
    """
    if credentials is None:
        raise HTTPException(
            status_code=401,
            detail="Authorization header required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials
    try:
        header_alg = jwt.get_unverified_header(token).get("alg", "")
        if header_alg == "RS256":
            # Asymmetric path: service key or tenant JWKS (custos/jwks.py).
            # HS256 secrets are NEVER accepted for RS256-header tokens and
            # vice versa — the confusion attack is structurally closed.
            from custos.jwks import verify_rs256_token
            payload = verify_rs256_token(token)
        elif header_alg == "HS256":
            if os.getenv("CUSTOS_ENV", "development").lower() == "production":
                secret = os.getenv("CUSTOS_JWT_SECRET")
                if not secret or secret == _DEV_DEFAULT_SECRET:
                    # Fail-closed even in RS256 deployments: an unset/dev
                    # shared secret must never silently accept HS256 tokens.
                    raise jwt.InvalidTokenError(
                        "HS256 rejected: shared secret unset or dev-default (production)"
                    )
            payload = jwt.decode(token, _JWT_SECRET, algorithms=["HS256"])
        else:
            raise jwt.InvalidTokenError(f"Unsupported algorithm: {header_alg!r}")
        client_id: str = payload.get("sub", "")
        if not client_id:
            raise HTTPException(status_code=401, detail="Token missing subject claim")
        return client_id
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=401,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidTokenError as exc:
        raise HTTPException(
            status_code=401,
            detail=f"Invalid token: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        )


# ---------------------------------------------------------------------------
# Optional: bypass for dev mode
# ---------------------------------------------------------------------------

_DEV_DEFAULT_SECRET = "dev-secret-change-in-production"


def validate_production_secrets() -> None:
    """Fail closed: refuse to run in production with a missing/dev-default JWT secret.

    Strict-env-presence rule: security-critical environment variables must be
    present in production deployments. A well-known dev fallback secret in a
    production deployment is equivalent to running with no secret at all, so
    startup raises instead of logging a warning.
    """
    env = os.getenv("CUSTOS_ENV", "development").lower()
    if env != "production":
        return
    algorithm = (os.getenv("CUSTOS_JWT_ALGORITHM") or "HS256").upper()
    if algorithm == "RS256":
        from custos.jwks import validate_production_key
        validate_production_key()  # explicit RSA key required (fail-closed)
    else:
        secret = os.getenv("CUSTOS_JWT_SECRET")
        if not secret or secret == _DEV_DEFAULT_SECRET:
            raise RuntimeError(
                "CUSTOS_JWT_SECRET is unset or set to the dev default while "
                "CUSTOS_ENV=production. Set a strong unique secret (fail-closed). "
                "(Or switch to RS256: CUSTOS_JWT_ALGORITHM=RS256 + CUSTOS_JWT_PRIVATE_KEY.)"
            )


def auth_enabled() -> bool:
    """Return True unless AUTH_DISABLED=1 is set (dev/test convenience only).

    If CUSTOS_ENV=production and AUTH_DISABLED=1, log a critical warning and
    override to require auth.
    """
    env = os.getenv("CUSTOS_ENV", "development").lower()
    if env == "production" and os.getenv("AUTH_DISABLED", "0") == "1":
        logger.critical(
            "AUTH_DISABLED=1 is set in production environment! Overriding to require authentication."
        )
        return True
    return os.getenv("AUTH_DISABLED", "0") != "1"
