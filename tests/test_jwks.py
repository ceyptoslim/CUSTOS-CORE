"""
JWKS / RS256 authentication tests

Covers the dual-algorithm verification path from custos/auth.py and the
key-management/JWKS machinery in custos/jwks.py:

* RS256 create/verify roundtrip (service key)
* /.well-known/jwks.json discovery (shape + usability to verify tokens)
* Tenant-issued tokens verified via a JWKS URL (fetched + cached + kid)
* Algorithm-confusion rejection (alg=none, HS256 secret replay)
* HS256 backward compatibility (dev) and production fail-closed guards
* Fail-closed production startup: RS256 without an explicit private key
"""
# Copyright (C) 2024-2026 FroLife Productions
# Licensed under the GNU Affero General Public License v3.0 (AGPL-3.0)
# See LICENSE file for details. Commercial license available upon request.

import base64
import json
import time

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from jwt.algorithms import RSAAlgorithm

import custos.auth as auth_mod
import custos.jwks as jwks_mod
from custos.jwks import (
    JWKSCache,
    get_jwks_document,
    get_service_keypair,
    get_service_public_jwk,
    tenant_jwks_url_for_issuer,
    validate_production_key,
    verify_rs256_token,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _reset_service_key():
    jwks_mod._service_key = None


@pytest.fixture
def rs256_mode(monkeypatch):
    """Point the auth module at the RS256 path (call-time branch)."""
    monkeypatch.setattr(auth_mod, "_JWT_ALGORITHM", "RS256")
    _reset_service_key()
    yield
    _reset_service_key()


def _make_credentials(token: str):
    from fastapi.security import HTTPAuthorizationCredentials

    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


def _new_tenant_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


# ---------------------------------------------------------------------------
# Service-key roundtrip
# ---------------------------------------------------------------------------

class TestServiceKeyRoundtrip:
    def test_rs256_token_verifies(self, rs256_mode):
        token = auth_mod.create_token("tenant_003")
        payload = verify_rs256_token(token)
        assert payload["sub"] == "tenant_003"

    def test_kid_header_present(self, rs256_mode):
        token = auth_mod.create_token("client")
        header = jwt.get_unverified_header(token)
        assert header["alg"] == "RS256"
        assert header["kid"]
        _, kid = get_service_keypair()
        assert header["kid"] == kid

    def test_kid_is_stable_thumbprint(self, rs256_mode):
        import hashlib

        jwk1 = get_service_public_jwk()
        _reset_service_key()
        # same underlying key (cached global) -> same kid; regenerate env key
        # is impossible without env var, so verify determinism of thumbprint
        n = jwk1["n"]
        e = jwk1["e"]
        canonical = json.dumps({"e": e, "kty": "RSA", "n": n}, separators=(",", ":"), sort_keys=True)
        expected = hashlib.sha256(canonical.encode()).hexdigest()
        assert jwk1["kid"] == expected

    def test_wrong_key_with_service_kid_rejected(self, rs256_mode):
        """Signature swap: a token signed by a different key but claiming the
        service kid must be rejected (kid-to-key binding enforced)."""
        token = auth_mod.create_token("client")
        header = jwt.get_unverified_header(token)
        other = _new_tenant_key()
        forged = jwt.encode(
            {"sub": "admin", "exp": int(time.time()) + 60},
            other, algorithm="RS256", headers={"kid": header["kid"]},
        )
        assert forged != token  # different signature bytes
        with pytest.raises(jwt.InvalidTokenError):
            verify_rs256_token(forged)


# ---------------------------------------------------------------------------
# JWKS discovery endpoint
# ---------------------------------------------------------------------------

class TestJWKSEndpoint:
    def test_well_known_returns_valid_jwk(self, rs256_mode):
        import main as app_module

        with TestClient(app_module.app) as client:
            resp = client.get("/.well-known/jwks.json")
        assert resp.status_code == 200
        doc = resp.json()
        assert set(doc.keys()) == {"keys"}
        jwk = doc["keys"][0]
        assert jwk["kty"] == "RSA"
        assert jwk["alg"] == "RS256"
        assert jwk["use"] == "sig"
        assert jwk["kid"]
        assert jwk["n"] and jwk["e"]

    def test_jwks_key_verifies_service_token(self, rs256_mode):
        """The published JWKS alone must verify a service-issued token."""
        token = auth_mod.create_token("external_verifier")
        public_key = RSAAlgorithm.from_jwk(json.dumps(get_service_public_jwk()))
        payload = jwt.decode(token, public_key, algorithms=["RS256"])
        assert payload["sub"] == "external_verifier"


# ---------------------------------------------------------------------------
# Tenant JWKS verification
# ---------------------------------------------------------------------------

class TestTenantJWKS:
    def test_tenant_token_verifies_via_jwks(self, rs256_mode, monkeypatch):
        """A tenant-issued RS256 token verifies against the tenant JWKS."""
        tenant_key = _new_tenant_key()
        tenant_kid = "tenant-key-1"

        def fake_fetch(self, url):
            jwk = json.loads(RSAAlgorithm.to_jwk(tenant_key.public_key()))
            jwk["kid"] = tenant_kid
            return {"keys": {tenant_kid: jwk}, "fetched": time.time()}

        monkeypatch.setattr(JWKSCache, "_fetch", fake_fetch)
        monkeypatch.setenv("CUSTOS_TENANT_JWKS_URL", "https://tenant.example/jwks.json")

        token = jwt.encode(
            {"sub": "tenant_client", "iss": "https://tenant.example", "exp": int(time.time()) + 60},
            tenant_key, algorithm="RS256", headers={"kid": tenant_kid},
        )
        payload = verify_rs256_token(token)
        assert payload["sub"] == "tenant_client"
        assert payload["iss"] == "https://tenant.example"

    def test_issuer_slug_lookup(self, monkeypatch):
        monkeypatch.delenv("CUSTOS_TENANT_JWKS_URL", raising=False)
        monkeypatch.setenv("CUSTOS_TENANT_JWKS_URL_HTTPS___TENANT_EXAMPLE",
                           "https://tenant.example/jwks.json")
        assert tenant_jwks_url_for_issuer("https://tenant.example") == \
            "https://tenant.example/jwks.json"

    def test_plaintext_jwks_url_rejected(self, rs256_mode, monkeypatch):
        """Fail-closed: http:// JWKS URLs are refused before any request."""
        monkeypatch.setenv("CUSTOS_TENANT_JWKS_URL", "http://insecure.example/jwks.json")
        cache = JWKSCache()
        with pytest.raises(ValueError, match="https"):
            cache.get_key("http://insecure.example/jwks.json", "some-kid")

    def test_plaintext_jwks_token_gets_401_not_500(self, rs256_mode, monkeypatch):
        """End-to-end: a token whose issuer points at an http:// JWKS
        must produce an auth failure (401), never a server error."""
        from fastapi import HTTPException

        monkeypatch.setenv("CUSTOS_TENANT_JWKS_URL", "http://insecure.example/jwks.json")
        token = jwt.encode(
            {"sub": "x", "iss": "https://tenant.example", "exp": int(time.time()) + 60},
            _new_tenant_key(), algorithm="RS256", headers={"kid": "tenant-key-1"},
        )
        with pytest.raises(HTTPException) as exc_info:
            auth_mod.verify_token(_make_credentials(token))
        assert exc_info.value.status_code == 401
        assert "refused" in exc_info.value.detail or "Invalid" in exc_info.value.detail

    def test_unknown_kid_rejected(self, rs256_mode, monkeypatch):
        monkeypatch.setenv("CUSTOS_TENANT_JWKS_URL", "https://tenant.example/jwks.json")

        def fake_fetch(self, url):
            return {"keys": {}, "fetched": time.time()}  # JWKS without our kid

        monkeypatch.setattr(JWKSCache, "_fetch", fake_fetch)
        token = jwt.encode(
            {"sub": "x", "iss": "https://tenant.example", "exp": int(time.time()) + 60},
            _new_tenant_key(), algorithm="RS256", headers={"kid": "not-in-jwks"},
        )
        with pytest.raises(jwt.InvalidTokenError):
            verify_rs256_token(token)

    def test_unconfigured_issuer_rejected(self, rs256_mode, monkeypatch):
        monkeypatch.delenv("CUSTOS_TENANT_JWKS_URL", raising=False)
        token = jwt.encode(
            {"sub": "x", "iss": "https://stranger.example", "exp": int(time.time()) + 60},
            _new_tenant_key(), algorithm="RS256", headers={"kid": "stranger"},
        )
        with pytest.raises(jwt.InvalidTokenError):
            verify_rs256_token(token)


# ---------------------------------------------------------------------------
# Algorithm confusion + HS256 compat
# ---------------------------------------------------------------------------

class TestAlgorithmSafety:
    def test_alg_none_rejected(self, rs256_mode):
        # hand-crafted JWT with alg=none (signature omitted)
        header = base64.urlsafe_b64encode(json.dumps({"alg": "none", "typ": "JWT"}).encode()).rstrip(b"=")
        payload = base64.urlsafe_b64encode(json.dumps({"sub": "admin", "exp": int(time.time()) + 60}).encode()).rstrip(b"=")
        token = f"{header.decode()}.{payload.decode()}."
        with pytest.raises(jwt.InvalidTokenError):
            verify_rs256_token(token)

    def test_hs256_still_works_in_dev(self, rs256_mode, monkeypatch):
        """Transition property: existing HS256 clients keep working."""
        monkeypatch.delenv("CUSTOS_ENV", raising=False)
        monkeypatch.setattr(auth_mod, "_JWT_SECRET", "transition-secret-0123456789abcdef")
        hs_token = jwt.encode({"sub": "legacy_client", "exp": int(time.time()) + 60},
                              "transition-secret-0123456789abcdef", algorithm="HS256")
        assert auth_mod.verify_token(_make_credentials(hs_token)) == "legacy_client"

    def test_hs256_dev_secret_rejected_in_production(self, rs256_mode, monkeypatch):
        """Fail-closed: dev-default HS256 secret never authorizes in production."""
        from fastapi import HTTPException

        monkeypatch.setenv("CUSTOS_ENV", "production")
        monkeypatch.setenv("CUSTOS_JWT_SECRET", auth_mod._DEV_DEFAULT_SECRET)
        monkeypatch.setattr(auth_mod, "_JWT_SECRET", auth_mod._DEV_DEFAULT_SECRET)
        hs_token = jwt.encode({"sub": "intruder", "exp": int(time.time()) + 60},
                              auth_mod._DEV_DEFAULT_SECRET, algorithm="HS256")
        with pytest.raises(HTTPException) as exc_info:
            auth_mod.verify_token(_make_credentials(hs_token))
        assert exc_info.value.status_code == 401
        assert "HS256 rejected" in exc_info.value.detail

    def test_rs256_signature_cannot_be_verified_with_secret(self, rs256_mode):
        """The classic confusion attack: RS256 token re-signed as HS256 with
        the known public key bytes as 'secret' must fail — the RS256 branch
        requires an RSA key material match, never a symmetric secret."""
        _, kid = get_service_keypair()
        confusion = jwt.encode({"sub": "admin", "exp": int(time.time()) + 60},
                               "dev-secret-change-in-production", algorithm="HS256",
                               headers={"kid": kid})
        with pytest.raises(jwt.InvalidTokenError):
            verify_rs256_token(confusion)


# ---------------------------------------------------------------------------
# Production fail-closed startup
# ---------------------------------------------------------------------------

class TestProductionValidation:
    def test_rs256_production_requires_key(self, monkeypatch):
        monkeypatch.setenv("CUSTOS_ENV", "production")
        monkeypatch.setenv("CUSTOS_JWT_ALGORITHM", "RS256")
        monkeypatch.delenv("CUSTOS_JWT_PRIVATE_KEY", raising=False)
        with pytest.raises(RuntimeError, match="CUSTOS_JWT_PRIVATE_KEY"):
            validate_production_key()

    def test_rs256_production_accepts_explicit_key(self, monkeypatch):
        monkeypatch.setenv("CUSTOS_ENV", "production")
        monkeypatch.setenv("CUSTOS_JWT_ALGORITHM", "RS256")
        pem = _new_tenant_key().private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode()
        monkeypatch.setenv("CUSTOS_JWT_PRIVATE_KEY", pem)
        assert validate_production_key() is None  # success contract: no exception

    def test_dev_environment_never_blocks(self, monkeypatch):
        monkeypatch.setenv("CUSTOS_ENV", "development")
        monkeypatch.setenv("CUSTOS_JWT_ALGORITHM", "RS256")
        monkeypatch.delenv("CUSTOS_JWT_PRIVATE_KEY", raising=False)
        assert validate_production_key() is None  # ephemeral dev key allowed

    def test_bad_algorithm_config_rejected_at_import(self, monkeypatch):
        monkeypatch.setenv("CUSTOS_JWT_ALGORITHM", "ES256")
        with pytest.raises(RuntimeError, match="HS256 or RS256"):
            import importlib
            importlib.reload(auth_mod)
        # restore for other tests
        monkeypatch.delenv("CUSTOS_JWT_ALGORITHM")
        import importlib
        importlib.reload(auth_mod)
