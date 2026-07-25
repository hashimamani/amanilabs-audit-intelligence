from app.rules.base import Rule
from app.domain.models import Flag, Evidence, Severity


class EmployeeLoanApprovalAnomalyRule(Rule):
    """
    Flags a loan officer who approves an unusual volume of loans relative
    to peers AT THE SAME BRANCH (branch size is a confound - a busy branch's
    top performer shouldn't look the same as a suspiciously high-volume
    officer at a small branch, so comparison must stay local).

    Statistical caveat this rule has to handle: many SACCO branches run with
    only 2-3 loan officers. A z-score computed from 2 data points is not
    reliable - the "average" and "standard deviation" of a 2-person sample
    barely mean anything. So:
      - Branches with >= MIN_PEERS_FOR_ZSCORE officers use a z-score test.
      - Smaller branches fall back to a simple ratio test (this officer vs.
        the next-highest peer) which is more robust with tiny samples,
        at the cost of being cruder. Both paths are disclosed in the
        evidence so an auditor knows which method flagged the case.
    """

    rule_id = "R005"
    rule_name = "Employee Loan Approval Anomaly"
    MIN_PEERS_FOR_ZSCORE = 3

    def evaluate(self, dataset) -> list[Flag]:
        std_multiplier = self.config.get("std_multiplier", 2.0)
        min_loans_flagged = self.config.get("min_loans", 15)
        ratio_threshold = self.config.get("small_branch_ratio_threshold", 1.4)

        flags = []
        by_branch = dataset.loans_per_employee_by_branch
        if by_branch.empty:
            return flags

        for branch_id, branch_group in by_branch.groupby("branch_id"):
            if len(branch_group) < 2:
                continue  # a single officer at a branch has no peer to compare against

            if len(branch_group) >= self.MIN_PEERS_FOR_ZSCORE:
                flags.extend(self._zscore_check(dataset, branch_id, branch_group,
                                                  std_multiplier, min_loans_flagged))
            else:
                flags.extend(self._ratio_check(dataset, branch_id, branch_group,
                                                ratio_threshold, min_loans_flagged))
        return flags

    def _zscore_check(self, dataset, branch_id, branch_group, std_multiplier, min_loans_flagged):
        flags = []
        mean = branch_group["loan_count"].mean()
        std = branch_group["loan_count"].std()
        std = std if std and std > 0 else 1

        for _, row in branch_group.iterrows():
            employee_id, count = row["approved_by"], row["loan_count"]
            z = (count - mean) / std
            if z >= std_multiplier and count >= min_loans_flagged:
                flags.append(self._build_flag(
                    dataset, employee_id, count, branch_id,
                    method="z-score",
                    detail=f"{z:.1f} standard deviations above the branch peer average of {mean:.1f}",
                    evidence_extra=[
                        Evidence("Branch peer average", f"{mean:.1f}"),
                        Evidence("Standard deviations above branch peers", f"{z:.1f}"),
                        Evidence("Detection method", "z-score (branch has 3+ loan officers)"),
                    ],
                ))
        return flags

    def _ratio_check(self, dataset, branch_id, branch_group, ratio_threshold, min_loans_flagged):
        flags = []
        sorted_group = branch_group.sort_values("loan_count", ascending=False).reset_index(drop=True)
        if len(sorted_group) < 2:
            return flags
        top = sorted_group.iloc[0]
        second = sorted_group.iloc[1]
        if second["loan_count"] <= 0:
            return flags
        ratio = top["loan_count"] / second["loan_count"]
        if ratio >= ratio_threshold and top["loan_count"] >= min_loans_flagged:
            flags.append(self._build_flag(
                dataset, top["approved_by"], top["loan_count"], branch_id,
                method="ratio",
                detail=f"{ratio:.1f}x the next-highest officer at the same branch ({second['loan_count']} loans)",
                evidence_extra=[
                    Evidence("Next-highest peer at branch", f"{second['approved_by']} ({second['loan_count']} loans)"),
                    Evidence("Ratio vs. next-highest peer", f"{ratio:.1f}x"),
                    Evidence("Detection method", "ratio comparison (branch has fewer than 3 loan officers, "
                                                  "too few for a reliable statistical average)"),
                ],
            ))
        return flags

    def _build_flag(self, dataset, employee_id, count, branch_id, method, detail, evidence_extra):
        emp_row = dataset.employees[dataset.employees.employee_id == employee_id]
        emp_name = emp_row.iloc[0]["name"] if not emp_row.empty else employee_id
        emp_loans = dataset.loans[dataset.loans.approved_by == employee_id]
        return Flag(
            rule_id=self.rule_id,
            rule_name=self.rule_name,
            severity=Severity.HIGH,
            entity_type="employee",
            entity_id=employee_id,
            member_id=None,
            explanation=(
                f"{emp_name} ({employee_id}) approved {int(count)} loans at branch {branch_id}, "
                f"{detail}."
            ),
            evidence=[
                Evidence("Loans approved", str(int(count))),
                Evidence("Branch", branch_id),
                *evidence_extra,
                Evidence("Sample of loan IDs", ", ".join(emp_loans["loan_id"].head(10).tolist())),
            ],
            suggested_steps=[
                "Review a sample of this officer's approved loans for common borrower traits or addresses.",
                "Check for relationships between borrowers and the approving officer (family, shared contacts).",
                "Compare approval-to-disbursement timing for this officer vs. branch average.",
            ],
            triggered_at=emp_loans["approval_timestamp"].max() if not emp_loans.empty else None,
        )
