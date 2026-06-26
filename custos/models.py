"""
CUSTOS Pydantic Models

Single source of truth for all request/response schemas.
Separating models from route handlers keeps main.py clean
and makes schemas reusable across CLI, SDK, and API layers.
"""

from typing import Optional
from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Request Models
# ---------------------------------------------------------------------------

class EvaluateRequest(BaseModel):
    client_id: str = Field(default="default", min_length=1, max_length=128)
    content: str = Field(..., min_length=1, max_length=32_768)
    token_count: int = Field(default=1, ge=1, le=100_000)

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


# ---------------------------------------------------------------------------
# Response Models
# ---------------------------------------------------------------------------

class EvaluateResponse(BaseModel):
    allowed: bool
    action: str                        # "allow" | "deny" | "audit"
    triggered_rule: Optional[str]
    reason: str
    client_id: str
    audit_record_hash: Optional[str] = None   # chain hash for tamper evidence


class HealthResponse(BaseModel):
    status: str
    uptime_seconds: float


class ReadyResponse(BaseModel):
    status: str                        # "ready" | "not_ready"
    checks: dict                       # named subsystem checks


class MetricsSnapshot(BaseModel):
    """Structured metrics for internal use -- /metrics endpoint returns Prometheus text."""
    requests_total: int
    requests_allowed: int
    requests_denied: int
    requests_audited: int
    rate_limit_hits: int
    audit_chain_length: int
    uptime_seconds: float


class AuditRecordResponse(BaseModel):
    timestamp: float
    client_id: str
    action: str
    triggered_rule: Optional[str]
    reason: str
    content_hash: str
    record_hash: str
    previous_hash: str
