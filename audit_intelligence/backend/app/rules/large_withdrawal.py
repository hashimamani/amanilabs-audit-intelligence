from app.rules.base import Rule
from app.domain.models import Flag, Evidence, Severity


class LargeWithdrawalRule(Rule):
    rule_id = "R001"
    rule_name = "Large Withdrawal"

    def evaluate(self, dataset) -> list[Flag]:
        multiplier = self.config.get("multiplier", 10)
        min_txns_for_baseline = self.config.get("min_txns_for_baseline", 3)

        flags = []
        withdrawals = dataset.transactions[dataset.transactions.transaction_type == "Withdrawal"]

        for member_id, group in withdrawals.groupby("member_id"):
            if len(group) < min_txns_for_baseline + 1:
                continue  # not enough history to call anything "abnormal"

            for idx, row in group.iterrows():
                # baseline excludes the transaction under review, so a single
                # large withdrawal can't inflate its own average and hide itself
                others = group.drop(idx)
                if len(others) < min_txns_for_baseline:
                    continue
                baseline = others["amount"].mean()
                if baseline <= 0:
                    continue
                ratio = row["amount"] / baseline
                if ratio >= multiplier:
                    severity = Severity.CRITICAL if ratio >= multiplier * 1.5 else Severity.HIGH
                    flags.append(Flag(
                        rule_id=self.rule_id,
                        rule_name=self.rule_name,
                        severity=severity,
                        entity_type="transaction",
                        entity_id=row["transaction_id"],
                        member_id=member_id,
                        explanation=(
                            f"{dataset.member_name(member_id)} withdrew KSh {row['amount']:,.0f}, "
                            f"which is {ratio:.1f}x their average withdrawal of KSh {baseline:,.0f} "
                            f"(based on {len(others)} prior withdrawals)."
                        ),
                        evidence=[
                            Evidence("Withdrawal amount", f"KSh {row['amount']:,.0f}"),
                            Evidence("Member's average withdrawal", f"KSh {baseline:,.0f}"),
                            Evidence("Multiple of average", f"{ratio:.1f}x"),
                            Evidence("Transaction date", str(row["timestamp"])),
                            Evidence("Channel", row.get("channel", "")),
                        ],
                        suggested_steps=[
                            "Confirm the withdrawal was authorized by the member directly (call member on file phone number).",
                            "Check whether the withdrawal correlates with a recent loan disbursement or account change.",
                            "Review teller/officer who processed the transaction for other unusual activity.",
                        ],
                        triggered_at=row["timestamp"],
                    ))
        return flags
