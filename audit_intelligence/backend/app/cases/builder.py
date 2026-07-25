"""
CaseBuilder: groups the flat list of Flags the RuleEngine produces into
investigation Cases an auditor can actually work.

Grouping logic (deliberate design decision, documented here so it isn't
re-litigated later):

1. Subject = who the case is actually about. Most flags carry a member_id
   (the person whose account/loan looked anomalous), so that's the primary
   grouping key. The one exception is R005 (Employee Loan Approval
   Anomaly), which flags an employee and leaves member_id unset - for
   those, the employee is the subject instead. This mirrors how an
   auditor actually thinks about a case: "investigate this person," not
   "investigate this transaction."

2. Time window = same subject, but flags far apart in time are almost
   certainly unrelated incidents (e.g. one large withdrawal in February
   and an unrelated duplicate transfer in November), and dumping a
   member's entire year of activity into one case file would bury the
   signal. So flags on the same subject are only merged into one case if
   consecutive flags (sorted by time) are within `time_window_days` of
   each other - a classic single-linkage time clustering. Flags with no
   timestamp (currently only R006 Repeated Guarantor, which is a
   standing-pattern flag rather than a point-in-time event) can't be
   clustered by time, so they attach to the subject's earliest
   time-anchored cluster if one exists, or become their own case
   otherwise.

3. Risk score = severity-weighted, with diminishing returns for additional
   corroborating flags rather than a flat sum. One Critical flag alone
   should already read as high risk; a second Medium flag on the same
   person should push the score up further (corroboration matters) but
   not double-count it. Capped at 100.
"""

from collections import defaultdict
from datetime import timedelta

from app.domain.models import Case, Evidence, Severity
from app.cases.config import DEFAULT_CASE_CONFIG

SEVERITY_WEIGHT = {"Critical": 100, "High": 70, "Medium": 40, "Low": 15}

# Each additional flag beyond the top one contributes at this fraction of
# its own weight - corroboration raises risk, but N flags isn't N times riskier.
CORROBORATION_FACTOR = 0.35


def _subject_key(flag) -> tuple[str, str]:
    if flag.entity_type == "employee":
        return ("employee", flag.entity_id)
    if flag.member_id:
        return ("member", flag.member_id)
    return (flag.entity_type, flag.entity_id)


def _risk_score(flags: list) -> float:
    weights = sorted((SEVERITY_WEIGHT.get(f.severity.value, 10) for f in flags), reverse=True)
    if not weights:
        return 0.0
    score = weights[0] + sum(w * CORROBORATION_FACTOR for w in weights[1:])
    return round(min(score, 100.0), 1)


def _severity_bucket(score: float) -> Severity:
    if score >= 90:
        return Severity.CRITICAL
    if score >= 60:
        return Severity.HIGH
    if score >= 35:
        return Severity.MEDIUM
    return Severity.LOW


def _related_entities(flags: list) -> dict[str, list[str]]:
    related = defaultdict(set)
    for f in flags:
        related[f.entity_type + "s"].add(f.entity_id)
        if f.member_id:
            related["members"].add(f.member_id)
    return {k: sorted(v) for k, v in related.items()}


def _subject_name(dataset, subject_type: str, subject_id: str) -> str:
    if dataset is None:
        return subject_id
    if subject_type == "member":
        return dataset.member_name(subject_id)
    if subject_type == "employee":
        return dataset.employee_name(subject_id)
    return subject_id


def _cluster_by_time(flags: list, window: timedelta) -> list[list]:
    """Single-linkage clustering on a sorted-by-time flag list: start a new
    cluster whenever the gap since the previous flag exceeds the window."""
    timestamped = sorted((f for f in flags if f.triggered_at is not None), key=lambda f: f.triggered_at)
    untimestamped = [f for f in flags if f.triggered_at is None]

    clusters = []
    for f in timestamped:
        if clusters and f.triggered_at - clusters[-1][-1].triggered_at <= window:
            clusters[-1].append(f)
        else:
            clusters.append([f])

    if not clusters:
        return [untimestamped] if untimestamped else []

    clusters[0] = untimestamped + clusters[0]
    return clusters


def build_cases(flags: list, dataset=None, config: dict | None = None) -> list[Case]:
    cfg = config or DEFAULT_CASE_CONFIG
    window = timedelta(days=cfg.get("time_window_days", 45))

    by_subject = defaultdict(list)
    for f in flags:
        by_subject[_subject_key(f)].append(f)

    scored_clusters = []
    for (subject_type, subject_id), subject_flags in by_subject.items():
        for cluster in _cluster_by_time(subject_flags, window):
            if cluster:
                scored_clusters.append((subject_type, subject_id, cluster, _risk_score(cluster)))

    # Deterministic ordering so case IDs are stable across runs on the same
    # input: highest risk first, then subject as a tiebreak.
    scored_clusters.sort(key=lambda c: (-c[3], c[0], c[1]))

    cases = []
    for i, (subject_type, subject_id, cluster_flags, score) in enumerate(scored_clusters, start=1):
        timeline = [
            {
                "timestamp": f.triggered_at.isoformat() if f.triggered_at else None,
                "rule_id": f.rule_id,
                "rule_name": f.rule_name,
                "explanation": f.explanation,
            }
            for f in sorted(cluster_flags, key=lambda f: (f.triggered_at is None, f.triggered_at))
        ]

        evidence: list[Evidence] = []
        for f in cluster_flags:
            evidence.extend(f.evidence)

        actions: list[str] = []
        for f in cluster_flags:
            for step in f.suggested_steps:
                if step not in actions:
                    actions.append(step)

        cases.append(Case(
            case_id=f"CASE-{i:04d}",
            subject_type=subject_type,
            subject_id=subject_id,
            subject_name=_subject_name(dataset, subject_type, subject_id),
            risk_score=score,
            severity=_severity_bucket(score),
            status="Open",
            triggered_rules=sorted({f.rule_id for f in cluster_flags}),
            flags=cluster_flags,
            evidence=evidence,
            timeline=timeline,
            related_entities=_related_entities(cluster_flags),
            recommended_actions=actions,
        ))

    return cases
