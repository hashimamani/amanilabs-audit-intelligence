"""
R009: graph/network analysis, not a trained model - see PROJECT_CONTEXT.md
for the full reasoning. Two independent signals, each emitting one Flag
per implicated member (not one flag per ring) so the existing subject-
grouping in cases/builder.py needs no changes at all.

Signal A (circular guarantee chains) deliberately uses cycle detection,
not connected-components/community detection. Baseline (non-injected)
loans already assign 2 random guarantors per loan from the whole member
pool - roughly 1,336 random edges across ~1,500 members - so "cluster
members connected via any guarantor edge" would collapse into one giant,
useless blob. A closed guarantee loop (A guarantees B, B guarantees C, C
guarantees A) is structurally rare in a mostly-random directed graph and
is also the most literal definition of a "ring": nobody in the loop has
independent financial backing, which defeats the point of a guarantor.
"""

import networkx as nx
import pandas as pd

from app.rules.base import Rule
from app.domain.models import Flag, Evidence, Severity


class FraudRingRule(Rule):
    rule_id = "R009"
    rule_name = "Fraud Ring / Collusion Network"

    def evaluate(self, dataset) -> list[Flag]:
        flags = []
        flags.extend(self._circular_guarantee_flags(dataset))
        flags.extend(self._shared_identity_flags(dataset))
        return flags

    def _circular_guarantee_flags(self, dataset) -> list[Flag]:
        min_len = self.config.get("min_cycle_length", 3)
        max_len = self.config.get("max_cycle_length", 6)
        window_days = self.config.get("synchronized_window_days", 14)

        edges = dataset.guarantors.merge(
            dataset.loans[["loan_id", "member_id", "approval_timestamp"]], on="loan_id"
        )

        graph = nx.DiGraph()
        edge_loans: dict[tuple[str, str], list] = {}
        for row in edges.itertuples(index=False):
            guarantor, borrower = row.guarantor_member_id, row.member_id
            if guarantor == borrower:
                continue
            graph.add_edge(guarantor, borrower)
            edge_loans.setdefault((guarantor, borrower), []).append(
                (row.loan_id, row.approval_timestamp)
            )

        flags: list[Flag] = []
        seen_rings: set[frozenset] = set()
        for cycle in nx.simple_cycles(graph, length_bound=max_len):
            if len(cycle) < min_len:
                continue
            key = frozenset(cycle)
            if key in seen_rings:
                continue
            seen_rings.add(key)

            cycle_loans = []
            for i in range(len(cycle)):
                pair = (cycle[i], cycle[(i + 1) % len(cycle)])
                cycle_loans.extend(edge_loans.get(pair, []))

            timestamps = [ts for _, ts in cycle_loans]
            span_days = (max(timestamps) - min(timestamps)).days if timestamps else None
            synchronized = span_days is not None and span_days <= window_days
            severity = Severity.CRITICAL if synchronized else Severity.HIGH
            latest_ts = max(timestamps) if timestamps else None
            loan_ids = sorted({lid for lid, _ in cycle_loans})
            chain_desc = " -> ".join(dataset.member_name(m) for m in cycle) + f" -> {dataset.member_name(cycle[0])}"

            for member in cycle:
                others = [m for m in cycle if m != member]
                evidence = [
                    Evidence("Ring size", str(len(cycle))),
                    Evidence("Guarantee chain", chain_desc),
                    Evidence(
                        "Fellow ring members",
                        ", ".join(f"{m} ({dataset.member_name(m)})" for m in others),
                    ),
                    Evidence("Loans involved", ", ".join(loan_ids)),
                ]
                if span_days is not None:
                    evidence.append(Evidence("Approval window", f"{span_days} day(s)"))

                explanation = (
                    f"{dataset.member_name(member)} is part of a {len(cycle)}-member circular guarantee "
                    f"chain ({chain_desc}), where each member guarantees the next member's loan - a closed "
                    f"loop with no independent financial backing."
                )
                if synchronized:
                    explanation += f" All {len(loan_ids)} loans were approved within {span_days} day(s) of each other."

                flags.append(Flag(
                    rule_id=self.rule_id,
                    rule_name=self.rule_name,
                    severity=severity,
                    entity_type="member",
                    entity_id=member,
                    member_id=member,
                    explanation=explanation,
                    evidence=evidence,
                    suggested_steps=[
                        "Verify each guarantor's independent income/assets - a circular chain means none of them has outside backing.",
                        "Check whether ring members share an address, employer, or family relationship.",
                        "Review whether the same loan officer(s) approved multiple loans in this chain.",
                    ],
                    triggered_at=latest_ts,
                ))
        return flags

    def _shared_identity_flags(self, dataset) -> list[Flag]:
        flags: list[Flag] = []
        join_dates = dataset.members.set_index("member_id")["join_date"]

        field_severity = {"national_id": Severity.CRITICAL, "phone": Severity.HIGH}
        for field, severity in field_severity.items():
            groups = dataset.members.groupby(field)["member_id"].apply(list)
            for value, member_ids in groups.items():
                if len(member_ids) < 2:
                    continue
                for member in member_ids:
                    others = [m for m in member_ids if m != member]
                    join_date = pd.to_datetime(join_dates.get(member))
                    flags.append(Flag(
                        rule_id=self.rule_id,
                        rule_name=self.rule_name,
                        severity=severity,
                        entity_type="member",
                        entity_id=member,
                        member_id=member,
                        explanation=(
                            f"{dataset.member_name(member)}'s {field.replace('_', ' ')} ({value}) is also "
                            f"registered to {len(others)} other member(s), which should not happen for a "
                            f"unique identifier."
                        ),
                        evidence=[
                            Evidence("Shared field", field.replace("_", " ")),
                            Evidence("Shared value", str(value)),
                            Evidence(
                                "Other members sharing this value",
                                ", ".join(f"{m} ({dataset.member_name(m)})" for m in others),
                            ),
                        ],
                        suggested_steps=[
                            "Confirm this member's identity documents in person.",
                            "Check whether these are duplicate registrations for the same individual, "
                            "or a coordinated multi-account scheme.",
                        ],
                        triggered_at=join_date if pd.notna(join_date) else None,
                    ))
        return flags
