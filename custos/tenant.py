"""
CUSTOS Tenant Manager v1.0

Manages per-tenant policy engines, rate limiters, and audit chains.
Each tenant is completely isolated — exhausting one tenant's quota,
triggering one tenant's policies, or reading one tenant's audit log
has zero effect on any other tenant.

Tenant ID format: any non-empty string, max 64 chars.
The "default" tenant is always pre-registered with standard settings.

Note: tenant policy customizations can be persisted
via PolicyStore (custos/policy_store.py). Set
POLICY_DB_PATH or DATABASE_URL env var to activate.
"""

import threading
from dataclasses import dataclass, field
from typing import Optional

from custos.audit import AuditChain
from custos.policy_engine import PolicyEngine
from custos.rate_limiter import QuotaConfig, RateLimiter


DEFAULT_QUOTA = QuotaConfig(
    requests_per_minute=60,
    requests_per_hour=1000,
    tokens_per_minute=100_000,
)


@dataclass
class TenantConfig:
    tenant_id: str
    quota: QuotaConfig = field(default_factory=lambda: QuotaConfig(
        requests_per_minute=60,
        requests_per_hour=1000,
        tokens_per_minute=100_000,
    ))


@dataclass
class TenantContext:
    tenant_id: str
    policy_engine: PolicyEngine
    rate_limiter: RateLimiter
    audit_chain: AuditChain


class TenantManager:
    """
    Registry of all tenant contexts.
    Thread-safe. Each tenant gets isolated instances of all core components.
    """

    def __init__(self):
        self._tenants: dict[str, TenantContext] = {}
        self._lock = threading.RLock()

        # Always register the default tenant
        self.register("default", TenantConfig(
            tenant_id="default",
            quota=DEFAULT_QUOTA,
        ))

    def register(self, tenant_id: str, config: TenantConfig) -> TenantContext:
        """Register a new tenant with isolated components."""
        with self._lock:
            rate_limiter = RateLimiter()
            rate_limiter.register(tenant_id, config.quota)

            ctx = TenantContext(
                tenant_id=tenant_id,
                policy_engine=PolicyEngine(),
                rate_limiter=rate_limiter,
                audit_chain=AuditChain(),
            )
            self._tenants[tenant_id] = ctx
            return ctx

    def get(self, tenant_id: str) -> Optional[TenantContext]:
        """Return tenant context or None if not registered."""
        with self._lock:
            return self._tenants.get(tenant_id)

    def get_or_default(self, tenant_id: str) -> TenantContext:
        """
        Return tenant context if registered, otherwise fall back
        to the default tenant. Never returns None.
        """
        with self._lock:
            return self._tenants.get(tenant_id) or self._tenants["default"]

    def list_tenants(self) -> list[str]:
        """Return list of all registered tenant IDs."""
        with self._lock:
            return list(self._tenants.keys())

    def unregister(self, tenant_id: str) -> bool:
        """Remove a tenant. Cannot remove 'default'."""
        if tenant_id == "default":
            return False
        with self._lock:
            if tenant_id in self._tenants:
                del self._tenants[tenant_id]
                return True
            return False

    @property
    def count(self) -> int:
        with self._lock:
            return len(self._tenants)
