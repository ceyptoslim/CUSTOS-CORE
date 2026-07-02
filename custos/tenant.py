"""
CUSTOS Tenant Manager v1.1

Manages per-tenant policy engines, rate limiters, and audit chains.
Each tenant is completely isolated — exhausting one tenant's quota,
triggering one tenant's policies, or reading one tenant's audit log
has zero effect on any other tenant.

Tenant ID format: any non-empty string, max 64 chars.
The "default" tenant is always pre-registered with standard settings.

Policy persistence (v1.1, closes #20):
Custom policy rules added via add_policy_rule() are persisted through
a PolicyStore (custos/policy_store.py). On startup, TenantManager:
  1. Restores the "default" tenant's custom rules (if any were persisted).
  2. Re-registers every other tenant that has persisted policy rules,
     restoring both the tenant and its custom rules.
This means custom policy configuration survives pod restarts, Kubernetes
rollouts, autoscaling events, and node rescheduling whenever a durable
PolicyStore backend is configured (POLICY_DB_PATH or DATABASE_URL).
With the default in-memory backend, behavior is unchanged (ephemeral).
"""

import threading
from dataclasses import dataclass, field
from typing import Optional

from custos.audit import AuditChain
from custos.policy_engine import PolicyEngine, PolicyRule
from custos.policy_store import PolicyStore
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

    def __init__(self, policy_store: Optional[PolicyStore] = None):
        self._tenants: dict[str, TenantContext] = {}
        self._custom_rules: dict[str, list[PolicyRule]] = {}
        self._lock = threading.RLock()
        self._policy_store = policy_store or PolicyStore()

        # Always register the default tenant (restores its persisted
        # custom rules automatically, if any).
        self.register("default", TenantConfig(
            tenant_id="default",
            quota=DEFAULT_QUOTA,
        ))

        # Restore any other tenants that have persisted policy rules.
        # This is what makes tenant + policy state survive a restart.
        for tenant_id in self._policy_store.list_tenants():
            if tenant_id not in self._tenants:
                self.register(tenant_id, TenantConfig(tenant_id=tenant_id))

    def register(self, tenant_id: str, config: TenantConfig) -> TenantContext:
        """Register a new tenant with isolated components.

        If the PolicyStore has persisted custom rules for this tenant_id,
        they are loaded and applied on top of the default rule set.
        """
        with self._lock:
            rate_limiter = RateLimiter()
            rate_limiter.register(tenant_id, config.quota)

            persisted_rules = self._policy_store.load(tenant_id)
            self._custom_rules[tenant_id] = list(persisted_rules)

            engine = PolicyEngine()
            for rule in persisted_rules:
                engine.add_rule(rule)

            ctx = TenantContext(
                tenant_id=tenant_id,
                policy_engine=engine,
                rate_limiter=rate_limiter,
                audit_chain=AuditChain(),
            )
            self._tenants[tenant_id] = ctx
            return ctx

    def add_policy_rule(self, tenant_id: str, rule: PolicyRule) -> TenantContext:
        """
        Add a custom policy rule for a tenant and persist it immediately
        via the PolicyStore, so it survives the next restart.
        """
        with self._lock:
            ctx = self.get_or_default(tenant_id)
            ctx.policy_engine.add_rule(rule)
            self._custom_rules.setdefault(tenant_id, []).append(rule)
            self._policy_store.save(tenant_id, self._custom_rules[tenant_id])
            return ctx

    def list_policy_rules(self, tenant_id: str) -> list[PolicyRule]:
        """Return only the custom (persisted) rules for a tenant — not defaults."""
        with self._lock:
            return list(self._custom_rules.get(tenant_id, []))

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
        """Remove a tenant and its persisted policy rules. Cannot remove 'default'."""
        if tenant_id == "default":
            return False
        with self._lock:
            if tenant_id in self._tenants:
                del self._tenants[tenant_id]
                self._custom_rules.pop(tenant_id, None)
                self._policy_store.delete(tenant_id)
                return True
            return False

    @property
    def count(self) -> int:
        with self._lock:
            return len(self._tenants)

    @property
    def policy_backend(self) -> str:
        return self._policy_store.backend_type
