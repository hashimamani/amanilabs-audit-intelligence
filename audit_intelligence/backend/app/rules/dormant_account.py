import pandas as pd
from app.rules.base import Rule
from app.domain.models import Flag, Evidence, Severity


class DormantAccountRule(Rule):
    rule_id = "R002"
    rule_name = "Dormant Account Reactivation"

    def evaluate(self, dataset) -> list[Flag]:
        dormancy_days = self.config.get("dormancy_days", 180)
        min_withdrawal = self.config.get("min_withdrawal_amount", 5000)

        flags = []
        txns = dataset.transactions.sort_values("timestamp")
        join_dates = dataset.members.set_index("member_id")["join_date"]

        for member_id, group in txns.groupby("member_id"):
            group = group.sort_values("timestamp").reset_index(drop=True)

            # Edge case: member has exactly ONE transaction in the whole
            # dataset - i.e. no activity at all since joining, until this
            # single withdrawal. A gap-between-transactions calculation
            # can't see this (there's no second transaction to diff against),
            # but it's arguably the most suspicious version of this pattern:
            # an account nobody touched, suddenly emptied. Compare against
            # join date instead in that case.
            if len(group) == 1:
                row = group.loc[0]
                if row["transaction_type"] == "Withdrawal" and row["amount"] >= min_withdrawal:
                    join_date = pd.to_datetime(join_dates.get(member_id))
                    if pd.notna(join_date):
                        gap = (row["timestamp"] - join_date).days
                        if gap >= dormancy_days:
                            flags.append(Flag(
                                rule_id=self.rule_id,
                                rule_name=self.rule_name,
                                severity=Severity.HIGH,
                                entity_type="transaction",
                                entity_id=row["transaction_id"],
                                member_id=member_id,
                                explanation=(
                                    f"{dataset.member_name(member_id)}'s account had NO recorded activity "
                                    f"since joining {gap} days ago, then withdrew KSh {row['amount']:,.0f} "
                                    f"in this, their only transaction of the year."
                                ),
                                evidence=[
                                    Evidence("Days since joining with zero activity", str(gap)),
                                    Evidence("Join date", str(join_date.date())),
                                    Evidence("Withdrawal amount", f"KSh {row['amount']:,.0f}"),
                                    Evidence("Withdrawal date", str(row["timestamp"])),
                                ],
                                suggested_steps=[
                                    "Verify member identity for this transaction (ID check, phone verification).",
                                    "Confirm this is a genuine member-initiated withdrawal, not an account takeover.",
                                    "Check whether this account was ever expected to be active (e.g. dormant/inactive member).",
                                ],
                                triggered_at=row["timestamp"],
                            ))
                continue

            for i in range(1, len(group)):
                gap = (group.loc[i, "timestamp"] - group.loc[i - 1, "timestamp"]).days
                row = group.loc[i]
                if gap >= dormancy_days and row["transaction_type"] == "Withdrawal" and row["amount"] >= min_withdrawal:
                    flags.append(Flag(
                        rule_id=self.rule_id,
                        rule_name=self.rule_name,
                        severity=Severity.HIGH,
                        entity_type="transaction",
                        entity_id=row["transaction_id"],
                        member_id=member_id,
                        explanation=(
                            f"{dataset.member_name(member_id)}'s account was inactive for {gap} days, "
                            f"then withdrew KSh {row['amount']:,.0f} on reactivation."
                        ),
                        evidence=[
                            Evidence("Days dormant", str(gap)),
                            Evidence("Last activity before gap", str(group.loc[i - 1, "timestamp"])),
                            Evidence("Reactivation withdrawal", f"KSh {row['amount']:,.0f}"),
                            Evidence("Reactivation date", str(row["timestamp"])),
                        ],
                        suggested_steps=[
                            "Verify member identity for this transaction (ID check, phone verification).",
                            "Check who accessed or updated the account record immediately before this withdrawal.",
                            "Confirm this was not a staff-initiated transaction without member presence.",
                        ],
                        triggered_at=row["timestamp"],
                    ))
        return flags
