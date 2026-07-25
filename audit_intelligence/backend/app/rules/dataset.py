"""
SaccoDataset: loads the raw CSV exports and precomputes shared derived
statistics (e.g. each member's average withdrawal) that multiple rules need.

Design decision: precompute once here rather than have every rule recompute
its own per-member averages - keeps rules simple and keeps the engine fast
enough to run on a full year of transactions interactively.
"""

import pandas as pd
from pathlib import Path


class SaccoDataset:
    def __init__(self, data_dir: str):
        p = Path(data_dir)
        self.members = pd.read_csv(p / "members.csv")
        self.branches = pd.read_csv(p / "branches.csv")
        self.employees = pd.read_csv(p / "employees.csv")
        self.accounts = pd.read_csv(p / "accounts.csv")
        self.transactions = pd.read_csv(p / "transactions.csv", parse_dates=["timestamp"])
        self.loans = pd.read_csv(p / "loans.csv", parse_dates=["approval_timestamp", "disbursement_timestamp"])
        self.guarantors = pd.read_csv(p / "guarantors.csv")
        self.loan_payments = pd.read_csv(p / "loan_payments.csv", parse_dates=["payment_timestamp"])

        self._precompute()

    def _precompute(self):
        # Per-member withdrawal/deposit stats, excluding nothing (rules that
        # need "typical, excluding this txn" recompute locally - this is the
        # cheap global baseline used by most rules).
        withdrawals = self.transactions[self.transactions.transaction_type == "Withdrawal"]
        self.member_withdrawal_stats = (
            withdrawals.groupby("member_id")["amount"]
            .agg(["mean", "std", "count"])
            .rename(columns={"mean": "avg_withdrawal", "std": "std_withdrawal", "count": "n_withdrawals"})
        )

        self.member_last_activity = (
            self.transactions.groupby("member_id")["timestamp"].max()
        )

        # Loan counts per approving employee, for peer-comparison
        self.loans_per_employee = self.loans.groupby("approved_by")["loan_id"].count()

        # Branch-normalized version: comparing an officer's volume only to
        # peers at the SAME branch. A company-wide comparison would confuse
        # "works at a busy branch" with "suspiciously high volume" - branch
        # size is a confound that has to be controlled for, not ignored.
        loans_with_branch = self.loans.merge(
            self.employees[["employee_id", "branch_id"]],
            left_on="approved_by", right_on="employee_id", how="left"
        )
        self.loans_per_employee_by_branch = (
            loans_with_branch.groupby(["branch_id", "approved_by"])["loan_id"]
            .count()
            .rename("loan_count")
            .reset_index()
        )

        # Guarantor frequency
        self.guarantor_counts = self.guarantors.groupby("guarantor_member_id")["loan_id"].count()

    def member_name(self, member_id: str) -> str:
        row = self.members[self.members.member_id == member_id]
        return row.iloc[0]["name"] if not row.empty else member_id

    def employee_name(self, employee_id: str) -> str:
        row = self.employees[self.employees.employee_id == employee_id]
        return row.iloc[0]["name"] if not row.empty else employee_id
