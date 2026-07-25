"""
Base interface every fraud/anomaly rule must implement.

Design decision: rules are config-driven (thresholds passed in via a dict,
not hardcoded) so a SACCO's audit team can tune sensitivity per-institution
without a code deploy. Defaults live in rules/config.py.
"""

from abc import ABC, abstractmethod
from app.domain.models import Flag


class Rule(ABC):
    rule_id: str
    rule_name: str

    def __init__(self, config: dict):
        self.config = config

    @abstractmethod
    def evaluate(self, dataset: "SaccoDataset") -> list[Flag]:
        """Run this rule against the full dataset and return any flags."""
        raise NotImplementedError
