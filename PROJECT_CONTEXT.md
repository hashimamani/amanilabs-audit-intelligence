# Audit Intelligence (AmaniAnalytics) — Project Context & Handoff

This document exists so a fresh Claude Code session (or a human) can pick up
this project with full context, without re-deriving decisions already made.
Read this fully before writing new code.

---

## 1. Business context

- Founder: former Amazon SWE, building a startup for Kenyan SACCOs.
- Company: **AmaniAnalytics Ltd**, product branded **"Audit Intelligence"** —
  an AI Audit Intelligence Platform. Fraud detection is the entry wedge, not
  the whole story: positioning leaves room to expand into compliance, loan
  risk, operational analytics, and executive reporting later.
- **NOT a core banking system.** Sits on top of existing SACCO systems,
  analyzing exported data (CSV/Excel now, DB connectors later).
- Users: internal auditors, risk managers, compliance officers (primary);
  CEOs, branch managers, board audit committees (secondary).
- **Core philosophy (do not lose this):** the product does not claim to
  detect fraud with certainty. It answers *"what should an auditor
  investigate first, and why?"* Every flag must carry evidence and a plain
  explanation. No AI-invented evidence, ever — the AI layer (not yet built)
  only explains/summarizes what the rule engine already produced.

## 2. Go-to-market reality (why we're building in this order)

The founder cannot get real SACCO data without first proving value. So the
build order is deliberately:

1. **Synthetic data generator** (done) — believable Kenyan SACCO data with
   deliberately injected, logged fraud scenarios, used to prove the rule
   engine actually catches things before anyone sees real data.
2. **Rule engine** (done, validated) — 8 explainable rules producing
   Flag objects with severity/evidence/explanation/suggested steps.
3. **Case generation** (NOT built yet — next step) — group flags into
   investigation cases per the original spec (Case ID, risk score,
   triggered rules, evidence, timeline, related members/employees/
   transactions, AI summary placeholder, recommended actions, status).
4. **FastAPI backend** (not built) — wraps engine + case store, Postgres.
5. **React frontend** (not built) — upload, ranked case list, case detail.
6. **Docker Compose** (not built).

Do not skip ahead to AI summarization, RBAC, multi-tenancy, or the full
data-source connector list (SQL Server/MySQL/Postgres live connections) —
those are explicitly deferred until there's a paying pilot. The MVP goal is
a convincing demo on synthetic data, then a real pilot on one SACCO's
export, THEN the fuller spec.

## 3. What exists right now (in this bundle)

```
synthetic_sacco_data/          <- generator output (CSV + ground truth)
  generate_data.py              <- the generator script itself
  branches.csv, employees.csv, members.csv, accounts.csv,
  transactions.csv, loans.csv, guarantors.csv, loan_payments.csv
  ground_truth.json / .csv      <- answer key: which records are injected fraud

audit_intelligence/backend/
  app/domain/models.py           <- Flag, Evidence, Severity dataclasses
  app/rules/base.py              <- Rule ABC (config-driven, evaluate(dataset)->list[Flag])
  app/rules/dataset.py           <- SaccoDataset: loads CSVs, precomputes shared stats
  app/rules/config.py            <- DEFAULT_CONFIG per rule (tunable thresholds)
  app/rules/engine.py             <- RuleEngine: runs all 8 rules, sorts by severity
  app/rules/large_withdrawal.py       (R001)
  app/rules/dormant_account.py        (R002)
  app/rules/duplicate_transaction.py  (R003)
  app/rules/rapid_transfers.py        (R004)
  app/rules/employee_behaviour.py     (R005)
  app/rules/repeated_guarantor.py     (R006)
  app/rules/offhours_approval.py      (R007)
  app/rules/disbursement_withdrawal.py(R008)
  validate_against_ground_truth.py    <- harness: runs engine, checks recall vs. ground truth
```

No `requirements.txt` exists yet in this bundle — dependencies used so far:
`pandas`, `numpy`, `faker` (faker only used by the generator; the engine
itself only needs pandas/numpy). Add a proper `requirements.txt` and
`pyproject.toml` as one of the first things you do in Claude Code.

No tests directory has real tests yet (`backend/tests/` exists but is
empty) — `validate_against_ground_truth.py` has been the de facto test
harness so far. Converting its checks into real pytest tests is worth
doing early.

## 4. Synthetic data generator — design decisions

- 15 branches (Kenyan towns), 46 employees (loan officers/tellers/branch
  managers), 1,500 members, 1 year of transactions (~54k transactions),
  668 loans, 1,336 guarantor links, ~3,300 loan payments.
- Kenyan texture is hand-crafted (name lists, employer list, branch towns)
  — Faker's default locales don't have good Kenyan coverage, so don't
  swap this for generic Faker output.
- Each member has a "profile" (typical deposit/withdrawal size, activity
  level) so rules like "withdrawal > 10x average" are meaningful rather
  than arbitrary.
- **8 fraud scenarios are deliberately injected** into the baseline and
  logged to `ground_truth.json`/`.csv` (NOT shown to prospects — it's the
  founder's private answer key):
  1. `large_withdrawal` — 15 instances, withdrawal 11-22x personal average
  2. `dormant_account_raid` — 10 instances, 200+ day gap then big withdrawal
  3. `duplicate_transaction` — 10 instances, same amount/recipient/day x2
  4. `rapid_transfers` — 10 instances, 6-9 transfers within ~45 min
  5. `employee_loan_approval_anomaly` — 1 officer, +25 loans over 5 months
  6. `repeated_guarantor` — 1 member guarantees 18 unrelated loans
  7. `weekend_offhours_approval` — 15 loans approved outside business hours
  8. `same_day_disbursement_withdrawal` — 10 loans withdrawn in full within hours

- **Important generator design note**: all loan creation defaults to
  business-hours timestamps (`force_business_hours=True` in `create_loan`)
  specifically so ONLY scenario 7 produces off-hours flags. Earlier in
  development this wasn't the case and it polluted the off-hours rule with
  ~90 false positives from unrelated injected loans — fixed, but don't
  reintroduce random hour generation for loan approvals without the same
  guard.
- Ground truth for scenarios 5 and 6 (`employee_loan_approval_anomaly`,
  `repeated_guarantor`) includes the ANCHOR entity id (the officer's /
  guarantor's own member ID) in `record_ids`, not just the affected loan
  IDs — this was a fix needed so the validation harness could actually
  match rule output (rules flag the officer/guarantor entity, not the
  individual loans).

Regenerate with: `python3 generate_data.py` (seeded, so output is
deterministic given the same code — but any added/removed `random.*` call
anywhere earlier in the script will shift all subsequent random draws,
including member IDs assigned to fraud scenarios).

## 5. Rule engine — design decisions

- Each rule is a class implementing `Rule.evaluate(dataset) -> list[Flag]`,
  instantiated with a config dict (thresholds), so a SACCO's audit team
  could eventually tune sensitivity without a code deploy. Defaults live
  centrally in `rules/config.py` (`DEFAULT_CONFIG`), keyed by rule_id.
- `SaccoDataset` (rules/dataset.py) loads all CSVs once and precomputes
  shared derived stats (per-member withdrawal averages, last-activity
  timestamps, loans-per-employee both company-wide AND branch-normalized,
  guarantor frequency counts) so rules don't duplicate this work.
- Every `Flag` (domain/models.py) carries: rule_id, rule_name, severity
  (Low/Medium/High/Critical), entity_type, entity_id, member_id,
  plain-English explanation, structured evidence (label/value pairs, NOT
  free text — so a future AI layer or UI can render/quote them reliably),
  suggested_steps, triggered_at.
- `RuleEngine` (rules/engine.py) explicitly registers all 8 rule classes
  (no reflection/auto-discovery — deliberate, so it's always auditable
  exactly which rules ran, which matters for a product whose whole pitch
  is explainability) and sorts output by severity.

### The 8 rules and known behavior/limitations

1. **R001 Large Withdrawal** — flags withdrawal >= `multiplier`x (default
   10x) the member's own average, EXCLUDING the transaction under review
   from its own baseline (so one huge withdrawal can't inflate its own
   average and hide itself). Requires >= `min_txns_for_baseline` (default 3)
   OTHER withdrawals to compute a baseline — members with too little
   history are skipped rather than flagged on a meaningless average. This
   is a deliberate tradeoff: 2 of 49 injected scenarios are missed for
   exactly this reason (3 total withdrawals isn't enough history) and
   that's considered correct, defensible behavior, not a bug to "fix" by
   lowering the bar.

2. **R002 Dormant Account Reactivation** — flags a withdrawal following a
   gap >= `dormancy_days` (default 180) since the member's previous
   transaction. Has a special case for members with EXACTLY ONE
   transaction ever (no second transaction to diff against) — compares
   against `join_date` instead in that case. This was a real bug found and
   fixed during validation (see section 6).

3. **R003 Duplicate Transaction** — flags same member/amount/recipient/date
   occurring 2+ times.

4. **R004 Rapid Transfers** — flags >= `min_transfers_in_window` (default 5)
   outgoing transfers within `window_minutes` (default 60) for one member,
   using a sliding-window scan.

5. **R005 Employee Loan Approval Anomaly** — flags a loan officer approving
   an anomalous volume of loans. **Branch-normalized**, not company-wide —
   comparing officers company-wide would confuse "works at a busy branch"
   with "suspiciously high volume." Uses a HYBRID method:
   - Branches with >= 3 loan officers: z-score vs. branch peers
     (`std_multiplier`, default 2.0).
   - Branches with < 3 loan officers: falls back to a ratio test (officer
     vs. next-highest peer, default ratio 1.4x) because a z-score computed
     from only 2 data points is not statistically meaningful. This
     hybrid approach was added specifically because the pure z-score
     version missed the injected rogue officer at a 2-officer branch (see
     section 6) — don't revert to pure z-score without re-solving that.

6. **R006 Repeated Guarantor** — flags a member guaranteeing >=
   `max_loans_guaranteed` (default 5) loans.

7. **R007 Weekend/Off-Hours Approval** — flags loan approvals on weekends
   or outside `business_start_hour`-`business_end_hour` (default 8-17).

8. **R008 Same-Day Disbursement Withdrawal** — flags a loan where >=
   `min_fraction_withdrawn` (default 90%) of the disbursed amount is
   withdrawn within `max_hours_between` (default 24) hours.

## 6. Validation history — what was actually tested and fixed

A validation harness (`validate_against_ground_truth.py`) runs the engine
against the synthetic data and checks recall against `ground_truth.json`,
plus a rough noise estimate (flags not traceable to any injected scenario).
This iterative loop found and fixed THREE real issues — worth knowing so
they aren't reintroduced:

1. **Data generation bug**: off-hours rule fired 104 times instead of ~15,
   traced to injected loans (scenarios 5, 6, 8) not being constrained to
   business hours in the generator, even though they should have been
   "normal" on that dimension. Fixed by forcing business-hours timestamps
   by default in `create_loan()`, with scenario 7 explicitly opting out.

2. **Statistical confound in R005**: pure company-wide z-score missed the
   actual injected rogue officer (47 loans) while instead flagging a
   naturally high-volume officer at a busy branch (54 loans) who wasn't
   fraud. Root cause: branch size varies, so "average loans per officer"
   company-wide conflates workload with anomaly. Fixed with
   branch-normalized comparison. This ALSO initially missed the injected
   officer because their branch only had 2 loan officers (z-score from
   n=2 is unreliable) — fixed with the hybrid z-score/ratio approach
   described above.

3. **Dormancy edge case in R002**: a member with exactly one transaction
   ever (the injected withdrawal itself) couldn't be flagged because the
   original logic computed a gap BETWEEN transactions and there was no
   second transaction to diff against. Fixed by adding a branch that
   compares against `join_date` when a member has exactly one transaction.

**Current validated state: 47/49 (96%) of injected fraud scenario
instances detected.** The 2 remaining misses (both R001/Large Withdrawal)
are members with only 3 total withdrawals — considered correct
"insufficient history" behavior, not a defect.

Noise: ~75 flagged entity IDs out of ~226 total don't trace to any
injected scenario. Not yet individually audited — some is expected
(synthetic baseline data has natural statistical outliers even without
injected fraud, which is realistic), but this hasn't been broken down
rule-by-rule yet. **Worth doing before a real demo**: rerun the validation
harness, sample a few "noise" flags per rule, and sanity-check whether
they look like reasonable anomalies or generator artifacts.

## 7. Explicit non-goals / deferred scope (don't build these yet)

- AI summarization layer (explicitly deferred until rule engine + case
  layer are solid — and when built, must ONLY explain evidence the engine
  already produced, never invent facts)
- RBAC / multi-role auth (single "auditor" role is enough for now)
- Multi-tenancy (decide this explicitly before writing the DB schema/API —
  it wasn't decided as of this handoff)
- Live DB connectors (Postgres/SQL Server/MySQL) — CSV/Excel only for now
- Natural language search, historical case comparison, board reports
- Full Clean Architecture / DDD ceremony — repository pattern is worth
  doing now; formal bounded contexts/domain events are premature

## 8. Immediate next steps (in order)

1. Add `requirements.txt` / `pyproject.toml`, and convert
   `validate_against_ground_truth.py`'s checks into real pytest tests
   under `backend/tests/`.
2. **Case generation layer**: group Flags into investigation cases (Case
   ID, risk score derived from constituent flags, triggered rules,
   evidence, timeline, related members/employees/transactions, status,
   assigned auditor, notes, outcome — per original spec). Decide grouping
   logic (e.g. same member within a time window = one case?) explicitly
   and document the reasoning.
3. Decide multi-tenancy model before writing the DB schema.
4. FastAPI backend: endpoints for upload, run analysis, list/get cases,
   update case status/notes. SQLAlchemy + Alembic + Postgres.
5. React + TypeScript + Tailwind frontend: upload flow, ranked case list,
   case detail view with evidence display.
6. Docker Compose to run backend + frontend + Postgres together.

## 9. Working style established so far (please continue it)

- Build in small validated layers: implement -> test against something
  concrete (ground truth, real output) -> fix real failures -> report
  honestly, including what's still imperfect.
- Never silently patch a threshold to make a test pass without
  understanding WHY it failed first (see section 6 — every fix traced to
  a root cause before being applied).
- Keep the "explainability first, never invent evidence" principle intact
  in every new layer, especially once an AI/LLM summarization layer is
  built.
- Copy finished code out to wherever the user can actually see/download it
  as each layer completes, rather than batching it all until the end.
