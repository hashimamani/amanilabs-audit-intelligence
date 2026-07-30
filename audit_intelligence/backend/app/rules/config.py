"""
Default thresholds for each rule. In the full product these would be
stored per-tenant in the database and editable by an admin; for now this
is the single source of truth the engine reads from.
"""

DEFAULT_CONFIG = {
    "R001": {"multiplier": 10, "min_txns_for_baseline": 3},
    "R002": {"dormancy_days": 180, "min_withdrawal_amount": 5000},
    "R003": {},
    "R004": {"window_minutes": 60, "min_transfers_in_window": 5},
    "R005": {"std_multiplier": 2.0, "min_loans": 15},
    "R006": {"max_loans_guaranteed": 5},
    "R007": {"business_start_hour": 8, "business_end_hour": 17},
    "R008": {"max_hours_between": 24, "min_fraction_withdrawn": 0.9},
    "R009": {"min_cycle_length": 3, "max_cycle_length": 6, "synchronized_window_days": 14},
}
