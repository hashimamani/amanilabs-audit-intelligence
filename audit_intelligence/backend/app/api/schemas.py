from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


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
    model_config = ConfigDict(from_attributes=True)

    id: int
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


class CaseDetailOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    case_ref: str
    run_id: int
    subject_type: str
    subject_id: str
    subject_name: str
    risk_score: float
    severity: str
    status: str
    triggered_rules: list[str]
    flags: list[FlagOut]
    evidence: list[EvidenceOut]
    timeline: list[dict]
    related_entities: dict[str, list[str]]
    recommended_actions: list[str]
    assigned_auditor: str | None
    notes: list[str]
    outcome: str | None
    ai_summary: str | None
    created_at: datetime
    updated_at: datetime


class CaseUpdateIn(BaseModel):
    status: str | None = None
    assigned_auditor: str | None = None
    outcome: str | None = None
    add_note: str | None = None


class BulkCaseStatusIn(BaseModel):
    case_ids: list[int]
    status: str


class BulkCaseStatusOut(BaseModel):
    updated_count: int


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
    case_ids: list[int] | None = None


class ReportGenerateOut(BaseModel):
    report_text: str
    case_count: int
    generated_at: datetime


class UserOut(BaseModel):
    id: int
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
    password: str
    role: Literal["auditor", "admin"]


class UserUpdateIn(BaseModel):
    role: Literal["auditor", "admin"] | None = None
    is_active: bool | None = None


class UploadOut(BaseModel):
    dataset_id: str
    files_received: list[str]


class RunAnalysisIn(BaseModel):
    dataset_id: str | None = None


class RunSummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    dataset_id: str
    created_at: datetime
    flag_count: int
    case_count: int
