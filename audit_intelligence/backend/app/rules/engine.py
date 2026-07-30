"""
RuleEngine: runs all registered rules against a SaccoDataset and returns
a unified, sorted list of Flags.

Design decision: rules are registered explicitly in a list rather than
auto-discovered via reflection. Explicit is safer for an audit product -
you always know exactly which rules ran and in what order, which matters
if you ever need to explain to a regulator or client "what did the system
check."
"""

from app.rules.dataset import SaccoDataset
from app.rules.config import DEFAULT_CONFIG
from app.rules.large_withdrawal import LargeWithdrawalRule
from app.rules.dormant_account import DormantAccountRule
from app.rules.duplicate_transaction import DuplicateTransactionRule
from app.rules.rapid_transfers import RapidTransfersRule
from app.rules.employee_behaviour import EmployeeLoanApprovalAnomalyRule
from app.rules.repeated_guarantor import RepeatedGuarantorRule
from app.rules.offhours_approval import OffHoursApprovalRule
from app.rules.disbursement_withdrawal import DisbursementWithdrawalRule
from app.rules.fraud_ring import FraudRingRule

RULE_REGISTRY = [
    LargeWithdrawalRule,
    DormantAccountRule,
    DuplicateTransactionRule,
    RapidTransfersRule,
    EmployeeLoanApprovalAnomalyRule,
    RepeatedGuarantorRule,
    OffHoursApprovalRule,
    DisbursementWithdrawalRule,
    FraudRingRule,
]

SEVERITY_ORDER = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}


class RuleEngine:
    def __init__(self, config: dict | None = None):
        self.config = config or DEFAULT_CONFIG
        self.rules = [cls(self.config.get(cls.rule_id, {})) for cls in RULE_REGISTRY]

    def run(self, dataset: SaccoDataset) -> list:
        all_flags = []
        for rule in self.rules:
            flags = rule.evaluate(dataset)
            all_flags.extend(flags)

        all_flags.sort(key=lambda f: SEVERITY_ORDER.get(f.severity.value, 99))
        return all_flags

    def run_from_dir(self, data_dir: str) -> list:
        dataset = SaccoDataset(data_dir)
        return self.run(dataset)
