"""
Runs the rule engine against the synthetic dataset and reports:
1. Detection rate per injected fraud scenario (did we catch it?)
2. Total flags raised, broken down by rule
3. A rough noise estimate: flags NOT traceable to any injected scenario

This is the harness that answers "does the demo actually work" before
you ever show it to a SACCO.
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
    engine = RuleEngine()
    flags = engine.run(dataset)

    with open(f"{DATA_DIR}/ground_truth.json") as f:
        ground_truth = json.load(f)

    # Build a set of every injected "record id" mentioned in ground truth,
    # flattening things like "loan_id/transaction_id" combos.
    injected_ids = set()
    for scenario in ground_truth:
        for rid in scenario["record_ids"]:
            for part in rid.split("/"):
                injected_ids.add(part)

    # Flatten flag entity_ids (some flags bundle multiple ids comma-separated)
    flagged_ids = set()
    for f in flags:
        for part in f.entity_id.split(","):
            flagged_ids.add(part.strip())
        if f.member_id:
            flagged_ids.add(f.member_id)

    print("=" * 70)
    print("RULE ENGINE OUTPUT SUMMARY")
    print("=" * 70)
    by_rule = {}
    for f in flags:
        by_rule.setdefault(f.rule_name, 0)
        by_rule[f.rule_name] += 1
    for rule_name, count in sorted(by_rule.items(), key=lambda x: -x[1]):
        print(f"  {rule_name:40s} {count:5d} flags")
    print(f"  {'TOTAL':40s} {len(flags):5d} flags")

    print()
    print("=" * 70)
    print("DETECTION RATE PER INJECTED SCENARIO")
    print("=" * 70)
    total_scenarios = len(ground_truth)
    caught = 0
    for scenario in ground_truth:
        scenario_ids = set()
        for rid in scenario["record_ids"]:
            for part in rid.split("/"):
                scenario_ids.add(part)
        hit = bool(scenario_ids & flagged_ids)
        caught += int(hit)
        status = "CAUGHT" if hit else "MISSED"
        print(f"  [{status}] {scenario['scenario']:35s} {scenario['description'][:60]}")

    print()
    print(f"Detected {caught}/{total_scenarios} injected scenario instances")

    print()
    print("=" * 70)
    print("NOISE CHECK (flags with no traceable injected record - expect > 0,")
    print("since real anomalies can legitimately arise from random baseline")
    print("generation too; the question is whether the volume is reasonable)")
    print("=" * 70)
    untraceable = flagged_ids - injected_ids
    print(f"Flagged IDs not matching any injected scenario: {len(untraceable)}")
    print(f"Total unique flagged IDs: {len(flagged_ids)}")
    print(f"Total unique injected IDs: {len(injected_ids)}")


if __name__ == "__main__":
    main()
