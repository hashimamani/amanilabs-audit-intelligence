from app.rules.base import Rule
from app.domain.models import Flag, Evidence, Severity


class OffHoursApprovalRule(Rule):
    rule_id = "R007"
    rule_name = "Weekend / Off-Hours Approval"

    def evaluate(self, dataset) -> list[Flag]:
        business_start = self.config.get("business_start_hour", 8)
        business_end = self.config.get("business_end_hour", 17)

        flags = []
        for _, loan in dataset.loans.iterrows():
            ts = loan["approval_timestamp"]
            is_weekend = ts.weekday() >= 5
            is_offhours = not (business_start <= ts.hour < business_end)
            if is_weekend or is_offhours:
                reason = []
                if is_weekend:
                    reason.append("weekend")
                if is_offhours:
                    reason.append("outside business hours")
                flags.append(Flag(
                    rule_id=self.rule_id,
                    rule_name=self.rule_name,
                    severity=Severity.MEDIUM,
                    entity_type="loan",
                    entity_id=loan["loan_id"],
                    member_id=loan["member_id"],
                    explanation=(
                        f"Loan {loan['loan_id']} for {dataset.member_name(loan['member_id'])} was approved "
                        f"on {ts.strftime('%A, %Y-%m-%d %H:%M')} ({' and '.join(reason)})."
                    ),
                    evidence=[
                        Evidence("Approval timestamp", str(ts)),
                        Evidence("Day of week", ts.strftime("%A")),
                        Evidence("Approved by", loan["approved_by"]),
                        Evidence("Loan amount", f"KSh {loan['amount']:,.0f}"),
                    ],
                    suggested_steps=[
                        "Confirm the approving officer's system access log matches this timestamp.",
                        "Check for other approvals by the same officer outside business hours.",
                        "Verify the loan followed normal documentation/appraisal steps despite the timing.",
                    ],
                    triggered_at=ts,
                ))
        return flags
