from app.rules.base import Rule
from app.domain.models import Flag, Evidence, Severity


class RapidTransfersRule(Rule):
    rule_id = "R004"
    rule_name = "Rapid Transfers"

    def evaluate(self, dataset) -> list[Flag]:
        window_minutes = self.config.get("window_minutes", 60)
        min_count = self.config.get("min_transfers_in_window", 5)

        flags = []
        transfers = dataset.transactions[dataset.transactions.transaction_type == "Transfer"]

        for member_id, group in transfers.groupby("member_id"):
            group = group.sort_values("timestamp").reset_index(drop=True)
            n = len(group)
            i = 0
            while i < n:
                j = i
                window_ids = [group.loc[i, "transaction_id"]]
                window_amounts = [group.loc[i, "amount"]]
                while j + 1 < n and (group.loc[j + 1, "timestamp"] - group.loc[i, "timestamp"]).total_seconds() <= window_minutes * 60:
                    j += 1
                    window_ids.append(group.loc[j, "transaction_id"])
                    window_amounts.append(group.loc[j, "amount"])

                count = j - i + 1
                if count >= min_count:
                    flags.append(Flag(
                        rule_id=self.rule_id,
                        rule_name=self.rule_name,
                        severity=Severity.HIGH,
                        entity_type="transaction",
                        entity_id=",".join(window_ids),
                        member_id=member_id,
                        explanation=(
                            f"{dataset.member_name(member_id)} made {count} outgoing transfers "
                            f"within {window_minutes} minutes, totalling KSh {sum(window_amounts):,.0f}."
                        ),
                        evidence=[
                            Evidence("Number of transfers", str(count)),
                            Evidence("Window", f"{window_minutes} minutes"),
                            Evidence("Total moved", f"KSh {sum(window_amounts):,.0f}"),
                            Evidence("Individual amounts", ", ".join(f"{a:,.0f}" for a in window_amounts)),
                            Evidence("Start time", str(group.loc[i, "timestamp"])),
                        ],
                        suggested_steps=[
                            "Check if individual amounts sit just under a reporting/approval threshold (possible structuring).",
                            "Identify recipients - are these related parties or a single beneficiary via multiple accounts?",
                            "Confirm the transfers were member-initiated (channel, device, location if available).",
                        ],
                        triggered_at=group.loc[i, "timestamp"],
                    ))
                    i = j + 1
                else:
                    i += 1
        return flags
