"""
CUSTOS Pydantic Models v1.2
Schemas for all request/response models across evaluate, execute,
audit, replay, policy diff, snapshots, and tenant management.
"""
# Copyright (C) 2024-2026 FroLife Productions
# Licensed under the GNU Affero General Public License v3.0 (AGPL-3.0)
# See LICENSE file for details. Commercial license available upon request.



from typing import Any, Optional
from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Existing schemas
# ---------------------------------------------------------------------------

class EvaluateRequest(BaseModel):
    client_id: str = Field(default="default", min_length=1, max_length=128)
    content: str = Field(..., min_length=1, max_length=32_768)
    token_count: int = Field(default=1, ge=1, le=100_000)
    tenant_id: str = Field(default="default", min_length=1, max_length=64)

    @field_validator("client_id")
    @classmethod
    def client_id_no_whitespace(cls, v: str) -> str:
        if v != v.strip():
            raise ValueError("client_id must not have leading/trailing whitespace")
        return v

    @field_validator("content")
    @classmethod
    def content_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("content must not be blank or whitespace only")
        return v

    @field_validator("tenant_id")
    @classmethod
    def tenant_id_no_whitespace(cls, v: str) -> str:
        if v != v.strip():
            raise ValueError("tenant_id must not have leading/trailing whitespace")
        return v


class EvaluateResponse(BaseModel):
    allowed: bool
    action: str
    triggered_rule: Optional[str]
    reason: str
    client_id: str
    tenant_id: str = "default"
    audit_record_hash: Optional[str] = None
    trace_id: Optional[str] = None


class HealthResponse(BaseModel):
    status: str
    uptime_seconds: float


class ReadyResponse(BaseModel):
    status: str
    checks: dict


class AuditRecordResponse(BaseModel):
    timestamp: float
    client_id: str
    action: str
    triggered_rule: Optional[str]
    reason: str
    content_hash: str
    record_hash: str
    previous_hash: str
    trace_id: Optional[str] = None


# ---------------------------------------------------------------------------
# v0.4 schemas (unchanged)
# ---------------------------------------------------------------------------

class ReplayRequest(BaseModel):
    record_hash: str = Field(..., min_length=64, max_length=64)
    original_content: str = Field(..., min_length=1, max_length=32_768)
    tenant_id: str = Field(default="default", min_length=1, max_length=64)


class ReplayResponse(BaseModel):
    original_record_hash: str
    original_timestamp: float
    original_action: str
    original_triggered_rule: Optional[str]
    original_trace_id: Optional[str]
    replayed_action: str
    replayed_triggered_rule: Optional[str]
    replayed_reason: str
    decision_matches: bool
    replay_timestamp: float
    content_hash: str


class PolicyRuleRequest(BaseModel):
    name: str
    pattern: str
    action: str = Field(..., pattern="^(allow|deny|audit)$")
    reason: str


class PolicyDiffRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=32_768)
    current_rules: list[PolicyRuleRequest]
    proposed_rules: list[PolicyRuleRequest]


class PolicyDiffResponse(BaseModel):
    content_preview: str
    current_action: str
    current_triggered_rule: Optional[str]
    current_reason: str
    proposed_action: str
    proposed_triggered_rule: Optional[str]
    proposed_reason: str
    decision_changed: bool
    change_summary: str


class SnapshotResponse(BaseModel):
    generated_at: float
    start_time: Optional[float]
    end_time: Optional[float]
    record_count: int
    records: list[Any]
    chain_valid: bool
    chain_verification_reason: str
    latest_hash: str
    snapshot_hash: str


class SnapshotVerifyRequest(BaseModel):
    snapshot: dict[str, Any]


class SnapshotVerifyResponse(BaseModel):
    valid: bool
    reason: str


# ---------------------------------------------------------------------------
# v0.5 — Tenant schemas
# ---------------------------------------------------------------------------

class TenantRegisterRequest(BaseModel):
    tenant_id: str = Field(..., min_length=1, max_length=64)
    requests_per_minute: int = Field(default=60, ge=1, le=10_000)
    requests_per_hour: int = Field(default=1000, ge=1, le=100_000)
    tokens_per_minute: int = Field(default=100_000, ge=1, le=10_000_000)

    @field_validator("tenant_id")
    @classmethod
    def tenant_id_not_reserved(cls, v: str) -> str:
        if v != v.strip():
            raise ValueError("tenant_id must not have leading/trailing whitespace")
        return v


class TenantResponse(BaseModel):
    tenant_id: str
    requests_per_minute: int
    requests_per_hour: int
    tokens_per_minute: int
    registered: bool = True


class TenantListResponse(BaseModel):
    tenants: list[str]
    count: int

# ---------------------------------------------------------------------------
# v1.1 — Tenant policy rule management (closes #20)
# ---------------------------------------------------------------------------

class PolicyRuleAddResponse(BaseModel):
    tenant_id: str
    rule: PolicyRuleRequest
    total_custom_rules: int


class PolicyRuleListResponse(BaseModel):
    tenant_id: str
    rules: list[PolicyRuleRequest]
    count: int


# ---------------------------------------------------------------------------
# v1.2 — Execution Enforcement schemas
# ---------------------------------------------------------------------------

class ExecuteRequest(BaseModel):
    """Request to evaluate AND execute against a downstream target.

    If the policy engine returns ALLOW, the content is forwarded to the
    target_url. If DENY, the request is blocked and never reaches the target.
    """
    client_id: str = Field(default="default", min_length=1, max_length=128)
    content: str = Field(..., min_length=1, max_length=32_768)
    tenant_id: str = Field(default="default", min_length=1, max_length=64)
    token_count: int = Field(default=1, ge=1, le=100_000)
    target_url: str = Field(..., min_length=1, max_length=2048)
    target_method: str = Field(default="POST", pattern="^(GET|POST|PUT|PATCH|DELETE)$")
    target_headers: Optional[dict[str, str]] = Field(default=None)
    target_timeout: float = Field(default=10.0, ge=1.0, le=60.0)

    @field_validator("client_id")
    @classmethod
    def client_id_no_whitespace(cls, v: str) -> str:
        if v != v.strip():
            raise ValueError("client_id must not have leading/trailing whitespace")
        return v

    @field_validator("content")
    @classmethod
    def content_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("content must not be blank or whitespace only")
        return v

    @field_validator("target_url")
    @classmethod
    def target_url_must_be_https(cls, v: str) -> str:
        if not v.startswith("https://"):
            raise ValueError("target_url must use HTTPS")
        return v


class ExecuteResponse(BaseModel):
    """Response from the execution firewall.

    If denied: `forwarded` is False, `status_code` is None.
    If allowed and forwarded: `forwarded` is True, `status_code` is the
    downstream response code.
    If allowed but circuit open: `forwarded` is False, `circuit_open` is True.
    """
    allowed: bool
    action: str
    triggered_rule: Optional[str]
    reason: str
    client_id: str
    tenant_id: str = "default"
    forwarded: bool = False
    status_code: Optional[int] = None
    response_preview: Optional[str] = None
    circuit_open: bool = False
    audit_record_hash: Optional[str] = None
    trace_id: Optional[str] = None


class CircuitBreakerStatus(BaseModel):
    state: str  # closed, open, half_open
    failure_count: int
    failure_threshold: int
    last_failure_time: Optional[float] = None
    reset_timeout: float
