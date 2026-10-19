from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel


class EvidenceOut(BaseModel):
    label: str
    value: str


class FlagOut(BaseModel):
    rule_id: str
    rule_name: str
    severity: str
    entity_type: str
    entity_id: str
    member_id: str | None
    explanation: str
    evidence: list[EvidenceOut]
    suggested_steps: list[str]
    triggered_at: str | None


class CaseSummaryOut(BaseModel):
    id: str
    case_ref: str
    run_id: int
    subject_type: str
    subject_id: str
    subject_name: str
    risk_score: float
    severity: str
    status: str
    triggered_rules: list[str]
    flag_count: int
    created_at: datetime
    updated_at: datetime


class CaseDetailOut(CaseSummaryOut):
    flags: list[FlagOut]
    evidence: list[EvidenceOut]
    timeline: list[dict]
    related_entities: dict[str, list[str]]
    recommended_actions: list[str]
    assigned_auditor: str | None
    notes: list[str]
    outcome: str | None
    ai_summary: str | None


class CaseUpdateIn(BaseModel):
    status: str | None = None
    assigned_auditor: str | None = None
    outcome: str | None = None
    add_note: str | None = None


class BulkCaseStatusIn(BaseModel):
    case_ids: list[str]
    status: str


class BulkCaseStatusOut(BaseModel):
    updated_count: int


class ActivityOut(BaseModel):
    at: datetime
    actor_email: str
    actor_name: str
    action: str
    detail: dict[str, Any]


class CaseAskIn(BaseModel):
    question: str


class CaseAskOut(BaseModel):
    answer: str


class ChartDatapointOut(BaseModel):
    label: str
    value: float


class AnalyticsQueryIn(BaseModel):
    question: str


class AnalyticsQueryOut(BaseModel):
    title: str
    chart_type: str
    data: list[ChartDatapointOut]


class ReportGenerateIn(BaseModel):
    case_ids: list[str] | None = None


class ReportGenerateOut(BaseModel):
    report_text: str
    case_count: int
    generated_at: datetime


class JobOut(BaseModel):
    id: str
    kind: Literal["analysis", "analytics", "report"]
    status: Literal["queued", "running", "succeeded", "failed"]
    result: dict[str, Any] | None
    error: str | None
    created_at: datetime
    updated_at: datetime


class UserOut(BaseModel):
    id: str
    email: str
    name: str
    role: str
    is_active: bool
    tenant_slug: str
    tenant_name: str


class LoginIn(BaseModel):
    email: str
    password: str


class LoginOut(BaseModel):
    access_token: str
    user: UserOut


class UserCreateIn(BaseModel):
    email: str
    name: str
    role: Literal["auditor", "admin"]
    password: str | None = None


class UserUpdateIn(BaseModel):
    role: Literal["auditor", "admin"] | None = None
    is_active: bool | None = None


class UploadTargetOut(BaseModel):
    file: str
    url: str
    method: str


class DatasetCreateOut(BaseModel):
    dataset_id: str
    uploads: list[UploadTargetOut]


class DatasetOut(BaseModel):
    dataset_id: str
    status: Literal["pending", "ready", "invalid"]
    errors: list[str]
    created_at: datetime


class RunAnalysisIn(BaseModel):
    dataset_id: str | None = None


class RunOut(BaseModel):
    id: int
    dataset_id: str
    status: Literal["queued", "running", "succeeded", "failed"]
    job_id: str | None
    created_at: datetime
    completed_at: datetime | None
    flag_count: int
    case_count: int
    severity_counts: dict[str, int]
    rule_counts: dict[str, int]
    error: str | None


class RuleThresholdOut(BaseModel):
    key: str
    label: str
    value: float | int


class RuleOut(BaseModel):
    rule_id: str
    rule_name: str
    summary: str
    detail: str
    signal: str
    thresholds: list[RuleThresholdOut]
