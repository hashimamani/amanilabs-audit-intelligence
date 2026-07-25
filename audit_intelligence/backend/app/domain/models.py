"""
Core domain models for the rule engine.

These are plain dataclasses, deliberately independent of any ORM/DB model.
The rule engine operates purely on pandas DataFrames in and Flag objects out;
persistence is a separate concern (see backend/app/api layer, added later).
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class Severity(str, Enum):
    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"
    CRITICAL = "Critical"


@dataclass
class Evidence:
    """A single concrete, quotable fact supporting a flag.

    Kept as field/value pairs (not free text) so the UI can render them as
    a clean evidence table, and so an AI summarizer later has structured
    facts to reference instead of needing to invent phrasing.
    """
    label: str
    value: str


@dataclass
class Flag:
    """One rule firing on one entity (transaction, loan, employee, etc.)."""
    rule_id: str
    rule_name: str
    severity: Severity
    entity_type: str          # "transaction", "loan", "employee", "member"
    entity_id: str            # e.g. transaction_id or loan_id
    member_id: str | None
    explanation: str          # plain-English "why this was flagged"
    evidence: list[Evidence] = field(default_factory=list)
    suggested_steps: list[str] = field(default_factory=list)
    triggered_at: datetime | None = None

    def to_dict(self) -> dict:
        return {
            "rule_id": self.rule_id,
            "rule_name": self.rule_name,
            "severity": self.severity.value,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "member_id": self.member_id,
            "explanation": self.explanation,
            "evidence": [{"label": e.label, "value": e.value} for e in self.evidence],
            "suggested_steps": self.suggested_steps,
            "triggered_at": self.triggered_at.isoformat() if self.triggered_at else None,
        }


@dataclass
class Case:
    """An investigation case: one or more corroborating Flags grouped onto
    a single subject (a member or an employee), for an auditor to open and
    work as one unit rather than chasing flags individually.

    ai_summary is a deliberate placeholder - per the product's explainability
    principle, this must only ever summarize the evidence already attached
    to this case, never invent facts, and stays None until that layer is built.
    """
    case_id: str
    subject_type: str          # "member" or "employee"
    subject_id: str
    subject_name: str
    risk_score: float
    severity: Severity
    status: str
    triggered_rules: list[str]
    flags: list[Flag]
    evidence: list[Evidence]
    timeline: list[dict]
    related_entities: dict[str, list[str]]
    recommended_actions: list[str]
    assigned_auditor: str | None = None
    notes: list[str] = field(default_factory=list)
    outcome: str | None = None
    ai_summary: str | None = None

    def to_dict(self) -> dict:
        return {
            "case_id": self.case_id,
            "subject_type": self.subject_type,
            "subject_id": self.subject_id,
            "subject_name": self.subject_name,
            "risk_score": self.risk_score,
            "severity": self.severity.value,
            "status": self.status,
            "triggered_rules": self.triggered_rules,
            "flags": [f.to_dict() for f in self.flags],
            "evidence": [{"label": e.label, "value": e.value} for e in self.evidence],
            "timeline": self.timeline,
            "related_entities": self.related_entities,
            "recommended_actions": self.recommended_actions,
            "assigned_auditor": self.assigned_auditor,
            "notes": self.notes,
            "outcome": self.outcome,
            "ai_summary": self.ai_summary,
        }
