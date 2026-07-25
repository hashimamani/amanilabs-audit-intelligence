"""
Runs the rule engine + case builder against the synthetic dataset and
reports case-level output: how many cases came out of how many flags,
severity distribution, and the highest-risk cases in detail - so you can
eyeball whether the grouping and scoring actually make sense before this
ever becomes an API response.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app.rules.engine import RuleEngine
from app.rules.dataset import SaccoDataset
from app.cases.builder import build_cases

DATA_DIR = str(Path(__file__).resolve().parents[2] / "synthetic_sacco_data")


def main():
    dataset = SaccoDataset(DATA_DIR)
    engine = RuleEngine()
    flags = engine.run(dataset)
    cases = build_cases(flags, dataset=dataset)

    print("=" * 70)
    print("CASE GENERATION SUMMARY")
    print("=" * 70)
    print(f"Flags in:  {len(flags)}")
    print(f"Cases out: {len(cases)}")

    by_severity = {}
    for c in cases:
        by_severity[c.severity.value] = by_severity.get(c.severity.value, 0) + 1
    for sev in ["Critical", "High", "Medium", "Low"]:
        print(f"  {sev:10s} {by_severity.get(sev, 0):4d} cases")

    multi_flag_cases = [c for c in cases if len(c.flags) > 1]
    print(f"\nCases with 2+ corroborating flags: {len(multi_flag_cases)}")

    case_ids = {c.case_id for c in cases}
    assert len(case_ids) == len(cases), "case_id collision detected"
    assert sum(len(c.flags) for c in cases) == len(flags), "flags lost or duplicated during grouping"

    print()
    print("=" * 70)
    print("TOP 15 CASES BY RISK SCORE")
    print("=" * 70)
    for c in cases[:15]:
        rules = ", ".join(c.triggered_rules)
        print(f"  [{c.case_id}] {c.subject_type:8s} {c.subject_id:8s} "
              f"score={c.risk_score:5.1f} sev={c.severity.value:8s} "
              f"flags={len(c.flags)}  rules=[{rules}]  {c.subject_name}")

    if multi_flag_cases:
        print()
        print("=" * 70)
        print("SAMPLE MULTI-FLAG CASE (full timeline)")
        print("=" * 70)
        c = multi_flag_cases[0]
        print(f"  {c.case_id} - {c.subject_name} ({c.subject_id}) - risk {c.risk_score}")
        for event in c.timeline:
            print(f"    [{event['rule_name']}] {event['timestamp']}: {event['explanation'][:90]}")


if __name__ == "__main__":
    main()
