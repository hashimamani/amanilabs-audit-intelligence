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
3. **Case generation** (done) — flags grouped into investigation cases
   (Case ID, risk score, triggered rules, evidence, timeline, related
   entities, status, assigned auditor, notes, outcome). AI summary field
   exists on the case row but is unpopulated — deferred per section 7.
4. **FastAPI backend** (done) — upload/analysis-run/case CRUD endpoints,
   SQLAlchemy ORM, SQLite locally / Postgres in Docker (see section 8).
5. **React frontend** (done) — upload flow, ranked case list, case detail
   view with evidence/timeline display.
6. **Docker Compose** (done) — backend + frontend + Postgres, see section 8.

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
injected scenario per the original harness's definition. **This was
individually audited** (`backend/noise_audit.py`, new) and the raw
75/226 figure turned out to be mostly a measurement artifact, not real
false positives:

- `validate_against_ground_truth.py` always adds a flag's `member_id` to
  the set being checked against `injected_ids`. But `ground_truth.json`
  only logs member ids as `record_ids` for scenarios 5/6
  (`employee_loan_approval_anomaly`, `repeated_guarantor` — see section 3's
  note on anchor entity ids). For every other scenario (1-4, 7, 8), a flag
  can correctly match its injected transaction/loan id and *still* show
  its member_id as "untraceable," because ground truth simply never logged
  that member id at all. That accounts for 69 of the 75 untraceable ids.
- Filtering to flags whose **entity_id** (the actual transaction/loan/
  employee/member the flag is about) matches no injected record at all —
  the real definition of "organic, non-injected flag" — leaves only **6
  flags out of 85** (7%):
  - 1 `same_day_disbursement_withdrawal` flag (loan L00237, 170% of the
    disbursement withdrawn within 24h — plausible, if unusually high;
    the >100% figure means other pre-existing balance was withdrawn
    alongside the loan proceeds in the same window, not a bug).
  - 3 `repeated_guarantor` flags, each at exactly the default threshold
    (5 loans guaranteed) — plausible natural variation given ~1,336
    guarantor links spread across 1,500 members.
  - 2 `employee_loan_approval_anomaly` flags (EMP0041 at 1.9x and EMP0042
    at 1.5x their next-highest branch peer), both via the small-branch
    ratio fallback (branches BR013/BR014 have <3 loan officers — 25 loan
    officers are spread across 15 branches company-wide, so most branches
    fall into this fallback path). Consistent with the known tradeoff
    documented in section 5 item 5 and section 6 item 2: ratio comparisons
    on 2-3 data points are noisier than z-scores on larger peer groups.
    Not a bug — a known, accepted cost of the hybrid approach that made
    detection of the actual injected officer (EMP0036) possible at all.

All 6 organic flags have a plausible, explainable reason to fire — none
look like generator artifacts or engine bugs. No thresholds were changed
as a result of this audit (per the project's rule: only change fraud
pattern behavior for real-world realism, never to tune a metric).

## 7. Explicit non-goals / deferred scope (don't build these yet)

- AI summarization layer (explicitly deferred until rule engine + case
  layer are solid — and when built, must ONLY explain evidence the engine
  already produced, never invent facts)
- RBAC / multi-role auth (single "auditor" role is enough for now)
- Multi-tenancy is decided and built (see section 12) — this bullet is now
  historical context for why RBAC/login is still explicitly deferred, not
  a statement that multi-tenancy itself is undecided.
- Live DB connectors (Postgres/SQL Server/MySQL) — CSV/Excel only for now
- Natural language search, historical case comparison, board reports
- Full Clean Architecture / DDD ceremony — repository pattern is worth
  doing now; formal bounded contexts/domain events are premature

## 8. Docker Compose + Postgres (done)

- `docker-compose.yml` at repo root runs three services: `postgres`
  (postgres:16-alpine), `backend` (FastAPI/uvicorn), `frontend` (Vite dev
  server, not a production build — see below). `docker compose up -d`
  brings up the full stack; backend on :8000, frontend on :5173, postgres
  on :5432.
- `app/core/db.py` now reads `DATABASE_URL` from the environment, falling
  back to the existing local SQLite file when unset. docker-compose sets
  it to a `postgresql+psycopg://` URL; local `python -m uvicorn` runs
  outside Docker are untouched and still use SQLite with zero setup. This
  was the actual "SQLite -> Postgres migration" decision: don't force
  Postgres on local dev, just make it swappable, since `db/models.py`
  already avoided any dialect-specific column types (plain JSON columns,
  no SQLite- or Postgres-only types) so no schema changes were needed for
  the swap to work.
- The frontend Dockerfile runs the same `npm run dev` Vite dev server as
  local development, not an nginx/production build — deliberate, since
  there's no deployment target yet (pre-pilot) and a second frontend code
  path (dev vs. prod build) isn't worth the complexity until one exists.
  `vite.config.ts`'s proxy target is now read from `VITE_API_PROXY_TARGET`
  (compose sets it to `http://backend:8000`; local dev is unaffected,
  defaults to `127.0.0.1:8000`).
- Verified end-to-end: built both images, brought the stack up, ran a real
  `/analysis/run` through the containerized backend, confirmed the rows
  landed in the Postgres container via `psql` (not just a 200 response),
  and loaded the case list + a case detail page in a real browser against
  the dockerized frontend/backend. Local (non-Docker) pytest suite (14/14)
  and the SQLite dev path were re-verified unaffected after the change.
- Uploaded datasets persist via a named volume
  (`backend_uploads` -> `/app/audit_intelligence/backend/data/uploads`)
  so they survive container restarts; Postgres data likewise persists via
  `postgres_data`.
- Multi-tenancy: still not decided, and still not needed — the Postgres
  schema that shipped is the same single-tenant schema from before, per
  section 7's deferred-scope list. Not addressed by this change.

## 9. UI polish: dashboard view (done)

- Added `frontend/src/pages/DashboardPage.tsx` as the new `/` landing
  route (moved the old case-list view from `/` to `/cases`, updated
  `Layout.tsx` nav to Dashboard / Cases / Upload & Analyze, and fixed the
  two other places that linked to the old `/` case-list — CaseDetailPage's
  "Back to cases" and UploadPage's post-run "View cases" button — so they
  now go to `/cases`).
- Shows the latest run's stats (flags raised, cases opened, Critical+High
  count, still-open count), a severity breakdown bar, a status breakdown,
  most-triggered rules, and the top 5 highest-risk cases — all computed
  client-side from the existing `/analysis/runs` and `/cases` endpoints,
  no new backend endpoint. Deliberately not building a dedicated stats
  endpoint yet: case volumes are in the dozens for the foreseeable
  pre-pilot future, and the existing `/cases` endpoint's max page size
  (200) covers that with room to spare - revisit if real pilot data pushes
  case counts into the thousands.
- `CaseListPage` now reads/writes its severity and status filters via
  `useSearchParams` (was local `useState`) so dashboard tiles can deep-link
  into a pre-filtered case list (e.g. clicking "Critical" goes to
  `/cases?severity=Critical`), and the filtered view is a real shareable
  URL.
- Verified in a real browser end-to-end: ran a fresh analysis from empty
  state, confirmed dashboard stats matched the run response exactly,
  clicked through a severity-filtered deep link into Cases, opened a case,
  and confirmed "Back to cases" returns to the unfiltered list. Backend
  pytest suite (14/14) re-verified unaffected (no backend changes in this
  piece).
- **`npm run build` fix (done)**: `src/api/client.ts`'s `ApiError` class
  used a TypeScript parameter-property constructor
  (`constructor(public status: number, message: string)`), which
  `erasableSyntaxOnly` in `tsconfig.app.json` rejects (that flag requires
  code that's valid after simply stripping types, and parameter properties
  emit actual field-assignment code, not just type annotations). Fixed by
  declaring `status: number` as a normal class field and assigning it in
  the constructor body instead. `npm run build` (`tsc -b && vite build`)
  now succeeds and `vite preview` serves the built `dist/` correctly.
  Pre-existing pytest suite (14/14, backend-only, unaffected by this
  frontend change) re-verified passing after the fix.

## 10. Immediate next steps (in order)

1. Further UI polish if there's appetite: bulk case status updates,
   evidence export.
2. Login/RBAC whenever there's a real need for it beyond one API key per
   tenant (still explicitly deferred, see section 7/12).

## 11. Working style established so far (please continue it)

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

## 12. Multi-tenancy (done)

Decided and built once a real second SACCO was lined up (previously
deferred per section 7 pending a concrete need).

- **Isolation model**: shared schema, `tenant_id` discriminator column —
  NOT schema-per-tenant or DB-per-tenant. Works identically on SQLite
  (local dev) and Postgres (Docker), no per-tenant migration tooling,
  matches this project's current scale (a handful of SACCOs, not
  thousands). `TenantORM` (`app/db/models.py`) has `id`/`slug`/`name`/
  `api_key`; `AnalysisRunORM` and `CaseORM` both carry `tenant_id`
  directly (not just via a join through `run`) so a route filtering cases
  can't leak another tenant's rows even if it forgets to also join back to
  `analysis_runs` — defense in depth.
- **Tenant identification**: an `X-Tenant-Key` header resolved to a tenant
  row by `get_current_tenant` (`app/core/tenancy.py`), a FastAPI dependency
  added to every route in `analysis.py`, `cases.py`, `upload.py`. No
  login/session/passwords — deliberately smaller than RBAC, which stays
  deferred (there is still no user-identity concept anywhere in the app,
  only tenant identity). Missing OR unrecognized keys both return a plain
  `401` (the header param is `Optional` in the FastAPI signature rather
  than `required=True` specifically so a missing header doesn't instead
  surface as FastAPI's default `422` validation error, which would read as
  "malformed request" rather than "not authenticated").
- **Default tenant**: `ensure_default_tenant()` auto-seeds a `"default"`
  tenant at startup (`main.py`) with a stable, non-secret, well-known key
  (`local-dev-default-key` — mirrors the existing `DEFAULT_DATASET_ID =
  "default"` pattern) so local dev and the bundled synthetic demo stay
  zero-friction. This key protects nothing sensitive — it only ever gates
  access to the bundled demo dataset in a dev environment.
- **Real tenant provisioning**: `python -m app.scripts.create_tenant
  --slug <slug> --name "<Display Name>"` (run from `backend/`) generates a
  random key via `secrets.token_urlsafe(32)` and prints it once — this is
  how the real second SACCO gets onboarded. Deliberately a CLI, not an
  admin UI: fine for a handful of pilot tenants by hand, revisit if/when
  self-service onboarding is actually needed.
- **Tenant display**: `GET /tenant/me` resolves the header to `{slug,
  name}` via the same `get_current_tenant` dependency every other route
  uses, so the frontend nav bar (`Layout.tsx`) can show which tenant
  you're looking at. Deliberately not a second `VITE_` env var alongside
  the key — deriving the name from the key server-side means it can't
  drift out of sync with what's actually authenticated (e.g. after
  rotating a key or renaming a tenant in the DB).
- **Upload isolation**: uploaded datasets are stored under
  `UPLOADS_DIR / tenant.slug / dataset_id` (was flat `UPLOADS_DIR /
  dataset_id`) so one tenant can't address another's uploaded dataset even
  by guessing its id. The bundled `"default"` demo dataset is shared
  across all tenants unchanged (it isn't tenant-owned data).
- **Frontend**: `src/api/client.ts` sends `X-Tenant-Key` from
  `VITE_TENANT_KEY` on every request (see `.env.example`). No
  tenant-switcher UI — out of scope until there's a login flow; in
  practice each tenant (including the real second SACCO) gets its own
  frontend env value/build pointed at the shared backend.
- **No migration tool introduced**: this project has no Alembic (or
  equivalent) and `Base.metadata.create_all` is additive-only
  (create-missing-table, not alter-existing-table). Since there was no
  real persisted data yet (both local SQLite and dockerized Postgres were
  dev-only), the schema change was rolled out by deleting the local
  `audit_intelligence.db` and `docker compose down -v`'ing the Postgres
  volume once. Revisit with a real migration tool once there's real tenant
  data that can't just be dropped and recreated.
- **Verified**: full pytest suite (19/19, including new
  `tests/test_tenancy.py` covering missing/unknown keys and cross-tenant
  isolation via FastAPI's `TestClient`); manually against a running
  backend — two tenants (`default` + a provisioned `demo-sacco`) each ran
  an analysis on the same bundled dataset, produced fully separate case
  sets, and cross-tenant case-by-id lookups returned `404`; the dashboard/
  case-list/case-detail UI flows re-verified working end-to-end in a real
  browser with the tenant header wired in; the full Docker Compose stack
  (frontend + backend + Postgres) rebuilt and re-verified against the new
  schema, including confirming the dockerized frontend's baked-in
  `VITE_TENANT_KEY` reaches the backend through the proxy.
