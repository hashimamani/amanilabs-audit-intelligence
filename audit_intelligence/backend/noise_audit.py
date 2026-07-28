"""
Breaks the "75 untraceable ids" noise number from validate_against_ground_truth.py
down into two very different things it was conflating:

1. Flags whose core entity_id (the transaction/loan/employee/member the flag
   is actually about) matches no injected record at all - these are the real
   candidates for "organic noise": anomalies the rule engine found in the
   randomly-generated baseline data, not anything deliberately injected.
2. Flags whose entity_id DOES match an injected record, but whose member_id
   alone doesn't appear in ground truth - ground_truth.json only logs member
   ids as record_ids for scenarios 5/6 (employee_loan_approval_anomaly,
   repeated_guarantor), per PROJECT_CONTEXT.md section 3. For every other
   scenario, a flag's member_id being "untraceable" is an artifact of how the
   original script builds flagged_ids (it always adds member_id to the set),
   not a sign the flag is spurious. This inflates the raw 75 number a lot.

See PROJECT_CONTEXT.md section 6/9 for why this audit matters before a demo.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app.rules.engine import RuleEngine
from app.rules.dataset import SaccoDataset

DATA_DIR = str(Path(__file__).resolve().parents[2] / "synthetic_sacco_data")


def main():
    dataset = SaccoDataset(DATA_DIR)
    flags = RuleEngine().run(dataset)

    with open(f"{DATA_DIR}/ground_truth.json") as f:
        ground_truth = json.load(f)

    injected_ids = set()
    for scenario in ground_truth:
        for rid in scenario["record_ids"]:
            for part in rid.split("/"):
                injected_ids.add(part)

    def entity_sub_ids(f):
        return {part.strip() for part in f.entity_id.split(",")}

    by_rule = {}
    for f in flags:
        by_rule.setdefault(f.rule_name, []).append(f)

    print("=" * 78)
    print("ORGANIC NOISE BY RULE (entity_id matches NO injected record at all)")
    print("=" * 78)

    total_flags = 0
    total_organic = 0

    for rule_name, rule_flags in sorted(by_rule.items(), key=lambda x: -len(x[1])):
        organic = [f for f in rule_flags if not (entity_sub_ids(f) & injected_ids)]
        total_flags += len(rule_flags)
        total_organic += len(organic)
        print(f"\n{rule_name}: {len(organic)} organic / {len(rule_flags)} total flags")
        for f in organic:
            ev = "; ".join(f"{e.label}={e.value}" for e in f.evidence)
            print(f"  - [{f.severity.value}] {f.entity_type} {f.entity_id} ({f.member_id})")
            print(f"      {f.explanation}")
            print(f"      {ev}")

    print()
    print("=" * 78)
    print(f"TOTAL organic (non-injected) flags: {total_organic} / {total_flags}")
    print("(the member-id-only 'untraceable' ids the original noise check also")
    print(" counts are a harness artifact for scenarios 1-4/7/8 - ground truth")
    print(" only logs member ids as record_ids for scenarios 5/6, so a flag can")
    print(" correctly match its injected transaction/loan and still show its")
    print(" member_id as 'untraceable'. Not counted as noise here.)")
    print("=" * 78)


if __name__ == "__main__":
    main()
