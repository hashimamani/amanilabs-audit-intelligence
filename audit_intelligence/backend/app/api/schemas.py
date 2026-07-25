from datetime import datetime

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
