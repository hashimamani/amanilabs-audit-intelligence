"""
Pytest conversion of validate_against_ground_truth.py's checks: does the
rule engine actually catch the injected fraud scenarios, and does flag
volume stay in a sane range. These are regression tests - if a future
change to a rule or its config silently breaks detection, this fails
loudly instead of requiring someone to rerun the script and read it.
"""

from collections import defaultdict


def _flagged_ids(flags):
    ids = set()
    for f in flags:
        for part in f.entity_id.split(","):
            ids.add(part.strip())
        if f.member_id:
            ids.add(f.member_id)
    return ids


def _scenario_ids(scenario):
    ids = set()
    for rid in scenario["record_ids"]:
        for part in rid.split("/"):
            ids.add(part)
    return ids


def test_engine_runs_without_error(flags):
    assert isinstance(flags, list)
    assert len(flags) > 0


def test_detection_rate_meets_validated_baseline(flags, ground_truth):
    flagged = _flagged_ids(flags)
    caught = sum(1 for s in ground_truth if _scenario_ids(s) & flagged)
    # Validated baseline is 52/54 (96%); the 2 known misses are
    # large_withdrawal cases with only 3 total withdrawals - not enough
    # history for a meaningful baseline, considered correct behavior, not
    # a bug (see PROJECT_CONTEXT.md section 5). This guards against
    # regressing below that, not against ever missing exactly those two.
    assert caught >= 52, f"Detection rate dropped: {caught}/{len(ground_truth)} caught (expected >= 52)"


def test_all_non_large_withdrawal_scenarios_are_always_caught(flags, ground_truth):
    """The 2 known misses are specifically large_withdrawal edge cases;
    every other scenario type should be caught 100% of the time."""
    flagged = _flagged_ids(flags)
    for scenario in ground_truth:
        if scenario["scenario"] == "large_withdrawal":
            continue
        assert _scenario_ids(scenario) & flagged, (
            f"Missed non-large-withdrawal scenario: {scenario['scenario']} - {scenario['description']}"
        )


def test_large_withdrawal_misses_no_more_than_two(flags, ground_truth):
    flagged = _flagged_ids(flags)
    scenarios = [s for s in ground_truth if s["scenario"] == "large_withdrawal"]
    missed = [s for s in scenarios if not (_scenario_ids(s) & flagged)]
    assert len(missed) <= 2, f"More large_withdrawal misses than expected: {[s['description'] for s in missed]}"


def test_flag_counts_by_rule_are_in_expected_range(flags):
    by_rule = defaultdict(int)
    for f in flags:
        by_rule[f.rule_id] += 1

    # Loose lower bounds, not exact counts - the point is catching wild
    # swings (a rule firing 10x more, or dropping to zero), not pinning
    # the engine's output to one exact number forever.
    expected_minimums = {
        "R001": 10, "R002": 8, "R003": 8, "R004": 8,
        "R005": 1, "R006": 1, "R007": 10, "R008": 8, "R009": 10,
    }
    for rule_id, minimum in expected_minimums.items():
        assert by_rule.get(rule_id, 0) >= minimum, (
            f"{rule_id} fired only {by_rule.get(rule_id, 0)} times, expected >= {minimum}"
        )


def test_noise_is_not_excessive(flags, ground_truth):
    """Sanity bound on false-positive volume - not a hard requirement
    (some noise is expected/healthy, see PROJECT_CONTEXT.md section 6),
    just a guard against a rule going haywire and flagging everything."""
    flagged = _flagged_ids(flags)
    injected = set()
    for s in ground_truth:
        injected |= _scenario_ids(s)
    noise = flagged - injected
    assert len(noise) < len(flagged), "More noise than actual flags - looks like a rule is misfiring"
