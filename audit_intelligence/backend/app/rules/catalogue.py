"""
What each rule checks, in the words an auditor or a board member would use.
The engine's own classes carry the id, the name and the thresholds; this is
the explanation that sits beside them in the UI and in reports.
"""

from app.rules.config import DEFAULT_CONFIG
from app.rules.engine import RULE_REGISTRY

DESCRIPTIONS: dict[str, dict[str, str]] = {
    "R001": {
        "summary": "A withdrawal far larger than the member's own normal behaviour.",
        "detail": (
            "Compares each withdrawal against that member's average withdrawal (excluding the one "
            "under review). Members with fewer than three other withdrawals are skipped rather "
            "than flagged on a meaningless average."
        ),
        "signal": "Account takeover, coercion, or a teller moving funds out through a member's account.",
    },
    "R002": {
        "summary": "A withdrawal from an account that had been quiet for months.",
        "detail": (
            "Flags a withdrawal that follows a long gap since the member's previous transaction. "
            "A member with no prior activity is measured from their join date instead."
        ),
        "signal": "Dormant-account raids, where an insider drains accounts nobody is watching.",
    },
    "R003": {
        "summary": "The same amount to the same recipient on the same day, more than once.",
        "detail": "Groups transactions by member, amount, recipient and date and flags repeats.",
        "signal": "Double-posting, replayed transactions, or splitting to hide a transfer.",
    },
    "R004": {
        "summary": "A burst of outgoing transfers within a short window.",
        "detail": "Counts outgoing transfers per member inside a sliding time window.",
        "signal": "Structuring to stay under limits, or an account being emptied quickly.",
    },
    "R005": {
        "summary": "A loan officer approving far more loans than their branch peers.",
        "detail": (
            "Compares officers only to colleagues at the same branch, so a busy branch is not "
            "mistaken for a suspicious officer. Branches with three or more officers use a "
            "statistical comparison; smaller branches compare the top officer to the next."
        ),
        "signal": "Ghost loans, kickbacks, or an officer bypassing the credit committee.",
    },
    "R006": {
        "summary": "One member guaranteeing an unusual number of loans.",
        "detail": "Counts the loans each member stands guarantor for.",
        "signal": "Straw guarantors used to push through loans that would not otherwise qualify.",
    },
    "R007": {
        "summary": "A loan approved on a weekend or outside business hours.",
        "detail": "Checks the approval timestamp against the business week and working hours.",
        "signal": "Approvals made when nobody is around to question them.",
    },
    "R008": {
        "summary": "A loan withdrawn almost entirely within hours of being disbursed.",
        "detail": "Measures how much of the disbursed amount left the account within the window after disbursement.",
        "signal": "Loans taken out to be cashed immediately, often by someone other than the member.",
    },
    "R009": {
        "summary": "Members whose guarantees form a closed loop, or who share identity details.",
        "detail": (
            "Builds the guarantor network and looks for circular guarantee chains (A guarantees B, "
            "B guarantees C, C guarantees A), rated more severely when the loans were approved "
            "within days of each other. Separately groups members sharing a phone number or "
            "national ID. Network analysis, not a trained model: every flag names the loop or the "
            "shared value."
        ),
        "signal": "Collusion rings where nobody has independent backing, and duplicate registrations.",
    },
}

THRESHOLD_LABELS: dict[str, str] = {
    "multiplier": "times the member's average withdrawal",
    "min_txns_for_baseline": "other withdrawals needed for a baseline",
    "dormancy_days": "days without activity",
    "min_withdrawal_amount": "minimum withdrawal (KES)",
    "window_minutes": "window (minutes)",
    "min_transfers_in_window": "transfers in the window",
    "std_multiplier": "standard deviations above branch peers",
    "min_loans": "minimum loans before comparison",
    "max_loans_guaranteed": "loans guaranteed",
    "business_start_hour": "business day starts (hour)",
    "business_end_hour": "business day ends (hour)",
    "max_hours_between": "hours after disbursement",
    "min_fraction_withdrawn": "fraction of the loan withdrawn",
    "min_cycle_length": "shortest loop counted",
    "max_cycle_length": "longest loop counted",
    "synchronized_window_days": "days for approvals to count as synchronised",
}


def rule_catalogue() -> list[dict]:
    rules = []
    for cls in RULE_REGISTRY:
        description = DESCRIPTIONS[cls.rule_id]
        thresholds = [
            {"key": key, "label": THRESHOLD_LABELS.get(key, key), "value": value}
            for key, value in DEFAULT_CONFIG.get(cls.rule_id, {}).items()
        ]
        rules.append({"rule_id": cls.rule_id, "rule_name": cls.rule_name, **description, "thresholds": thresholds})
    return rules
