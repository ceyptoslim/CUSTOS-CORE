"""
CUSTOS JWT Authentication

Lightweight JWT verification middleware for /v1/evaluate.
Uses HS256 by default. Secret loaded from environment variable CUSTOS_JWT_SECRET.

Upgrade path: swap to RS256 with JWKS endpoint for production multi-tenant use.
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
_JWT_ALGORITHM = "HS256"
_JWT_EXPIRY_SECONDS = int(os.getenv("CUSTOS_JWT_EXPIRY", "3600"))  # 1 hour default

_bearer_scheme = HTTPBearer(auto_error=False)


# ---------------------------------------------------------------------------
# Token creation (for testing / dev token issuance)
# ---------------------------------------------------------------------------

def create_token(client_id: str, expires_in: int = _JWT_EXPIRY_SECONDS) -> str:
    """Create a signed JWT for the given client_id."""
    payload = {
        "sub": client_id,
        "iat": int(time.time()),
        "exp": int(time.time()) + expires_in,
    }
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
    Raises HTTP 401 on missing/invalid token, HTTP 403 on expired token.
    """
    if credentials is None:
        raise HTTPException(
            status_code=401,
            detail="Authorization header required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials
    try:
        payload = jwt.decode(token, _JWT_SECRET, algorithms=[_JWT_ALGORITHM])
        client_id: str = payload.get("sub", "")
        if not client_id:
            raise HTTPException(status_code=401, detail="Token missing subject claim")
        return client_id
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=403,
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
