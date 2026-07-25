"""
Pytest conversion of generate_cases_report.py's checks: does grouping
Flags into Cases preserve data (no flags lost/duplicated), stay unique,
and behave correctly on the known multi-signal / employee-subject cases
in the synthetic dataset.
"""


def test_no_flags_lost_or_duplicated_during_grouping(flags, cases):
    assert sum(len(c.flags) for c in cases) == len(flags)


def test_case_ids_are_unique(cases):
    case_ids = [c.case_id for c in cases]
    assert len(case_ids) == len(set(case_ids))


def test_every_case_has_at_least_one_flag(cases):
    assert all(len(c.flags) >= 1 for c in cases)


def test_risk_score_is_bounded(cases):
    assert all(0 <= c.risk_score <= 100 for c in cases)


def test_employee_anomaly_produces_an_employee_subject_case(cases):
    employee_cases = [c for c in cases if c.subject_type == "employee"]
    assert employee_cases, "Expected at least one employee-subject case from R005"
    assert all(c.subject_id.startswith("EMP") for c in employee_cases)


def test_multi_flag_cases_have_chronologically_sorted_timelines(cases):
    multi = [c for c in cases if len(c.flags) > 1]
    assert multi, "Expected at least one multi-flag corroborated case in this dataset"
    for c in multi:
        timestamps = [e["timestamp"] for e in c.timeline if e["timestamp"] is not None]
        assert timestamps == sorted(timestamps)


def test_cases_are_sorted_by_risk_score_descending(cases):
    scores = [c.risk_score for c in cases]
    assert scores == sorted(scores, reverse=True)


def test_untimestamped_repeated_guarantor_flags_still_form_a_case(cases):
    guarantor_cases = [c for c in cases if "R006" in c.triggered_rules]
    assert guarantor_cases, "Expected at least one case from the untimestamped Repeated Guarantor rule"
