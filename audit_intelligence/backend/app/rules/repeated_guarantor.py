from app.rules.base import Rule
from app.domain.models import Flag, Evidence, Severity


class RepeatedGuarantorRule(Rule):
    rule_id = "R006"
    rule_name = "Repeated Guarantor"

    def evaluate(self, dataset) -> list[Flag]:
        threshold = self.config.get("max_loans_guaranteed", 5)

        flags = []
        for guarantor_id, count in dataset.guarantor_counts.items():
            if count >= threshold:
                loan_ids = dataset.guarantors[
                    dataset.guarantors.guarantor_member_id == guarantor_id
                ]["loan_id"].tolist()
                flags.append(Flag(
                    rule_id=self.rule_id,
                    rule_name=self.rule_name,
                    severity=Severity.HIGH if count >= threshold * 2 else Severity.MEDIUM,
                    entity_type="member",
                    entity_id=guarantor_id,
                    member_id=guarantor_id,
                    explanation=(
                        f"{dataset.member_name(guarantor_id)} appears as guarantor on {int(count)} loans, "
                        f"well above a typical member's 1-2."
                    ),
                    evidence=[
                        Evidence("Loans guaranteed", str(int(count))),
                        Evidence("Sample loan IDs", ", ".join(loan_ids[:10])),
                    ],
                    suggested_steps=[
                        "Check whether guaranteed borrowers share an employer, address, or referral source.",
                        "Verify the guarantor's own income/asset capacity to plausibly back this many loans.",
                        "Review repayment status of loans this guarantor backs - are they concentrated in defaults?",
                    ],
                    triggered_at=None,
                ))
        return flags
