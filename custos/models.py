"""
CUSTOS Pydantic Models v0.3
Added trace_id to EvaluateResponse and AuditRecordResponse.
"""

from typing import Optional
from pydantic import BaseModel, Field, field_validator


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


class EvaluateResponse(BaseModel):
    allowed: bool
    action: str
    triggered_rule: Optional[str]
    reason: str
    client_id: str
    audit_record_hash: Optional[str] = None
    trace_id: Optional[str] = None          # v0.3: span correlation


class HealthResponse(BaseModel):
    status: str
    uptime_seconds: float


class ReadyResponse(BaseModel):
    status: str
    checks: dict


class MetricsSnapshot(BaseModel):
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
    trace_id: Optional[str] = None          # v0.3: span correlation
