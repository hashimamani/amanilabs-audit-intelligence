from app.rules.base import Rule
from app.domain.models import Flag, Evidence, Severity


class DuplicateTransactionRule(Rule):
    rule_id = "R003"
    rule_name = "Duplicate Transaction"

    def evaluate(self, dataset) -> list[Flag]:
        flags = []
        txns = dataset.transactions.copy()
        txns = txns[txns.recipient.fillna("") != ""]
        txns["txn_date"] = txns["timestamp"].dt.date

        group_cols = ["member_id", "amount", "recipient", "txn_date"]
        for key, group in txns.groupby(group_cols):
            if len(group) < 2:
                continue
            member_id, amount, recipient, txn_date = key
            ids = group["transaction_id"].tolist()
            times = sorted(group["timestamp"].tolist())
            flags.append(Flag(
                rule_id=self.rule_id,
                rule_name=self.rule_name,
                severity=Severity.MEDIUM,
                entity_type="transaction",
                entity_id=",".join(ids),
                member_id=member_id,
                explanation=(
                    f"{dataset.member_name(member_id)} sent KSh {amount:,.0f} to {recipient} "
                    f"{len(group)} times on {txn_date}."
                ),
                evidence=[
                    Evidence("Amount", f"KSh {amount:,.0f}"),
                    Evidence("Recipient", recipient),
                    Evidence("Date", str(txn_date)),
                    Evidence("Occurrences", str(len(group))),
                    Evidence("Timestamps", "; ".join(str(t) for t in times)),
                ],
                suggested_steps=[
                    "Confirm with the member whether both/all transfers were intentional.",
                    "Check if this recipient receives duplicate payments from other members too.",
                    "Rule out a system/network retry error vs. deliberate repeated transfer.",
                ],
                triggered_at=max(times),
            ))
        return flags
