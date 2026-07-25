from app.rules.base import Rule
from app.domain.models import Flag, Evidence, Severity


class DisbursementWithdrawalRule(Rule):
    rule_id = "R008"
    rule_name = "Same-Day Disbursement Withdrawal"

    def evaluate(self, dataset) -> list[Flag]:
        max_hours = self.config.get("max_hours_between", 24)
        min_fraction = self.config.get("min_fraction_withdrawn", 0.9)

        flags = []
        withdrawals = dataset.transactions[dataset.transactions.transaction_type == "Withdrawal"]

        for _, loan in dataset.loans.iterrows():
            member_withdrawals = withdrawals[withdrawals.member_id == loan["member_id"]]
            disb_time = loan["disbursement_timestamp"]
            window = member_withdrawals[
                (member_withdrawals.timestamp >= disb_time) &
                (member_withdrawals.timestamp <= disb_time + pd_timedelta(max_hours))
            ]
            if window.empty:
                continue
            total_withdrawn = window["amount"].sum()
            fraction = total_withdrawn / loan["amount"] if loan["amount"] else 0
            if fraction >= min_fraction:
                flags.append(Flag(
                    rule_id=self.rule_id,
                    rule_name=self.rule_name,
                    severity=Severity.MEDIUM,
                    entity_type="loan",
                    entity_id=loan["loan_id"],
                    member_id=loan["member_id"],
                    explanation=(
                        f"Loan {loan['loan_id']} of KSh {loan['amount']:,.0f} to "
                        f"{dataset.member_name(loan['member_id'])} was {fraction*100:.0f}% withdrawn "
                        f"within {max_hours} hours of disbursement."
                    ),
                    evidence=[
                        Evidence("Loan amount", f"KSh {loan['amount']:,.0f}"),
                        Evidence("Withdrawn within window", f"KSh {total_withdrawn:,.0f}"),
                        Evidence("Fraction withdrawn", f"{fraction*100:.0f}%"),
                        Evidence("Disbursement time", str(disb_time)),
                        Evidence("Withdrawal transaction IDs", ", ".join(window["transaction_id"].tolist())),
                    ],
                    suggested_steps=[
                        "Establish the purpose declared for the loan and whether it's consistent with immediate full withdrawal.",
                        "Check if this pattern repeats for other loans from the same approving officer.",
                        "Verify no informal arrangement exists to funnel disbursed funds back to a third party.",
                    ],
                    triggered_at=disb_time,
                ))
        return flags


def pd_timedelta(hours):
    import pandas as pd
    return pd.Timedelta(hours=hours)
