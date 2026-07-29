"""
Bridges the pure-Python Case objects the builder produces to DB rows.

case_ref is assigned HERE, not in builder.py, because it needs to be
globally unique across runs (the builder only knows about one run's worth
of flags at a time and numbers cases 1..N within that run).
"""

from sqlalchemy.orm import Session

from app.domain.models import Case
from app.db.models import AnalysisRunORM, CaseORM


def save_cases(db: Session, run: AnalysisRunORM, cases: list[Case]) -> list[CaseORM]:
    rows = []
    for i, case in enumerate(cases, start=1):
        row = CaseORM(
            case_ref=f"CASE-{run.id:04d}-{i:04d}",
            tenant_id=run.tenant_id,
            run_id=run.id,
            subject_type=case.subject_type,
            subject_id=case.subject_id,
            subject_name=case.subject_name,
            risk_score=case.risk_score,
            severity=case.severity.value,
            status=case.status,
            triggered_rules=case.triggered_rules,
            flags=[f.to_dict() for f in case.flags],
            evidence=[{"label": e.label, "value": e.value} for e in case.evidence],
            timeline=case.timeline,
            related_entities=case.related_entities,
            recommended_actions=case.recommended_actions,
            assigned_auditor=case.assigned_auditor,
            notes=case.notes,
            outcome=case.outcome,
            ai_summary=case.ai_summary,
        )
        db.add(row)
        rows.append(row)
    db.flush()
    return rows
