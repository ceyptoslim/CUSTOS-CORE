"""
CUSTOS Pydantic Models v0.4
Added schemas for replay, policy diff, and snapshot endpoints.
"""

from typing import Any, Optional
from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Existing schemas (unchanged)
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


class EvaluateResponse(BaseModel):
    allowed: bool
    action: str
    triggered_rule: Optional[str]
    reason: str
    client_id: str
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
# v0.4 — Replay schemas
# ---------------------------------------------------------------------------

class ReplayRequest(BaseModel):
    record_hash: str = Field(..., min_length=64, max_length=64)
    original_content: str = Field(..., min_length=1, max_length=32_768)


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


# ---------------------------------------------------------------------------
# v0.4 — Policy diff schemas
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# v0.4 — Snapshot schemas
# ---------------------------------------------------------------------------

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
    
