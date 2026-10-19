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

9. **R009 Fraud Ring / Collusion Network** — graph/network analysis, not
   a trained model (see section 16 for the full reasoning and why that
   distinction matters for how this gets described to a SACCO). Two
   independent signals, each emitting one Flag per implicated member:
   (a) circular guarantee chains via directed-graph cycle detection
   (`networkx.simple_cycles`, length between `min_cycle_length`/
   `max_cycle_length`, default 3-6) - a closed loop where nobody has
   independent backing; severity bumps to Critical if the loop's loan
   approvals fall within `synchronized_window_days` (default 14) of each
   other; (b) shared `phone`/`national_id` across distinct member records
   (Critical/High respectively) - a plain groupby, no graph needed.

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

**Current validated state: 52/54 (96%) of injected fraud scenario
instances detected** (was 47/49 before R009 added 5 new instances, all 5
caught — see section 16). The 2 remaining misses (both R001/Large
Withdrawal) are members with only 3 total withdrawals — considered
correct "insufficient history" behavior, not a defect.

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
- RBAC / multi-role auth is decided and built (see section 15) — Auditor
  and Admin roles, individual login. Still explicitly NOT built: self-service
  signup, password reset/forgot-password email flow, a user changing their
  own password, or token revocation before expiry.
- Multi-tenancy is decided and built (see section 12).
- Live DB connectors (Postgres/SQL Server/MySQL) — CSV/Excel only for now
- Natural language search, historical case comparison, board reports
- Full Clean Architecture / DDD ceremony — repository pattern is worth
  doing now; formal bounded contexts/domain events are premature

## 8. Docker Compose + Postgres (done)

- `docker-compose.yml` at repo root runs three services: `postgres`
  (postgres:16-alpine), `backend` (FastAPI/uvicorn), `frontend` (nginx
  serving a real production build — see section 14, this was a dev server
  when Docker Compose first shipped, changed once a real pilot existed).
  `docker compose up -d` brings up the full stack; backend on :8000,
  frontend on :5173, postgres on :5432.
- `app/core/db.py` now reads `DATABASE_URL` from the environment, falling
  back to the existing local SQLite file when unset. docker-compose sets
  it to a `postgresql+psycopg://` URL; local `python -m uvicorn` runs
  outside Docker are untouched and still use SQLite with zero setup. This
  was the actual "SQLite -> Postgres migration" decision: don't force
  Postgres on local dev, just make it swappable, since `db/models.py`
  already avoided any dialect-specific column types (plain JSON columns,
  no SQLite- or Postgres-only types) so no schema changes were needed for
  the swap to work.
- The frontend Dockerfile originally ran the same `npm run dev` Vite dev
  server as local development rather than a production build — deliberate
  at the time, since there was no deployment target yet and a second
  frontend code path (dev vs. prod build) wasn't worth the complexity
  until one existed. Superseded once a real pilot existed — see section 14.
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

**Superseded 2026-10-19 by the serverless rebuild — see section 23 for the
current plan and what to do next.** The three items that used to live here
(domain + HTTPS on the EC2 box, provisioning the pilot tenant on it, the
Login/RBAC fast-follows) are all absorbed by that rebuild: CloudFront gives
HTTPS for free, Cognito gives password reset/revocation for free, and the
EC2 box is being decommissioned rather than improved.

**Superseded by section 23 (kept for the reasoning)**: the AWS
deployment (section 18) was created by hand via one-off CLI commands -
no infra-as-code, no CI/CD. Discussed and explicitly decided to leave
manual for now (SSH in, `git pull`/rsync, `docker compose up -d
--build`) rather than investing in tooling before there's a real need.
If/when deploys become frequent enough that manual redeploy is real
toil, or a second environment/account is actually needed: **Terraform**
(not CDK - smaller footprint for this handful of resources, no
build-toolchain requirement, and its plan/apply/destroy model directly
answers "replicate in another account") to codify the existing EC2/
security-group/Elastic-IP/IAM-user setup via `terraform import` (adopt
what's already running, don't recreate it), plus a simple GitHub Actions
workflow (push to `main` -> SSH in -> `git pull` + `docker compose up -d
--build,` no ECR pipeline/blue-green/staging-env) for code deploys. That
also means switching the server from its current `rsync` copy to a real
`git clone` (read-only deploy key) so it can `git pull` cleanly.

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

**Superseded by section 15**: the `X-Tenant-Key`/`api_key`/`VITE_TENANT_KEY`
mechanism described above was fully replaced by individual user login once
RBAC was built - `TenantORM.api_key` no longer exists, `app/core/tenancy.py`
and `GET /tenant/me` were deleted, and `VITE_TENANT_KEY` is gone from the
frontend/Docker config entirely. The isolation model itself (shared schema,
`tenant_id` columns, defense-in-depth double filtering) is UNCHANGED - only
the "how do we know which tenant is asking" mechanism moved from a shared
key to `user.tenant_id` via login. Left the history above intact rather
than rewriting it, since the reasoning for the isolation model itself is
still exactly why it works today.

## 13. Bulk case status updates + CSV evidence export (done)

Pilot-facing UI polish: auditors previously updated one case at a time and
had no way to hand data to someone outside the app.

- **Bulk status update**: `PATCH /cases/bulk-status` (`app/api/routes/
  cases.py`) takes `{case_ids, status}`, filtered by both `id IN (...)` AND
  `tenant_id == tenant.id` — a foreign case id slipped into the payload is
  silently excluded, not updated, same isolation guarantee as every other
  route. No status-value validation, matching the existing single-case
  `PATCH /cases/{id}` (frontend dropdown is the only constraint on valid
  values, consistent with before). Declared before `/{case_id}` in the
  route file - Starlette matches path shape before doing the `int` param
  conversion, so `bulk-status` would otherwise 422 by first matching
  `PATCH /{case_id}` and failing to parse `"bulk-status"` as an int.
  `CaseListPage.tsx` adds row/select-all checkboxes and a small bulk-action
  bar (status dropdown + Apply + Clear) that appears once >=1 row is
  selected; selection resets whenever the case list reloads so it can't
  reference stale rows after a filter change.
- **CSV export, not PDF/board report**: deliberately chosen over a
  formatted PDF - a board-report-style export would edge into "board
  reports," which section 7 explicitly defers. CSV is raw auditor data.
  Both exports are built client-side from data the pages already have
  loaded (no new backend endpoint) via a small hand-rolled `src/lib/csv.ts`
  (quote/escape + Blob-download helper, no new dependency):
  - List-level: "Export CSV" on `CaseListPage.tsx`, one row per
    currently-filtered case (summary fields only).
  - Per-case: "Download evidence (CSV)" on `CaseDetailPage.tsx`, one row
    per (flag, evidence-item) pair for that case, with case/flag context
    repeated per row; a flag with zero evidence items still emits one row
    so it isn't silently dropped from the export.
- **Verified**: new `tests/test_cases_bulk.py` (bulk update changes only
  the targeted cases; a case id from a second tenant included in the
  payload is excluded from `updated_count` and left untouched; empty
  `case_ids` is a no-op) - full suite 22/22. In the browser against a real
  backend: selected 3 cases, applied a bulk status change, confirmed the
  table reflected it after reload; verified actual CSV *content* (not just
  "no console error") for both exports by temporarily wrapping
  `URL.createObjectURL` via `javascript_tool` to capture the Blob text
  before the download fired - confirmed correct headers, correct rows, and
  correct comma/quote escaping (e.g. `"KSh 62,176"`) in both. `npm run
  build` re-verified passing (this project's known regression point - see
  the earlier `erasableSyntaxOnly` fix in section 9).

## 14. Production frontend build/deploy path (done)

The frontend's Docker Compose service ran Vite's dev server, not a
production build, even in Docker - a deliberate pre-pilot call (section 8)
made when there was no deployment target. With a real second SACCO pilot
now lined up, that needed to change: a dev server was never meant to serve
real users. No specific hosting provider/domain has been chosen yet, so
this was scoped to making the stack genuinely deployable via `docker
compose` on any VM, not to picking/configuring a specific host.

- `audit_intelligence/frontend/Dockerfile` is now a two-stage build:
  `node:22-slim` runs `npm run build`, then `nginx:1.27-alpine` serves the
  static `dist/` output. `VITE_TENANT_KEY` is baked into the JS bundle at
  build time (Vite statically replaces `import.meta.env.VITE_*`), so it's
  threaded through as a Docker build `ARG`, not a compose `environment:`
  entry - a runtime env var would be invisible to code that already ran
  during the image build.
- New `audit_intelligence/frontend/nginx.conf`: serves static files with
  `try_files $uri /index.html;` (SPA fallback, so a direct link or hard
  refresh on a client-side route like `/cases/5` doesn't 404), and
  reverse-proxies `/api/` to `http://backend:8000/` - the compose service
  name, stable regardless of external host/domain since it's resolved on
  the internal compose network. This also means production has no CORS
  exposure at all: the browser only ever talks to nginx's single origin.
  Backend CORS config is untouched - still needed for the local
  non-Docker `npm run dev` flow, where frontend :5173 and backend :8000
  are genuinely cross-origin.
- `docker-compose.yml`: frontend service gets `build.args.VITE_TENANT_KEY:
  ${VITE_TENANT_KEY:-local-dev-default-key}` (defaults to the well-known
  dev tenant key so `docker compose up` still works zero-friction; a real
  deployment sets `VITE_TENANT_KEY` via a root `.env`, now gitignored,
  before building). Port mapping stays `5173:80` - only the container's
  internal listening port moved from Vite's 5173 to nginx's 80.
  `VITE_API_PROXY_TARGET` is gone - nginx's `proxy_pass` replaces what the
  Vite dev-server proxy used to do.
- `.dockerignore` now excludes `audit_intelligence/frontend/.env`
  explicitly, so a machine-local dev env file (gitignored but not
  previously dockerignored) can never leak into a build context, removing
  any dependence on dotenv's "don't override existing process.env"
  precedence behavior working correctly.
- New root `.env.example` documents `VITE_TENANT_KEY` for `docker compose
  build` specifically - distinct from `audit_intelligence/frontend/
  .env.example`, which is for the local non-Docker `npm run dev` flow and
  is untouched by this change.
- **Verified**: `docker compose up -d --build` - `curl` confirmed nginx
  serving the root (200), a direct deep link to `/cases/1` returning
  `index.html` instead of 404 (SPA fallback), and `/api/tenant/me`
  proxying through to the backend correctly. In a real browser: the
  dashboard loaded real data end-to-end through nginx -> backend ->
  Postgres, the nav bar's tenant badge showed "Default / Demo" (proving
  the build-time-baked key reached the bundle), and navigating directly to
  a case detail URL worked without a 404. Local (non-Docker) `npm run dev`
  re-verified unaffected (Vite auto-selected :5174 since :5173 was held by
  the Docker container running simultaneously during this check - not a
  regression, just two things sharing a port at once).

**Superseded by section 15**: `VITE_TENANT_KEY` (and the build-`ARG`
threading described above) no longer exists - auth is per-user login now,
nothing is baked into the frontend build. `docker-compose.yml`'s backend
service instead gets a `JWT_SECRET` env var (same "insecure dev default,
override before real deploy" pattern). The nginx SPA-fallback and `/api/`
reverse-proxy design described here is unchanged and still exactly how
the frontend reaches the backend in Docker.

## 15. Login + RBAC: Auditor / Admin roles (done)

Every request previously authenticated via one shared `X-Tenant-Key` per
tenant - no individual identity, no permission differences. Explicitly
asked for by the user once the multi-tenancy and pilot-demo-actions work
was done. Replaces that shared-key model entirely, not layered on top of
it: logging in as a user determines both identity AND tenant (a user
belongs to exactly one tenant).

- **Roles**: `auditor` (everything the app already did - view/update
  cases, add notes, run analyses) and `admin` (everything an auditor can
  do, plus manage user accounts for their own tenant via `/users`).
- **`UserORM`** (`app/db/models.py`): `tenant_id`, `email` (unique),
  `password_hash`, `name`, `role`, `is_active`. `TenantORM.api_key` was
  removed - fully dead once login replaced it. Same no-Alembic,
  drop-and-recreate rollout this project has now used three times
  (multi-tenancy's `tenant_id` columns, this session, this change) -
  local `audit_intelligence.db` / the Postgres volume needed dropping
  once for the new schema.
- **Passwords**: `bcrypt` via `app/core/security.py` (`hash_password`/
  `verify_password`). **Tokens**: stateless JWT (`pyjwt`, HS256, 24h
  expiry, no refresh token - re-login on expiry is an accepted
  pilot-stage tradeoff) via the same module. The JWT payload carries only
  `{sub: user_id, exp}` - deliberately NOT role/tenant - so
  `get_current_user` (`app/core/auth.py`) does a fresh DB lookup every
  request. This matters because an admin can deactivate a user; baking
  role/tenant into the token would let a deactivated user's existing
  token keep working until it expired. `JWT_SECRET` is read from env,
  defaulting to a labeled insecure dev value - same pattern as
  `DATABASE_URL`/the CORS comment in `main.py`. Logout is client-side
  only (discard the token) - no server-side session to revoke.
- **`app/core/auth.py`** replaced `app/core/tenancy.py`: `get_current_user`
  (parses `Authorization: Bearer <token>`, 401 on anything wrong -
  missing, malformed, expired, or an inactive user, without
  distinguishing which, same non-leaking reasoning the old tenancy
  dependency used for its own header), `get_current_tenant` (thin wrapper
  - `user.tenant`) so every existing route in `analysis.py`/`cases.py`/
  `upload.py` needed only its import line changed, not its body, and
  `require_admin` (403 if `role != "admin"`). `ensure_default_tenant_and_admin`
  auto-seeds the `"default"` tenant AND a well-known dev admin
  (`admin@default.local` / `local-dev-admin`, non-secret, mirrors the old
  `DEFAULT_TENANT_DEV_KEY` reasoning exactly) at startup so local dev /
  `docker compose up` stay zero-friction.
- **Routes**: `POST /auth/login`, `GET /auth/me` (`app/api/routes/auth.py`);
  admin-only `GET/POST /users`, `PATCH /users/{id}` (`app/api/routes/users.py`,
  every route scoped to `tenant_id == admin.tenant_id`, 404 - not 403 - on
  a foreign user id, matching the case-lookup pattern). `GET /tenant/me`
  was deleted - `GET /auth/me` returns richer info (who's logged in, not
  just which tenant) and made it redundant.
- **`create_tenant.py`** now provisions a tenant's first admin, not a key:
  `--slug --name --admin-email --admin-name`, prints a generated password
  once. Every subsequent user for that tenant is created by that admin
  through `/users` in the app itself, not this script.
- **Frontend**: new `src/auth/AuthContext.tsx` (plain React context, no
  new state library - matches this app's existing plain-`useState` style)
  holds the token (in `localStorage` - accepted XSS tradeoff, same class
  as CORS being wide open pre-pilot, noted not solved) and user, hydrating
  via `GET /auth/me` on load. `client.ts` sends `Authorization: Bearer` from
  it instead of `X-Tenant-Key`. `App.tsx` gained a `RequireAuth` wrapper
  (redirects to `/login`, preserving the attempted path) and a `/login`
  route outside `Layout`. `Layout.tsx`'s badge now shows `{user.name} ·
  {tenant.name}` plus a working "Log out" action, and a "Users" nav link
  that only renders for `role === "admin"`. New `UsersPage.tsx` (admin-only)
  lists the tenant's users with inline role-change and activate/deactivate
  controls, plus a create-user form - this is the concrete thing that
  makes "Admin" mean something beyond a label.
- **Not built** (explicitly deferred, flag if wanted): self-service
  signup, forgot-password/email flow, a user changing their own password,
  token revocation before expiry.
- **Verified**: full pytest suite (29/29) including new `tests/test_auth.py`
  (login success/failure, `/auth/me` token validation, a deactivated
  user's existing token stops working immediately, admin-only routes
  reject an auditor with 403, user CRUD stays scoped to the admin's own
  tenant); `test_tenancy.py` renamed to `test_tenant_isolation.py` and
  `test_cases_bulk.py` rewritten to authenticate via login instead of the
  old header, same assertions. Manually: `curl` login with correct/wrong
  credentials, `/auth/me` with/without a token, provisioned a second
  tenant's admin and re-confirmed cross-tenant case isolation still holds
  under the new auth layer. Real browser: logged in as the seeded default
  admin, saw the nav badge and "Users" link, ran an analysis, opened/
  updated a case; created an auditor account via `UsersPage`; logged out
  (redirected to `/login`); logged in as that new auditor and confirmed
  no "Users" link and a clean "Admin role required" message (not a raw
  error dump) when hitting `/users` directly via the preserved
  post-login redirect. Full Docker Compose stack rebuilt and re-verified
  (login through nginx's `/api` proxy, default admin auto-seeded in a
  fresh Postgres volume). `npm run build` re-verified passing.

## 16. Fraud ring detection: R009 (done)

The user asked to pilot one more capability: ML-based fraud ring
detection. Clarified and locked in up front: **graph/network analysis**,
not a supervised classifier (no labeled real fraud-ring examples exist to
train on - inventing synthetic labels risks teaching a model the
generator's own quirks rather than real fraud signals) and not
behavioral/transaction clustering (doesn't use the relationship data -
guarantors, shared contact info - that's the actual signal for a
*coordinated group*, as opposed to one anomalous member).

**Framing honesty, worth knowing before pitching this to a SACCO
board**: this is graph theory / network analysis (cycle detection over a
guarantor digraph, plus shared-identity grouping), not a trained
statistical model. That's a legitimate, industry-standard part of the
fraud-detection ML toolkit, and it's a better fit for this product's
"every flag needs concrete evidence, never invented" principle than a
model outputting an opaque probability score - but "network analysis" or
"graph-based detection" is the more precise term than "ML" if someone
asks how it works under the hood.

- **Why cycle detection, not community detection**: baseline
  (non-injected) loans already assign 2 random guarantors per loan from
  the entire member pool - confirmed by reading `generate_data.py`,
  roughly 1,336 random guarantor edges across ~1,500 members. A naive
  "cluster members connected via any guarantor edge" (connected
  components / community detection) would almost certainly collapse into
  one giant blob from pure noise. A genuine circular guarantee chain (A
  guarantees B, B guarantees C, C guarantees A) is structurally rare in a
  mostly-random directed graph, and is also the most literal definition
  of a "ring" - a closed loop where nobody has independent financial
  backing, which is what makes a guarantor requirement meaningless.
  `networkx.simple_cycles(graph, length_bound=...)` bounds the search
  (unbounded cycle enumeration can blow up on a graph with incidental
  noise-cycles).
- **`app/rules/fraud_ring.py` (R009)**, config in `app/rules/config.py`
  (`min_cycle_length`/`max_cycle_length` default 3/6,
  `synchronized_window_days` default 14). Two independent signals:
  - **Circular guarantee chains**: directed graph (guarantor -> borrower)
    from `guarantors` joined to `loans`; cycles >= `min_cycle_length`
    are flagged. Severity Critical if the cycle's loan approvals fall
    within `synchronized_window_days` of each other (rapid + circular is
    very hard to explain innocently), else High.
  - **Shared identity**: members grouped by `phone` and separately by
    `national_id`; any group of 2+ is flagged. `national_id` duplication
    is Critical (should be unique by construction), shared `phone` is
    High.
  - **Both signals emit one `Flag` per implicated member**, not one flag
    per ring - the key design choice that needed **zero changes** to
    `Flag`/`Case` (`app/domain/models.py`) or `build_cases`
    (`app/cases/builder.py`): each flag has a normal single `member_id`,
    so existing subject-grouping just works, and each ring member gets
    their own case exactly like every other rule. The ring's other
    members appear as structured evidence ("Fellow ring members: ...")
    on each individual's flag.
  - `triggered_at`: circular-guarantee flags use the cycle's most recent
    loan-approval timestamp; shared-identity flags use the member's
    `join_date` - same fallback `app/rules/dormant_account.py` already
    established for "no better timestamp exists."
- **Real bug found and fixed while building this**: `SaccoDataset`
  (`app/rules/dataset.py`) read `members.csv` without an explicit dtype;
  since `phone`/`national_id` are all-digit strings, pandas inferred
  `int64` and silently dropped the leading zero every Kenyan phone number
  starts with (`0770548145` -> `770548145`). Invisible until R009 became
  the first rule to actually surface these fields in evidence. Fixed with
  `dtype={"phone": str, "national_id": str}` on the `read_csv` call.
- **New injected scenario 9** in `generate_data.py`, appended strictly
  after scenario 8 (every earlier scenario's `random.*` draws had to stay
  undisturbed, per the file's own documented warning) - verified via
  `git diff` that all 8 earlier scenarios' `ground_truth.json` entries
  are byte-identical and no unrelated CSV changed:
  - **9a circular_guarantee_ring**: 2 rings (sizes 4 and 5), built via
    `create_loan(..., guarantor_ids=[prev_member])` chained back to the
    start, approvals clustered within days (with a weekend-dodge so this
    doesn't also masquerade as an R007 off-hours flag).
  - **9b shared_identity_ring**: mutates `members_df` directly via
    `.loc` (it's already been snapshotted from the `members` list by
    this point in the script, so editing the list wouldn't reach the CSV
    output) - 2 shared-phone pairs, 1 shared-national-id pair.
  - `record_ids` logs **every** ring member's id, not one anchor -
    matches how R009 actually emits a flag per member and how the
    validation harness checks recall.
- **Validated, not assumed**: ran the rule against the dataset *before*
  adding scenario 9 - zero flags (confirms near-zero organic cycle/
  identity noise going in). After adding scenario 9: all 5 new instances
  caught (2/2 rings, 3/3 identity pairs), R009 fired exactly 15 times -
  matching the injected count precisely, with **zero additional organic
  noise** (the overall "flags not traceable to any injected scenario"
  count stayed at 75, identical to the pre-R009 baseline in section 6).
  Detection rate overall: 52/54 (same 2 known R001 misses as before, see
  section 6). `tests/test_rule_engine.py` updated with the real measured
  numbers (52/54 baseline, `R009` minimum 10 in
  `test_flag_counts_by_rule_are_in_expected_range` - actual is 15,
  loose lower bound like every other rule's floor). Full suite 29/29.
- **Frontend/API: zero changes needed**, confirmed by re-reading
  `CaseDetailPage.tsx`/`client.ts` - flags, evidence, and
  `triggered_rules` all render generically already. Verified in a real
  browser: a circular-guarantee case and a shared-identity case both
  render their evidence tables correctly (guarantee chain, fellow ring
  members, loans involved, approval window / shared field+value), with
  the phone-number fix confirmed showing `0770548145` not `770548145`.

## 17. "Quietly premium" UI styling pass (done)

Requested directly: better styling, a more premium feel. Locked in:
refined neutral palette + one signature accent color (not a bold/
colorful redesign - reads less "serious" for an audit/compliance
product), small icons okay (`lucide-react`).

- **Typography**: `@fontsource-variable/inter` (self-hosted, bundled at
  build time - no external CDN request at runtime, matches this
  project's existing self-containment habits), set as `--font-sans` in
  `index.css`'s `@theme` block so Tailwind v4's Preflight picks it up
  everywhere automatically.
- **Accent color**: Tailwind's built-in `indigo` palette, used
  consistently for primary buttons, active nav state, focus rings,
  checkboxes, links-on-hover. Slate stays the neutral base everywhere
  else. `SeverityBadge.tsx`'s red/orange/amber/slate mapping is
  untouched - that color carries real meaning for auditors and
  shouldn't be overridden by the brand accent.
- **Reusable classes** via Tailwind's `@layer components` in
  `index.css` (`.card`, `.btn-primary`, `.btn-secondary`,
  `.input-field`) replace the repeated `rounded-lg border
  border-slate-200 bg-white p-6` etc. strings that were copy-pasted
  across every page. Deliberately CSS-only, not a new React
  `Button`/`Card` component layer - this codebase has never used shared
  component abstractions for these, and introducing one now would be
  scope creep beyond "better styling."
- **Icons** (`lucide-react`): a `ShieldCheck` logo mark (`Layout.tsx`
  header, `LoginPage.tsx`), nav item icons, dashboard stat-tile icons,
  and icons on buttons that benefit from one (run analysis, upload,
  export/download, add user, back-to-cases).
- **`LoginPage.tsx`** (highest-visibility page) got a bit more:
  subtle `bg-gradient-to-b from-indigo-50 via-slate-50 to-slate-50`
  instead of flat slate, logo mark above the form.
- Fixed a real overflow bug found during verification: nav item labels
  (e.g. "Upload & Analyze") were wrapping mid-phrase once icons were
  added and took more horizontal space - added `whitespace-nowrap` to
  nav links and the header's logo/tenant-badge spans.
- **Verified**: `npm run build` passing (re-exercises the
  `erasableSyntaxOnly` regression point from section 9); full backend
  suite 29/29 unaffected (styling-only, no backend changes); real
  browser walkthrough of every page (Login, Dashboard, Cases list, Case
  detail, Upload, Users) logged in as the seeded default admin, plus a
  fresh auditor account to re-confirm the `role === "admin"` nav gating
  (section 15) still correctly hides "Users" and blocks the route after
  this pass touched `Layout.tsx`'s surrounding markup.

## 18. Hosted on AWS: single EC2 instance + Docker Compose (done)

Requested directly: host the pilot on AWS. Locked in: a scoped IAM user
(not root), no domain yet (plain HTTP on the instance's public IP), one
EC2 instance running the existing `docker-compose.yml` as-is rather than
ECS/Fargate/RDS — matches this project's consistently chosen "smallest
correct thing" pattern at this stage (1-2 pilot tenants, pre-revenue).

- **IAM**: root credentials were configured in the deploy environment's
  AWS CLI — created a dedicated IAM user (`audit-intelligence-deploy`,
  `AmazonEC2FullAccess`, region `us-east-1`) under a separate named CLI
  profile (`audit-intelligence`) instead. Root is not used for anything
  from here on. `AmazonEC2FullAccess` (not a hand-crafted minimal policy)
  is a deliberate scoping call — already a large reduction from root for
  a one-off solo-founder deploy; revisit with a tighter custom policy if
  this ever becomes a team/CI credential instead.
- **Network**: default VPC/subnet (no custom VPC needed at this scale).
  Security group `audit-intelligence-sg`: `22/tcp` restricted to the
  deploying machine's IP only (not `0.0.0.0/0` — avoids random SSH
  brute-force traffic; note this needs a one-line
  `authorize-security-group-ingress` update if that IP ever changes),
  `80/tcp` open to everyone (the actual pilot access point). Postgres
  (5432) and the backend's direct port (8000) are deliberately NOT
  opened in the security group even though `docker-compose.yml` still
  publishes both to the host for local-dev convenience — the security
  group is the real firewall (AWS SGs gate all inbound traffic at the
  network interface regardless of what's listening), so leaving those
  two closed means they're unreachable from the internet without
  touching the compose file (which would affect local dev too).
- **Instance**: Ubuntu 24.04 LTS (looked up via `ec2:DescribeImages`
  against Canonical's owner id, not a hand-picked AMI id that goes
  stale — the deploy user's `AmazonEC2FullAccess` doesn't include SSM
  parameter reads, which would've been the other way to resolve the
  latest AMI). `t3.small` (2 vCPU, 2GB RAM) + a 2GB swap file created via
  the launch user-data script specifically so `docker compose build`
  (the `vite build` step) doesn't OOM on a small instance — cheaper than
  `t3.medium` just for a one-time build spike. 20GB gp3 EBS (default 8GB
  is tight once OS + Docker images + Postgres data are on it). An
  Elastic IP is allocated and associated — required given the
  no-domain/use-the-IP-directly decision, otherwise the public IP would
  change on every stop/start and silently break the pilot's access URL.
- **Deploy mechanism**: `rsync` the repo to the instance (same
  excludes as `.gitignore`/`.dockerignore` already establish - `.git`,
  `node_modules`, `__pycache__`, `.venv`, `*.db`, upload data), a
  server-only root `.env` with a freshly generated `openssl rand -hex
  32` `JWT_SECRET` (never committed, never leaves the server - this is
  the one credential that actually needed rotating for a real deploy,
  since unlike the Postgres password it signs tokens that travel to real
  browsers over the wire), then the exact same `sudo docker compose up
  -d --build` already validated locally and in section 14.
- **Port mapping fix found during verification**: `docker-compose.yml`'s
  frontend service publishes to host port `5173` (matching the local-dev
  URL convention), not `80` - the security group was scoped to `80`
  matching the plan's "plain `http://<ip>/`" intent, so the first
  connectivity check failed. Fixed with a **server-only**
  `docker-compose.override.yml` (not committed, not synced back to the
  repo) adding `80:80` for the frontend service - `docker compose`
  auto-merges override files in the same directory, so `sudo docker
  compose up -d` on the server picks it up with no other change. Local
  dev and the repo's `docker-compose.yml` are untouched.
- **Critical post-deploy hardening**: `ensure_default_tenant_and_admin`
  (`app/core/auth.py`) seeds `admin@default.local` with a well-known dev
  password (`local-dev-admin`) by design for local-dev zero-friction
  (section 15) - that credential is now documented in this very file, so
  leaving it live on a real internet-facing box would mean anyone who's
  read this document could log in as an admin. Rotated it immediately
  after first boot to a freshly generated random password (via a one-off
  `docker compose exec backend python3 -c "..."` reusing the existing
  `hash_password`/`SessionLocal` code directly - no new code needed).
  Did NOT deactivate/delete that account - the bundled demo dataset flow
  through it is still useful for showing the product to prospects - only
  rotated what unlocks it. **The real pilot SACCO's own tenant was
  deliberately NOT provisioned during this deploy** (its name/admin
  details weren't decided yet) - see section 10 item 2 for the exact
  command to run on the server whenever it's ready.
- **Verified**: `curl` from outside the instance confirmed nginx serving
  the root (200), login working end-to-end through the real deployed
  stack (old `local-dev-admin` credential correctly rejected with 401
  after rotation, new credential accepted), a full analysis run against
  the live backend (101 flags / 91 cases, matching local numbers), case
  listing, and the SPA fallback on a direct `/cases/1` deep link all
  working against the public IP. `sudo docker compose ps` confirmed all
  three containers healthy/running. A full interactive browser
  walkthrough was intended but the browser tool had a transient outage
  during this session - the curl-level checks above cover the same
  request paths the UI would exercise (login, analysis run, case list,
  client-side routing), so this is a real gap only in "saw it rendered
  with my own eyes," not in "the deployed stack actually works."
- **Cost**: ~$17-20/month (t3.small ~$15, 20GB gp3 EBS ~$1.60, Elastic
  IP free while attached to a running instance).
- **Access**: `http://34.233.59.94/` (plain HTTP, no domain/TLS yet -
  see section 10 item 1). SSH: `ssh -i ~/.ssh/audit-intelligence-key.pem
  ubuntu@34.233.59.94`.

## 19. GenAI layer: case Q&A + constrained "ask for a chart" analytics (done)

The user asked how to integrate generative AI: probing questions on a
case's evidence, and generating custom graphs. This is the layer the
`Case.ai_summary` field has been a placeholder for since the very first
build - its docstring already stated the non-negotiable constraint: any
AI layer "must only ever summarize the evidence already attached to this
case, never invent facts." That rule governed every design choice below.
`ai_summary` itself remains unused (this feature is a separate `/ask`
endpoint, not a summary-generation feature) - still a placeholder for a
future summary feature.

Two features, two different risk profiles:

- **Case Q&A** (`POST /cases/{id}/ask`, added directly into
  `app/api/routes/cases.py` alongside the other case routes - keeps
  case-scoped routes together, same reasoning `bulk-status` already
  established) is low-risk: a case's evidence/flags/timeline is already
  small and structured, so the whole record is stuffed verbatim into the
  system prompt (`_case_to_grounding_text`) with strict instructions
  (`CASE_QA_SYSTEM_PROMPT`) to answer ONLY from that text, cite which
  flag/evidence item backs each claim, and say plainly when something
  isn't in the record rather than speculating. Simple context-stuffing,
  not RAG or tool-calling - safer and simpler for data this size. A
  single non-streaming `client.messages.create()` call, no adaptive
  thinking (simple grounded lookup, not complex reasoning), `max_tokens`
  1024. No Q&A history persistence - ephemeral, kept only in frontend
  React state, lost on reload; a clean fast-follow if wanted.
- **"Ask for a chart"** (`POST /analytics/query`, new
  `app/api/routes/analytics.py`, tenant-wide not case-scoped) is
  higher-risk: letting an LLM freely generate SQL or invent numbers would
  violate the no-invented-evidence rule and open a real injection
  surface. Instead Claude is given exactly ONE tool
  (`generate_chart(group_by, metric)`, forced via `tool_choice`) with a
  small enumerated `group_by` (`severity`/`status`/`subject_type`/
  `rule_id`/`created_date`) and `metric` (`case_count` only, v1). Claude's
  ONLY job is picking which pre-defined, server-computed aggregation
  answers the question - it never touches the database and never states
  a number itself. The backend re-validates the tool call's params
  against the literal enum again (defense in depth - never trust a
  model-supplied string blindly, even though `tool_choice` already
  constrains the schema), then computes real `{label, value}` pairs via
  plain Python `Counter` over a tenant+latest-run-scoped SQLAlchemy query
  (not SQL `GROUP BY` on the JSON columns - `db/models.py`'s own
  docstring already established dialect-specific SQL was deliberately
  avoided) and a backend-generated title, so there's zero chance of a
  wording/data mismatch. `rule_id` grouping counts once per rule a case
  triggered (a case can trigger multiple rules, so totals can exceed case
  count) - matches `DashboardPage.tsx`'s existing "Most-triggered rules"
  panel, which already aggregates this exact way client-side. No `filters`
  param in v1 (left undefined rather than inventing behavior - easy
  fast-follow once a real question shape needs it). Rendered with a new
  `src/components/BarChart.tsx` - deliberately not a new charting
  dependency (none existed before; every v1 dimension is categorical or
  day-bucketed, which a horizontal bar covers fine) - added as a new
  section on `DashboardPage.tsx`, no new route/page/nav item.

Both use `claude-opus-4-8` and the official `anthropic` Python SDK.
**New cost/ops surface, worth flagging directly**: this is the first
external, per-request-billed dependency in the app. No rate limiting or
per-tenant cost guard exists yet - acceptable at pre-pilot scale but
worth knowing before it hits real production traffic.

- **`app/core/ai.py`**: lazy `lru_cache`d Anthropic client singleton
  behind a FastAPI dependency (`get_anthropic_client`), plus `call_claude`
  which translates SDK exceptions (rate limit, connection, status errors)
  into clean HTTP errors instead of a raw 500. `ANTHROPIC_API_KEY` has
  no safe default (unlike `JWT_SECRET`/`DATABASE_URL`) - it's a real paid
  external API. `get_anthropic_client` checks the env var directly,
  before ever touching the SDK, so an unset key fails clean with a 503
  ("AI features are not configured") instead of crashing on import or
  breaking unrelated routes - verified both in the test suite (key
  unset throughout) and in a live browser walkthrough (both panels
  correctly show the clean 503 message with no key configured). Being a
  FastAPI dependency, tests override it with `app.dependency_overrides`
  exactly like `get_db` - no real key or network call in the test suite.
- **New dependency**: `anthropic` added to the root `requirements.txt`
  (unpinned, matching this file's existing convention).
  `docker-compose.yml`'s backend service gets `ANTHROPIC_API_KEY:
  ${ANTHROPIC_API_KEY}` (no default, unlike `JWT_SECRET`); documented in
  the root `.env.example`. Leave unset for local dev without AI - the
  affected routes degrade to a clean 503, nothing else breaks.
- **Verified**: full pytest suite (38/38, including new
  `tests/test_case_ai.py` and `tests/test_analytics_ai.py`, both mocking
  the Anthropic client via `dependency_overrides` - no real key or
  network call anywhere in the suite). The case Q&A tests assert every
  real evidence value from a case's `GET /cases/{id}` response appears
  verbatim in the system prompt actually passed to the (mocked) client -
  this is the test that enforces "no invented evidence" at the code
  level, not just in the prompt text. The analytics tests cross-check
  computed chart data against a hand-built `Counter` from real seeded
  cases (including a multi-rule case, proving `rule_id` grouping is
  genuinely per-rule, not accidentally per-case) and confirm an
  out-of-enum `group_by` from a (mocked) misbehaving model is rejected
  with 400, not a 500. `npm run build` passing. Confirmed both new routes
  appear correctly in the live OpenAPI schema. Real browser, local
  (non-Docker) dev, `ANTHROPIC_API_KEY` deliberately unset: logged in,
  submitted a question on both the Dashboard's "Ask for a chart" panel
  and a real case's "Ask about this case" panel, confirmed both correctly
  surface the clean "AI features are not configured" message (not a raw
  error dump) via the existing `ApiError`-based error handling - zero
  frontend changes were needed for that path to work correctly.
- **Live-verified against the deployed pilot** (section 18's EC2 instance,
  `34.233.59.94`): the user added a real `ANTHROPIC_API_KEY` to the
  server's `.env` directly over SSH (never handled by the assistant -
  API keys are never something to type into a file or command on a
  user's behalf, even if offered). Deployed via the same `rsync` +
  `sudo docker compose up -d --build` mechanism as section 18, after
  updating `audit-intelligence-sg`'s SSH ingress rule to the deploying
  machine's new IP (the old rule pointed at a different network - a
  one-line `authorize-security-group-ingress` fix, exactly as flagged
  as a possible future need in section 18). A disposable test tenant
  (`ai-smoke-test`, provisioned via the normal `create_tenant.py` script
  purely for this verification - self-generated throwaway credentials,
  not a real account) ran a real analysis (91 cases, matching the known
  baseline) and exercised both endpoints live:
  - **Case Q&A**: asked a real R009 (fraud-ring) case why it was
    flagged. Claude's answer correctly cited the actual ring size,
    guarantee chain, fellow ring members, loan IDs, and approval window
    from that case's real evidence - and, per the system prompt's rule
    5, explicitly declined to render a fraud verdict ("I'll leave the
    judgment on whether fraud occurred to you").
  - **Analytics**: three differently-phrased questions ("cases by
    severity", "which rules are firing the most", "break down open vs
    closed cases") each correctly mapped to a sensible `group_by`
    (`severity`, `rule_id`, `status` respectively - note the third
    phrasing has no literal "open vs closed" enum value, and Claude
    correctly picked the closest real dimension instead of failing) with
    real, internally-consistent computed numbers (severity: 26 + 33 +
    32 = 91, matching the run's real case count).
  - 503-when-unset path was already verified pre-deploy (see above); this
    pass covers the live, key-configured path the earlier one couldn't.
- **Explicit non-goals for this pass** (fast-follows, not forgotten): Q&A
  history persistence, a real charting library (pie/line charts), a
  `filters` param on the chart tool, per-tenant rate limiting or a cost
  guard on either endpoint. The `ai-smoke-test` tenant was left in place
  on the live DB (no `delete_tenant` script exists, and hand-writing a
  DELETE against production wasn't worth the risk for a harmless,
  fully-isolated extra tenant row) - safe to ignore or remove later.

**Superseded by section 21**: the enum-based `generate_chart` tool
described above (`GROUP_BY_VALUES`, `filter_rule_id`, and everything
built on top of them, including section 20's `chart_type`/`CHART_TYPE`
dict) was fully replaced by a code-execution-based design once real
usage showed the enum kept needing a hand-added parameter for every new
question shape. Case Q&A is UNCHANGED and still exactly as described
above - only analytics moved to the new mechanism.

## 20. AI board report generator + multi-chart-type analytics (done)

Direct follow-up to section 19: the user wanted to explore genuinely
different AI capabilities rather than just "more of the same," and asked
to start with the one most likely to move a real conversation - an
AI-drafted board report, since the founder personally presents to SACCO
boards. Separately, the chart panel was upgraded from a single hand-rolled
bar chart to real bar/line chart variety.

- **`POST /reports/generate`** (new `app/api/routes/reports.py`,
  tenant-wide like `/analytics`, not case-scoped): batches multiple
  cases' evidence through the exact same grounding discipline as case
  Q&A - `case_to_grounding_text` (moved from `routes/cases.py` to
  `core/ai.py` so both routes share it, one function, no duplication) is
  called per case and concatenated with clear `=== Case: ... ===`
  boundaries into one system prompt. Same non-negotiables as case Q&A:
  never state a fact not verbatim in the records, cite which flag/
  evidence backs each claim, and explicitly never render a fraud
  verdict - that stays with the audit team and board.
  - **Case selection**: explicit `case_ids` (reuses `CaseListPage.tsx`'s
    existing multi-select checkboxes from the bulk-status feature) are
    tenant-filtered and hard-capped at `MAX_REPORT_CASES = 50` (400 if
    exceeded, never silently truncated). With no selection, defaults to
    the latest run's Critical+High cases by risk score, capped at
    `DEFAULT_REPORT_CASE_LIMIT = 20` - a board doesn't want all 91 cases
    narrated. An empty result returns a plain message without ever
    calling Claude.
  - **Output is plain text only in this pass** - on-screen (new
    `<section>` on `CaseListPage.tsx`, `whitespace-pre-wrap`, matching
    the case Q&A answer style) plus a "Download as text" button (new
    `downloadText` in `src/lib/csv.ts`, generalized from the existing
    `downloadCsv` Blob-download pattern). No Word/PDF generation - a
    well-scoped fast-follow if wanted (a `docx` skill is available for
    that later).
  - **Real bug found via live testing, fixed**: the first live report
    (20 real Critical+High cases against the deployed pilot) hit the
    initial `max_tokens=4096` cap and was cut off mid-sentence. Raised to
    8192 (still well under the ~16k threshold where non-streaming risks
    an SDK timeout) and re-verified live: a full, complete 20-case report
    ending in a proper closing statement, no truncation.
- **Multi-chart-type analytics** (`app/api/routes/analytics.py`):
  - `chart_type` (`"bar"` or `"line"`) is derived server-side from
    `group_by` via a fixed dict, **never chosen by Claude** - keeps the
    "model only picks which real thing, never decides presentation"
    rule intact from section 19. `created_date` is the only `"line"`
    dimension; everything else stays `"bar"`.
  - **Real scoping bug found and fixed while building this**: every
    `group_by` dimension, including `created_date`, was scoped to the
    latest analysis run only. Since one run creates all its cases in a
    single batch, a "cases by day" chart on that scope would show one
    spike on one day, not a trend - the bug wasn't visible until line
    charts made it matter. Fixed by branching the row-fetch:
    `created_date` now spans the tenant's whole case history across all
    runs; every other dimension keeps the latest-run-only scope, which
    is correct for a snapshot breakdown. New test
    (`test_analytics_created_date_spans_multiple_runs`) seeds two
    separate runs and asserts the total spans both - the direct
    regression test for this.
  - Frontend: `recharts` added as a new dependency (`npm install
    recharts`) - the first charting library in this project. Loaded the
    `dataviz` skill before writing any chart code; since every chart here
    is single-series, the relevant guidance was: reuse the app's
    *existing* severity colors (`SeverityBadge.tsx`'s red/orange/amber/
    slate) for the severity breakdown specifically, rather than a
    generic categorical palette, since severity already carries real
    meaning for auditors; a single indigo accent for every other
    dimension; thin marks, tooltips, and recessive gridlines everywhere.
    `BarChart.tsx` was migrated from its original hand-rolled `<span>`
    bars to `recharts` (same external prop shape, so `DashboardPage.tsx`
    didn't need to change how it's called), and a new `LineChart.tsx`
    added - both now read as one visual system instead of one hand-rolled
    style sitting next to a library-rendered one.
  - **Bundle-size cost, noted not fixed**: `recharts` grew the frontend
    JS bundle from ~281KB to ~671KB (gzipped ~199KB). Acceptable for an
    internal tool used by a handful of staff; code-splitting is a fast-
    follow if it ever becomes a real problem, not done here since it
    wasn't asked for and the current size isn't causing any actual issue.
  - **Superseded by section 21**: the `chart_type`-via-fixed-dict
    mechanism and the hardcoded `created_date`-spans-all-runs branch
    described in the two bullets above are gone, replaced by a
    code-execution design where the model's own generated code decides
    both. `BarChart.tsx`/`LineChart.tsx` and the `recharts` dependency
    are UNCHANGED and still exactly as described - only how `chart_type`
    gets decided moved.
- **Verified**: full pytest suite (50/50, including new
  `tests/test_reports_ai.py` and the extended `test_analytics_ai.py` -
  all still mock the Anthropic client, zero real network calls or API
  key needed to run the suite). `npm run build` clean. Deployed to the
  live pilot (`rsync` + `sudo docker compose up -d --build`, same
  mechanism as section 19) and live-tested against real Claude responses
  using the existing `ai-smoke-test` throwaway tenant: a full untruncated
  20-case board report (evidence-cited per case, correctly refusing to
  render a fraud verdict) and both chart types returning `chart_type`-
  correct, numerically accurate results for varied natural-language
  phrasings.

**Follow-up bug, found immediately after the timeout fix shipped**: with
the 504 gone, a real 502 "AI did not return a valid chart" surfaced -
distinct issue, same day. `_extract_chart` only tried the whole stdout,
or the single last line, as a JSON candidate. The system prompt
explicitly permits Claude's code to print other things before its FINAL
print (e.g. an exploratory `df.head()`), and doesn't forbid pretty-
printing that final JSON across multiple lines - neither case was
handled by either candidate. Added a third candidate: everything from
the last stdout line that opens a JSON object (`{`) onward. Also added
`_debug_summary`/logging on any future extraction failure (stop_reason
plus every content block, truncated) - there had been zero diagnostic
trail for the original 502, which is why it took a code read rather than
a log read to find. New tests
(`test_analytics_extracts_chart_after_exploratory_prints`,
`test_analytics_extracts_pretty_printed_multiline_json`) cover both
shapes directly - full suite 51/51. Deployed and re-verified live (5
varied questions, all real 200s with correct computed numbers) - the
original failure was never reproduced on demand (genuinely intermittent
by nature), so this is the most plausible root cause found on a close
read, not a confirmed-via-logs one; the new logging is what closes that
gap for any future occurrence. UI rendering (bar chart with severity
colors, line chart
  with a smooth trend, the report panel's text formatting and download
  button) was visually confirmed via the local dev server with the
  actual deployed component code and a mocked API response, since the
  browser tool hit the same transient outage against the live IP
  documented in section 18 - a real gap only in "saw the live site
  rendered with my own eyes," not in "the deployed code and data are
  correct," which was independently confirmed via curl against the real
  endpoints.

**Real user-reported bug, found immediately after deploy, fixed same
day**: asking "trend of R002 cases" rendered an all-cases date breakdown,
silently ignoring "R002." Root cause: `generate_chart` had no way to
scope by a specific rule while grouping by something else like
`created_date` - exactly the `filters` gap called out as deferred above.
Fixed by adding an optional `filter_rule_id` parameter to the tool
(re-validated server-side against the 9 real rule IDs, same defense-in-
depth as `group_by`/`metric`); the backend filters the case set before
aggregating, and the returned `title` reflects the applied filter (e.g.
"Cases by creation date — R002 only") so it's never ambiguous what's
actually shown. Covered by two new tests
(`test_analytics_filter_rule_id_scopes_the_chart`,
`test_analytics_rejects_out_of_enum_filter_rule_id`) - full suite 47/47.
Live-reverified on the deployed pilot with the exact reported question:
correctly returns `filter_rule_id: R002`, title "Cases by creation
date — R002 only", and a count of 10 - matching R002's real, documented
count in this dataset (section 4's `dormant_account_raid` scenario).
A follow-up unfiltered question ("cases by severity") was re-checked
immediately after to confirm the fix didn't regress the unfiltered path.

## 21. Analytics rebuilt on real code execution, replacing the enum tool (done)

The `filter_rule_id` patch in section 19 fixed one specific complaint but
revealed the real problem: the enum-based `generate_chart` tool needed a
hand-added parameter for every new question shape a user might ask, and
would keep needing one forever. The user's direct feedback: "I don't see
any intelligence with the way it is" - they expected something closer to
uploading data to Claude and asking it to analyze it, the way Claude.ai's
own data-analysis mode works, not picking from a fixed menu.

**The constraint that motivated the enum in the first place was never
"Claude shouldn't be flexible" - it was "Claude must never state a number
it hasn't verifiably computed."** That constraint is fully preserved by a
different mechanism: give Claude a code-execution sandbox with the real
case data, and require its own printed code output - not its prose - to
be the chart. A number produced by pandas code that actually ran against
real rows isn't invented, it's computed, exactly as rigorously as the old
enum's `Counter`-based aggregation was, just without a fixed vocabulary.

- **`app/api/routes/analytics.py`** rewritten from scratch. Claude gets
  the tenant's case data as an embedded CSV (no Files API - at this
  project's scale the whole thing is a few KB, well within context) via
  the `code_execution_20260120` server-side tool, with `thinking:
  {"type": "adaptive"}` on (this task is genuinely harder than enum
  selection) and `max_tokens=8192` (same headroom lesson learned from
  the report generator's truncation bug in section 20). The system
  prompt requires Claude's code to print exactly one JSON object as its
  final output (`{title, chart_type, data}`); the backend extracts and
  validates that JSON's *structure* (never trust model-decided shape
  blindly, even though the *values* inside it are now trustworthy by
  construction) before returning it. Handles the documented `pause_turn`
  resubmission case (server-side tool iteration cap) with one retry.
- **Privacy-minimized by design**: the CSV sent to the sandbox has only
  `run_id`, `severity`, `status`, `subject_type`, `triggered_rules`,
  `risk_score`, `created_at` - no `case_ref`, `subject_id`, or
  `subject_name`. Charts are about aggregates, never about identifying a
  specific member; case Q&A and the report generator already own "tell
  me about this specific case" and stay unchanged. This also closes off
  the prompt-injection surface almost entirely - every column sent is
  either a backend-generated enum value or a number, never user-authored
  free text (unlike case Q&A's evidence values, which is a pre-existing,
  separate consideration).
- **What used to be hardcoded Python branching is now a prompt
  instruction Claude's own code implements**: "for a snapshot question,
  use only the most recent run_id; for a trend/history question, use all
  runs." This generalizes to questions the old hardcoded branch (which
  only handled `created_date` specially) never anticipated - confirmed
  live: asking for a plain average correctly used only the latest run
  (a snapshot question) with no code change needed to teach it that.
- **`app/api/schemas.py`**: `ChartDatapointOut.value` is now `float` (not
  `int`) - metrics aren't just `case_count` anymore, since Claude's code
  can compute anything (averages confirmed working live). `AnalyticsQueryOut`
  drops `group_by`/`metric`, which no longer mean anything.
- **Tests shift focus**, and this is worth understanding explicitly: the
  old tests asserted specific aggregation outputs, which was meaningful
  when this codebase's own `Counter` did the counting. Now the
  aggregation lives in Claude-generated code, which can't be usefully
  unit-tested without a real call - exactly mirroring how case Q&A/report
  quality were never unit-tested either, only grounding/structure was.
  `tests/test_analytics_ai.py` was rewritten to verify what's still under
  this codebase's control: the CSV actually handed to the model (spans
  all runs, excludes PII - `test_analytics_csv_excludes_pii_and_spans_all_runs`),
  response structure validation on four different malformed-output shapes,
  the empty-tenant short-circuit not calling Claude, and the `pause_turn`
  resubmission path. Full suite 48/48.
- **Verified live** against the deployed pilot with real Claude calls,
  including two questions the old enum system could never have answered
  at all, both independently cross-checked against a manual calculation
  from `GET /cases`:
  - "What is the average risk score for R001 cases?" → returned 90.59.
    Manually confirmed: 22 R001 cases in the latest run, mean risk score
    90.59 - exact match, including the (correct, unprompted-in-code)
    decision to scope to the latest run only since this is a snapshot
    question, not a trend.
  - "Break down R009 cases by severity" → returned Critical: 11, High: 4.
    Manually confirmed via `Counter` over the same data - exact match.
  - `npm run build` clean; both live tests took roughly 30-45 seconds
    each (thinking + code execution round-trip) - noticeably slower than
    the old single forced tool call, an expected and accepted tradeoff
    for the flexibility gained.
- **New cost/latency profile, not yet acted on**: code execution
  container time is billed past a monthly free-hours allowance (~$0.05/hr
  after 1,550 free hours/org/month) - negligible at this project's usage
  scale but a new cost dimension beyond message tokens. Still no
  per-tenant rate limiting or cost guard on any AI endpoint (same
  standing gap noted since section 19).

**Latency follow-up, same day**: the ~30-45s round trip drew a real user
complaint ("i dont get it") - it read as broken, not slow. Two rounds of
tuning, both measured live rather than assumed:

1. First attempt: dropped adaptive thinking and set `effort: "medium"`
   on Opus, hypothesizing "thinking" was the dominant cost. Measured
   live post-deploy: 46.9s and 41.2s - essentially no change from
   before. Hypothesis was wrong; reported that honestly rather than
   claiming a fix that didn't hold up. Also fixed the frontend's loading
   state either way, since a silent 40-second wait reads as broken
   regardless of the actual latency number ("Analyzing..." + a caption
   explaining what's happening, replacing the old bare "Asking...").
2. Second attempt: switched analytics specifically to `claude-sonnet-5`
   (case Q&A and the report generator stay on Opus - only this route is
   synchronously latency-sensitive with a live user waiting).
   `call_claude()` (`app/core/ai.py`) now takes an optional `model=`
   override instead of a hardcoded constant, defaulting to the app-wide
   Opus model. **Real trap avoided**: Sonnet 5 defaults to *adaptive
   thinking* when `thinking` is omitted - the opposite of Opus 4.8,
   which defaults to none - so simply switching models without also
   explicitly setting `thinking: {"type": "disabled"}` would have
   silently reintroduced the exact overhead attempt 1 was trying to
   remove. Covered by a new test asserting both the model and the
   explicit `thinking: disabled` on every analytics call.
   - **Measured live, three samples**: 32.9s, 37.3s, 31.0s (avg ~34s) vs.
     the Opus baseline's 46.9s/41.2s (avg ~44s) - a real, consistent
     ~25% improvement, not a dramatic one. Confirms the dominant cost is
     the sandboxed code-execution container itself (spin-up + real
     Python execution), which is largely fixed regardless of model or
     prompt tuning - full suite 49/49, `npm run build` clean.
   - One of the three live runs also demonstrated the flexibility this
     redesign was built for: asked "trend of R002 cases" against a
     tenant with only one analysis run on record, and it correctly
     returned an honest empty chart titled "R002 Trend Not Available -
     Only Single Analysis Run Present," instead of faking a one-point
     line - reasoning the old enum-based system had no way to do.
- **Where this leaves latency**: ~30-40s is now the realistic floor for
  this feature at current settings, and further speed needs either
  accepting that floor and improving the *waiting experience* (e.g.
  streaming visible progress instead of a static spinner - discussed,
  not built) or a more invasive architecture change (e.g. skipping code
  execution for simple, recognizable questions). Neither pursued yet -
  flagging as the next real lever if 30-40s still isn't acceptable.

## 22. Fixed: nginx 504 "Gateway Timeout" on the AI endpoints (done)

Real bug, reported directly by the user hitting it live: both "ask for a
chart" and board report generation were returning "Gateway Timeout"
instead of their real result.

- **Root cause**: `audit_intelligence/frontend/nginx.conf`'s `/api/`
  location had no explicit `proxy_read_timeout`, so nginx's default (60s)
  applied. Section 21 documented `/analytics/query` averaging ~30-40s and
  occasionally needing a `pause_turn` retry that roughly doubles the wait;
  `/reports/generate` runs Opus over up to 20 batched cases at
  `max_tokens=8192`. Both routinely exceed 60s. nginx was killing the
  proxied connection and returning its own 504 while the FastAPI backend
  was still genuinely working - not a backend bug, not an Anthropic-side
  issue.
- **Fix**: added `proxy_connect_timeout`/`proxy_send_timeout`/
  `proxy_read_timeout 180s;` to the `/api/` location - generous margin
  over the documented worst case, no effect on every other route (those
  return in milliseconds regardless of this setting).
- **Verified by reproducing the actual failure, not just reasoning about
  it**: built the real `frontend` image from this repo's Dockerfile, ran
  it against a stub backend container (named `backend` on a shared
  docker network, so nginx's `proxy_pass http://backend:8000/` resolves
  exactly like it does against the real service) that sleeps 90s before
  responding. Pre-fix nginx.conf: confirmed a real `504 Gateway Time-out`
  at exactly 60.0s. Post-fix nginx.conf, same stub, same 90s delay:
  confirmed a real `200` at 90.0s. This isolates the fix to nginx
  configuration alone, independent of what the backend/Anthropic call
  actually does.
- Confirmed this can only be nginx (not a Vite dev-server issue, and not
  a client-side fetch timeout): `frontend/vite.config.ts`'s local dev
  proxy sets no timeout of its own, and `frontend/src/api/client.ts`'s
  `request()` uses a plain `fetch()` with no `AbortController`/timeout.
  "Gateway Timeout" is literally nginx's 504 status text, surfaced to the
  user via `ApiError`'s fallback to `res.statusText` when nginx's default
  HTML error page fails to parse as JSON.
- **Deployed and live-verified same day** on the EC2 pilot (section 18,
  `34.233.59.94`) - that box is where the user was actually hitting this.
  `rsync` + `sudo docker compose up -d --build`, same mechanism as every
  prior deploy. One extra step needed first: SSH connect timed out
  because the security group's SSH ingress rule (section 18) was still
  scoped to a previous deploying machine's IP - updated via
  `aws ec2 authorize/revoke-security-group-ingress` under the
  `audit-intelligence` CLI profile, exactly the one-line fix section 18
  already anticipated for this situation. Verified against real Claude
  calls using a fresh disposable tenant (`nginx-fix-verify`, same
  throwaway-tenant pattern as section 19's `ai-smoke-test`, left in place
  under the same reasoning - no `delete_tenant` script exists and it's a
  harmless isolated row): a real analysis run (91 cases, matching the
  known baseline), then both previously-failing endpoints against real
  Claude - `/analytics/query` returned a real severity breakdown (26 + 33
  + 32 = 91) in 50.3s, `/reports/generate` returned a real 20-case,
  ~11.7KB report in 49.0s. Both are real 200s at durations that were
  landing right at or past the old 60s ceiling - exactly the previously-
  failing range, now succeeding.

## 23. Serverless rebuild on AWS — decisions and phase plan (code complete; nothing deployed until the bootstrap)

Requested directly on 2026-10-19: "this project did not have proper
infrastructure done in a proper production method ... should run
serverless in AWS ... improvements across all facets including the UI."
A full review of the repo and the live UI preceded this; the gaps it
found, in priority order:

- The pilot's Postgres runs *inside a container on one t3.small with no
  backups* - one disk failure loses every case. Plain HTTP on a bare IP
  carries logins and member PII (names, national IDs, phones) unencrypted,
  which is a Data Protection Act problem for any SACCO sale, not just
  hygiene. No IaC, no CI, `rsync` deploys, a `docker-compose.override.yml`
  that exists only on the server, no searchable logs or alarms.
- Long-running work (`/analysis/run`, the AI endpoints at 30-90s) runs
  synchronously inside HTTP requests - the nginx 504 in section 22 was a
  symptom of that design, and it is incompatible with any API gateway.
  Uploads go to local disk; the demo dataset is found by walking the repo
  path. Hand-rolled JWT/bcrypt with a well-known seeded admin in code.
  No schema migrations ("drop the DB" was the strategy). Only filenames
  are validated on upload. No audit trail of who changed a case. No rate
  limit or budget on paid Anthropic calls. Unpinned deps; Python 3.14
  locally vs 3.12 in Docker.
- UI: a 3-page CRUD app with a top nav. No run-over-run deltas, rules
  shown as bare codes, no search/sort/pagination (hard-capped at 200),
  every Critical case shows `100.0` so on-screen ranking is meaningless,
  bare inputs with no save feedback, no activity history, no triage flow,
  no upload validation/progress, `Loading...` text, no toasts, no error
  boundary, zero frontend tests.

### Decisions (locked with the user, do not re-litigate)

1. **DynamoDB** single table, not Aurora Serverless v2. Zero idle cost,
   no VPC/NAT, no connection-pool pain from Lambda; case rows are already
   JSON blobs read as a unit. Cost: the ~4 data-layer files are rewritten
   and ad-hoc SQL is gone (DynamoDB being schemaless also removes the
   "no migration tool" problem).
2. **Region `eu-west-1`**, matching Tender Tracker and the billing
   platform so one operator pattern covers every AmaniLabs product. (The
   EC2 box is in us-east-1; `af-south-1` was offered for the "data stays
   in Africa" pitch and declined for now.)
3. **Cognito** replaces the hand-rolled auth: custom login page kept,
   groups for `admin`/`auditor`, `custom:tenant_id`, API Gateway JWT
   authorizer. Password reset, forced change, MFA and revocation - the
   section 15 fast-follows - come for free.
4. **Decommission the EC2 pilot and remove every manually created
   resource** (instance, security group, Elastic IP, key pair, the
   `audit-intelligence-deploy` IAM user) at the end of the rebuild. No
   data migration: only demo/smoke tenants ever existed on it (the real
   SACCO tenant was never provisioned, per section 18).
5. **Deploys run only from GitHub Actions via OIDC, mirroring
   `billing-platform` exactly** - a plain CloudFormation deploy identity
   that can assume the CDK bootstrap roles and nothing else, a script that
   builds the *immutable* OIDC subject from the numeric GitHub ids, a
   `workflow_dispatch` deploy guarded by typing the stage name, and CI
   that synths with no AWS credentials. Nothing is ever deployed from the
   developer machine (its CLI is the account root user, which cannot
   assume a role anyway); the one-time `cdk bootstrap` +
   `scripts/deploy-identity.sh` is run by the user with a non-root
   administrative identity.

### Target architecture

| Layer | Target |
|---|---|
| Frontend | S3 + CloudFront (OAC, HTTPS, `/api/*` behaviour to the API, CSP/HSTS headers) |
| API | API Gateway HTTP API + one Lambda (FastAPI via Mangum, Powertools logging/tracing); route code barely changes, only the DB/auth/storage layers do |
| Long work | SQS → worker Lambda (15 min, 2 GB) + a job status record; the UI polls with real progress. Kills the 504 class permanently |
| Auth | Cognito user pool, JWT authorizer at the gateway |
| Data | DynamoDB single table, PITR + deletion protection in prod, KMS |
| Files | S3 (SSE-KMS, presigned browser upload - Lambda's 6 MB limit makes this mandatory, lifecycle expiry on raw uploads for data minimisation) |
| Secrets | SSM SecureString |
| Ops | CloudWatch dashboard, alarms (5xx, DLQ depth, worker errors), log retention, X-Ray |
| IaC/CI | CDK (TypeScript, cdk-nag) + GitHub Actions |

Rule engine, case builder and the AI grounding layer are untouched - they
are pure pandas/dicts. Idle cost well under $5/month vs ~$20 now.

### Phases (each ends green and shippable)

- **Phase 0 - foundations (done, see below).**
- **Phase 1 - backend decoupled from the box, no AWS yet**: DynamoDB data
  layer (tested with moto), S3-or-local dataset store, async job model
  (jobs record + worker entrypoint runnable locally *and* as a Lambda
  handler), Cognito-JWKS auth dependency with a local mock issuer,
  Powertools structured logging, upload column-schema validation, case
  activity log. The seeded default admin leaves with the old auth. Gate:
  full suite green against moto; `/analysis/run` returns a job id and
  completes via the worker locally.
- **Phase 2 - infra**: CDK stacks Data, Auth, Api (+SQS/worker/DLQ), Web,
  Ops; cdk-nag clean; assertion tests; the user runs the bootstrap; CI
  deploys dev. Gate: login → run → cases → AI chart on the dev CloudFront
  URL.
- **Phase 3 - frontend**: Cognito login (current look kept), app shell
  with sidebar + run selector, TanStack Table case list (search/sort/
  paginate), job progress component, case triage flow (next/prev, inline
  status with toast + activity timeline), dashboard deltas vs previous
  run, rule names everywhere + a plain-English Rule Catalogue page,
  skeletons/toasts/error boundary, vitest + one Playwright smoke. Gate:
  walked in a real browser on dev.
- **Phase 4 - hardening + cutover**: per-tenant AI budget/rate limit, S3
  lifecycle, tenant provisioning as an admin command, `delete_tenant`
  (right to erasure), prod stacks behind the typed confirmation, custom
  domain when one exists, runbook, EC2 + manual resources removed.

### Phase 0 - foundations (done 2026-10-19)

- **Python**: `pyproject.toml` + `uv.lock` are the source of truth;
  `requirements.txt` is now *generated* (`uv export --frozen --no-dev
  --no-hashes --no-emit-project`) for the Docker image and, later, the
  Lambda bundle - CI fails if the two drift. `.python-version` pins
  **3.13**, the same interpreter the Lambda runtime and the Dockerfile
  (`python:3.13-slim`, was 3.12) use. The local venv had been on 3.14,
  whose Homebrew build was broken (`pyexpat` dlopen failure made even
  `pip freeze` crash); it was moved aside to `.venv-old-py314` (ignored)
  and recreated. Versions were pinned to what the suite already ran on
  (pandas 3.0.x, FastAPI 0.14x, anthropic 0.12x `<1` - the 1.x major is a
  Phase 1 upgrade, not a silent one). `faker` moved to the dev group: only
  `generate_data.py` imports it, the engine never does.
- **ruff** (`E`, `F`; `E501` ignored rather than reformat 250 lines;
  `E402` allowed in tests, which set up the app before importing it).
  Two real findings fixed: `rules/base.py` annotated `evaluate()` with a
  `"SaccoDataset"` string that was never imported (harmless at runtime
  because it was a string, wrong as documentation - now a real import),
  and an unused `prof = member_profiles[member_id]` in
  `generate_data.py`'s `create_loan` (removed; it made no `random.*`
  call, so every seeded draw - and therefore `ground_truth.json` - is
  byte-identical, which the 52/54 test re-confirmed).
- **infra/** (CDK, TypeScript, ESM, `tsx`): `lib/config.ts` validates
  `infra/config/<stage>.json` with zod at synth (region, optional pinned
  account - required for prod - alarm email, log retention); `prod.json`
  was gitignored with `prod.json.example` committed (reversed in Phase 4:
  both stage configs are committed now). `lib/app.ts`
  (`defineStacks`) is the single place stacks are declared so `bin/app.ts`
  and the tests synthesise the same thing - empty until Phase 2. cdk-nag's
  AwsSolutions pack is wired through CDK's validation framework in both
  the app and `test/nag.test.ts`, whose first test plants a non-compliant
  bucket and asserts `AwsSolutions-S1`/`S10` are caught - a silently
  disabled pack is otherwise indistinguishable from a clean app. 15
  tests, `npm run synth` clean ("This app contains no stacks").
- **Deploy identity** (`infra/bootstrap/deploy-identity.yaml`,
  `scripts/deploy-identity.sh`, `docs/DEPLOYING.md`) copied from
  `billing-platform` with one deliberate simplification: a single deploy
  role, no separate publish-UI role, because the web bundle will be
  published by CDK's `BucketDeployment` inside the same deployment. The
  script refuses to run as root and prints the `gh` commands that create
  the GitHub environment and set `AWS_DEPLOY_ROLE_ARN`/`AWS_REGION` on it.
- **GitHub Actions**: `ci.yml` (backend: `uv sync --frozen`, ruff, pytest,
  requirements.txt-matches-lock; frontend: `npm ci`, oxlint, `npm run
  build`; infra: typecheck, vitest, `cdk synth` with no credentials) and
  `deploy.yml` (`workflow_dispatch` with stage + typed confirmation, OIDC,
  `sts get-caller-identity`, `cdk diff`, deploy only when the confirmation
  matches). A dry-run dispatch proves the whole identity chain before
  Phase 2 has anything to deploy. `.nvmrc` = 22, matching the frontend
  Dockerfile.
- **Verified**: `uv run pytest` 53/53 on Python 3.13 with the newly
  pinned stack (including SQLAlchemy 2.1.x and pandas 3.0.6 - no code
  change needed); `uv run ruff check .` clean; `docker build` of the
  backend image on `python:3.13-slim` succeeds and reports the same pinned
  versions inside the container; infra typecheck + 15 tests + synth clean.
  CI itself has not run yet - it fires on the first push of this work.

### Phase 1 - backend decoupled from the box (done 2026-10-19)

SQLAlchemy, Postgres and SQLite are gone. Nothing in the backend assumes a
local disk, a long-lived process or a password it checks itself. The rule
engine, case builder and the AI grounding prompts did not change.

- **`app/core/settings.py`** reads every environment-dependent value once.
  Three shapes: `local` (laptop / compose: DynamoDB Local, local auth,
  disk datasets, inline jobs), `test` (same, under moto) and dev/prod
  (the real table, Cognito, S3, SQS). `is_local` covers local and test.
- **`app/db/table.py` + `app/db/repository.py`**: one DynamoDB table,
  `PK=TENANT#<slug>` for every item so a route cannot read across tenants
  without building a different key on purpose; `SK` prefixes META / USER# /
  RUN#<run_no> / CASE#<case_ref> / ACTIVITY#<case_ref>#<ts> / JOB# /
  DATASET#. `GSI1` serves "cases of a run, highest risk first"
  (`RISK#<score*10>#<inverted seq>`, queried descending, projecting only
  the summary fields so a list never reads the flag/evidence blobs) and
  "user by email" for local login. Run numbers are a per-tenant atomic
  counter on the tenant item, so `case_ref = CASE-<run>-<seq>` stays
  readable and `run_id` stays an integer in the API. **Case ids in the API
  are now the `case_ref` string** (`/cases/CASE-0001-0003`), not a
  database integer. Floats are stored as `Decimal` and converted back on
  read (`_to_dynamo`/`_from_dynamo`), which the repository test pins.
- **Background jobs** (`app/jobs/`): `/analysis/run`, `/analytics/query`
  and `/reports/generate` all return **202 with a job record** (analysis
  also returns the run, which carries `status`/`job_id`); the client polls
  `GET /jobs/{id}` or `GET /analysis/runs/{id}`. `JOB_RUNNER=inline`
  executes in-process (local, tests); `sqs` sends `{tenant_slug, job_id}`
  to the queue and `app/worker_handler.py` (SQS Lambda, partial-batch
  responses) runs it. `execute_job` is idempotent on redelivery (finished
  jobs are skipped, `running` ones retried after a crash); a `JobFailed`
  carries a message safe to show, anything else becomes a generic error
  with the traceback in the log. Analysis runs now also store
  `severity_counts` and `rule_counts` at completion, and `latest_run`
  only ever returns a succeeded run - a failed run can never become "the
  latest" the dashboard reads. Case Q&A stays synchronous (seconds, not
  a minute). **This is what makes the nginx-504 class of bug impossible
  rather than tuned around.**
- **Auth** (`app/core/auth.py`): in dev/prod the bearer is the **Cognito
  ID token** (the only token that carries `custom:tenant`; same choice as
  Tender Tracker), verified against the pool's JWKS with
  `audience=client id`, `issuer=pool`, `token_use == "id"`; role is the
  `cognito:groups` entry that is `admin` or `auditor`. Local mode mints
  HS256 tokens with the identical claim names (`core/security.py`) so
  everything after `decode_token` is one code path. The user's mirror
  item in the table is read on every request: deactivation is immediate
  and a role change needs no new token. `POST /auth/login` only exists in
  local mode (404 otherwise). `test_auth_cognito.py` signs real RS256
  tokens with a generated key and swaps the JWKS client.
- **User directory** (`app/core/users.py`): Cognito mode calls
  AdminCreateUser (Cognito emails the temporary password - no password
  ever passes through this code), puts the user in the role group, and
  mirrors `{user_id = sub, email, name, role, is_active}` into the table
  (Cognito cannot list users by a custom attribute); role changes move
  groups, deactivation disables the user and signs them out globally.
  Local mode keeps the bcrypt hash on the item. `test_users_cognito.py`
  runs the Cognito path against moto's cognito-idp.
- **Datasets** (`app/core/datasets.py`, `/datasets`): uploads never pass
  through the API. `POST /datasets` returns one URL per required file - a
  presigned S3 PUT in dev/prod, or the API's own `PUT
  /datasets/{id}/files/{name}?tenant&expires&token` (HMAC) locally, so
  the browser code is identical - then `POST /datasets/{id}/finalize`
  reads each file's header (a 64 KB ranged GET on S3) and refuses the
  dataset with a per-file list of missing columns *before* any analysis
  is queued. `REQUIRED_COLUMNS` is the documented export contract. The
  worker downloads S3 datasets to a temp dir and deletes it afterwards.
  The old multipart `POST /upload` is gone (Lambda's 6 MB request cap
  would have made it fail on the first real SACCO export).
- **Activity trail**: every status/assignee/outcome/note change on a case
  writes an `ACTIVITY#` item (actor, action, from/to); `GET
  /cases/{ref}/activity` returns it newest first. Bulk status changes are
  marked `bulk: true`. The UI does not show it yet - Phase 3.
- **Logging**: `aws-lambda-powertools` `Logger` (JSON lines, works outside
  Lambda too); jobs log start/success/failure with ids. `app/
  lambda_handler.py` (Mangum) and `app/worker_handler.py` are the two
  Lambda entrypoints; the Docker image proves both import.
- **Frontend**: minimal adaptation so the app keeps working end to end -
  string case ids, `runAnalysis`/`queryAnalytics`/`generateReport` poll
  their job inside `client.ts` (pages unchanged), `uploadDataset` PUTs
  files to the returned URLs and shows finalize errors. The real UI
  rebuild is Phase 3.
- **docker-compose**: Postgres replaced by `amazon/dynamodb-local`
  (shared db on a volume); backend on host port 8001 (8000 is DynamoDB
  Local's). `JWT_SECRET` is gone from compose and `.env.example`.
- **Verified**: 78 tests (`uv run pytest`) - every API test on moto
  DynamoDB with a session-scoped table, plus moto S3 for the presigned
  path, moto SQS + the worker handler for the queue path, moto
  cognito-idp for the directory; ruff clean; backend image rebuilt and
  both Lambda entrypoints imported inside it; the real app run locally
  against DynamoDB Local (the instance already on :8000) - login, a demo
  analysis (101 flags / 91 cases, the known baseline, 7 s), dashboard,
  case list, a status change from the case page and its activity entry
  read back over the API, the clean 503 on analytics without a key.
- **Deliberately not done here**: anthropic 1.x upgrade (read the Claude
  API reference skill first), cursor pagination (`limit`/`offset` over
  the summary index is fine at hundreds of cases per run), per-tenant AI
  budget (Phase 4).

### Phase 2 - infrastructure as code (done 2026-10-19, not yet deployed)

Five CDK stacks per stage in `infra/lib/stacks/`, wired in `lib/app.ts`
(`defineStacks`) so `bin/app.ts` and the tests synthesise the same thing:

- **Data**: the table (`PK/SK`, `GSI1` with an INCLUDE projection - the
  attribute list is asserted equal to `GSI1_PROJECTED` in the backend's
  `db/table.py` by `test/stacks.test.ts`, so the two cannot drift), the
  datasets bucket (literal name `audit-intelligence-<stage>-datasets-
  <account>`, SSE-S3, TLS-only, CORS for presigned PUT, raw uploads expired
  after `datasetRetentionDays`), the access-logs bucket, and the Anthropic
  key as a Secrets Manager secret created holding `unset` - the backend
  reads it at cold start (`settings._anthropic_api_key`) and treats
  `unset` as "AI not configured", so a fresh deploy degrades cleanly.
  Prod: PITR on, deletion protection, RETAIN, termination protection. Dev:
  disposable.
- **Auth**: Cognito pool, no self sign-up, `custom:tenant` immutable,
  groups `admin`/`auditor`, 12-char password policy with symbols, MFA
  `REQUIRED` when `requireMfa` (prod) else `OPTIONAL`, Essentials plan,
  web client with SRP only, 1 h tokens, 30-day refresh, revocation on.
- **Api**: one HTTP API, every route under `/api` behind a Cognito JWT
  authorizer (`jwtAudience` = the web client, i.e. the ID token), two
  Python 3.14 arm64 functions from one asset (`constructs/
  python-function.ts`: explicit role scoped to its own log group, JSON
  logs, X-Ray, an error alarm each; `backendCode()` stages
  `requirements.txt` + `app/` + the demo CSVs *without* `ground_truth.*`
  into `infra/.lambda-src` and pip-installs `manylinux2014_aarch64`
  wheels inside the Lambda build image so the bundle is identical from a
  Mac or an x86 runner), the jobs queue (visibility 12 min > the worker's
  10 min) with a dead-letter queue after 2 receives, the worker fed one
  message at a time with `maxConcurrency` 5 (an event-source setting, not
  reserved concurrency - the account quota that bit the billing platform
  cannot bite here). Grants are explicit: table + `index/GSI1`, no `Scan`;
  `s3:GetObject`/`PutObject` on `tenants/*` only (acknowledged by literal
  ARN); Cognito admin actions on the pool without `AdminDeleteUser` or
  `AdminSetUserPassword` (Phase 4 gives `AdminDeleteUser` to the *worker*
  only, for erasure); secret read. Alarms: API 5xx, API p99 > 5 s,
  each function's errors, DLQ depth, table throttles. Function names are
  fixed (`audit-intelligence-<stage>-api|worker`) so an operator workflow
  can invoke the worker by name.
- **Web**: private bucket behind CloudFront (OAC, HTTPS redirect, HTTP/2+3,
  price class 200 for the Nairobi edge), a CloudFront Function for SPA
  routing on the default behaviour only (so an API 404 is never rewritten
  into `index.html`), `/api/*` to the gateway with caching disabled and
  `AllViewerExceptHostHeader`, CSP/HSTS headers whose `connect-src` admits
  only Cognito and the datasets bucket host, and a `BucketDeployment` of
  `frontend/dist` plus a generated `config.json` (stage, region, pool id,
  client id, `/api`) so one build is valid in every stage. A placeholder
  page is deployed when `dist/` is absent so synth works in a clean
  checkout.
- **Ops**: SNS topic + email subscription, one composite alarm over every
  alarm, a dashboard.
- **cdk-nag** (AwsSolutions, v3 `Validations` API): every finding is
  fixed or acknowledged at the construct that causes it with a reason -
  COG2/COG3/COG8 on the pool, SQS3 on the DLQ, SMG4 on the secret, DDB3
  in dev only, CFR1/2/4 on the distribution, SNS2 on the alarm topic
  (CloudWatch cannot publish to a topic encrypted with the AWS-managed
  key), the log-stream and X-Ray wildcards on each function role, and
  the eight library-generated wildcards plus L1/IAM4 on CDK's own
  `BucketDeployment` function. `scripts/nag-report.ts` prints findings
  with construct paths when the assertion in `test/nag.test.ts` fails.
  **Python 3.14**: cdk-nag's L1 flagged 3.13 as not the latest runtime;
  rather than acknowledge it, the whole backend moved to 3.14 via a
  uv-managed interpreter (`uv python install 3.14` - the Homebrew 3.14
  build on this machine is broken, the uv one is not), after confirming
  every compiled dependency publishes cp314 aarch64 wheels. 78 backend
  tests, the Docker image and the Lambda bundle all run on 3.14 now.
- **Operator path without laptop credentials**: `infra/bootstrap/
  deploy-identity.yaml` now also creates `audit-intelligence-admin-
  tasks-<stage>`, trusted by the GitHub environment `admin-tasks-<stage>`
  and allowed only `lambda:InvokeFunction` on the worker. `.github/
  workflows/provision-tenant.yml` invokes the worker with `{"admin_task":
  "create_tenant", ...}`; `worker_handler.py` creates the tenant and its
  first admin (Cognito emails the temporary password). Same shape as
  Tender Tracker's `seed-admin`.
- **Verified**: `npm run typecheck`; 38 infra tests including the nag
  probe and a full nag pass for dev and prod; `cfn-lint` clean on the
  identity template; 78 backend tests on Python 3.14; the backend Docker
  image on `python:3.14-slim`; a real `cdk synth --context stage=dev`
  with Docker bundling - five templates, a 179 MB Lambda asset holding 70
  aarch64 shared objects and the demo CSVs without the ground truth.
  Two things it took: (1) pip's `--platform` does not widen a single
  manylinux tag to the ones beneath it reliably - numpy ships
  `manylinux_2_28`, cffi ships `manylinux2014`, and asking for either
  alone refused the other - so the bundling command lists every aarch64
  manylinux tag Lambda's AL2023 (glibc 2.34) can run; (2) an environment-
  agnostic synth renders the CDK assets bucket ARN with
  `<AWS::Partition>` and a pinned-account synth renders the literal `aws`
  partition, so the BucketDeployment acknowledgement names both forms.
  `uvicorn[standard]` became plain `uvicorn`: uvloop/httptools/
  watchfiles/websockets are dev-server extras that were only adding
  weight to the bundle. **Nothing is deployed**: the
  user runs `cdk bootstrap` + `scripts/deploy-identity.sh dev` with a
  non-root identity (docs/DEPLOYING.md), then `gh workflow run
  deploy.yml -f stage=dev -f confirm=dev`.

### Phase 3 - the frontend (done 2026-10-19)

The app is no longer a three-page CRUD demo. Same indigo/slate system,
same `lucide-react` icons; the structure and the behaviour changed.

- **Runtime config + Cognito**: `src/config.ts` fetches `/config.json`
  (written by the Web stack) and falls back to local auth mode when it is
  absent, so one build serves every stage and `npm run dev` keeps working
  with no Cognito at all. `src/auth/AuthContext.tsx` drives both modes
  behind one interface: Cognito via `aws-amplify/auth` (SRP sign-in, the
  forced new-password step, TOTP setup with a QR code from `qrcode` and
  the TOTP code step - prod requires MFA - and forgot-password), local via
  `POST /auth/login`. The API client gets its bearer from a
  `setTokenProvider` hook: Cognito's **ID token** (the one carrying
  `custom:tenant`) when deployed, the stored local token otherwise.
  `LoginPage` is one multi-step form over those states; errors are
  translated from Cognito's exception names into sentences.
- **App shell** (`components/Layout.tsx`): sidebar navigation (Dashboard,
  Cases, Upload & Analyze, Rules, Users for admins) with the user and
  tenant in the footer; a top bar with the **run selector**
  (`contexts/RunContext.tsx` - the chosen run, persisted in
  localStorage, else the latest succeeded run; `previousRun` is the one
  before it) and the run button. Collapses to a top nav on small screens.
- **Rules are named everywhere**: `GET /rules` (new,
  `app/rules/catalogue.py`) returns id, name, a plain-English summary,
  how it works, what it may indicate and the thresholds with human
  labels; `contexts/RulesContext.tsx` caches it and `RuleLabel` renders
  `R001 · Large Withdrawal` with the summary as a tooltip. The **Rules
  page** is the catalogue with per-rule case counts for the selected run
  - the "what does the system check" answer for a board, in the product.
- **Dashboard**: tiles and severity bars carry run-over-run deltas
  (`+12 since last run`, red when up) from the `severity_counts`/
  `rule_counts` Phase 1 stored on each run; the most-triggered list shows
  names; the chart panel shows a `JobProgress` (elapsed seconds and a
  rotating hint) instead of a bare spinner.
- **Cases**: a TanStack Table (`ui/DataTable.tsx`, generic): search across
  case ref, member name and ID; sortable columns; 25 per page; a
  selection column that does not trigger the row click; severity, rule
  (deep-linked from the Rules page as `?rule=R00x`) and status filters in
  the URL; status pills; an **age** column. Bulk status changes and the
  board report give toasts and progress.
- **Case page**: previous/next through the run's ranking (`3 of 91`), the
  status select saves immediately with a toast, assignee/outcome have an
  explicit Save enabled only when dirty, and the **Activity** panel shows
  the Phase 1 trail as sentences ("Jane changed status from Open to In
  Progress", with the bulk marker).
- **Upload**: per-file validation errors from finalize shown inline, the
  tenant's uploaded datasets listed with status and a run button, and the
  run switches the selector to the new run when it finishes.
- **Users**: no password field in Cognito mode (Cognito emails a temporary
  one); role and activation changes toast.
- **Plumbing**: `ui/Toast.tsx` (no dependency), `ui/Skeleton.tsx` instead
  of "Loading...", `ui/ErrorBoundary.tsx`, `ui/EmptyState.tsx`, dates via
  `lib/format.ts` in `en-KE`.
- **Tests**: vitest + Testing Library (`npm test`, 14 tests: the client's
  polling and upload contract against a mocked `fetch`, the table's sort/
  search/pagination/selection, the activity sentences, the local login
  page - which caught a real bug: the login labels were not associated
  with their inputs). Playwright (`npm run test:e2e`, `e2e/smoke.spec.ts`)
  signs in, runs the demo analysis, opens the top case, changes its
  status and reads it back from the activity trail, then opens the rules
  page - against the real backend on DynamoDB Local. CI gained the unit
  tests in the frontend job and an `e2e` job that stands the same stack
  up (DynamoDB Local service container, uvicorn, Vite, Chromium).
- **Bundle**: 919 KB / 272 KB gzipped (Amplify is most of the growth).
  Code-splitting is a fast-follow if it ever matters for a tool used by a
  handful of staff.
- **Verified**: `tsc -b`, oxlint (four fast-refresh warnings on context
  files, informational), `npm run build`, 14 unit tests, the Playwright
  smoke (16.6 s), and a browser walkthrough against the local stack with
  two runs so the deltas had something to compare: dashboard, cases
  (sort, search, pills, age), a case with prev/next and its activity,
  rules. The Cognito code path cannot be exercised until dev is deployed
  - that is the first thing to do after the bootstrap.

### Phase 4 - hardening + cutover (code done 2026-10-19; cutover waits on the bootstrap)

The previous session lost its connection a minute into this phase, with
the budget half-written in the working tree; this picks it up.

- **Per-tenant AI budget** (`core/budget.py`, `repository.increment_usage`):
  every case question, chart and board report counts one against
  `USAGE#ai#<utc-day>` under the tenant's partition; past `AI_DAILY_LIMIT`
  (default 200, `aiDailyLimit` in `infra/config/<stage>.json`) the route
  answers **429** with a sentence naming the limit and the midnight-UTC
  reset, before any job is queued. The check and the increment are *one
  conditional `UpdateItem`* (`attribute_not_exists(count) OR count <
  :limit`), so concurrent requests cannot overshoot and a refused call is
  never counted. `enforce_ai_budget` depends on `get_anthropic_client`
  first, so the 503 for an unconfigured key does not eat allowance. Usage
  items carry a `ttl` (31 days); TTL is enabled on the table in CDK and in
  `create_table` for DynamoDB Local/moto, and `infra/test` asserts the
  attribute name matches `TTL_ATTRIBUTE` in `db/table.py`. The gateway
  throttle from Phase 2 (20/40 dev, 50/100 prod) remains the request-rate
  limit; this is the money limit.
- **Right to erasure** (`core/tenants.erase_tenant`): removes a tenant's
  Cognito accounts (global sign-out, then `AdminDeleteUser`, disabled ones
  included), its uploaded CSVs (by key - every dataset item names its id
  and the files are the fixed export contract - so the worker needs
  `s3:DeleteObject` under `tenants/*` and still no `s3:ListBucket`), then
  every item in the partition with the tenant record last. Exposed only as
  the worker's `delete_tenant` admin task, which refuses unless `confirm`
  repeats the slug; `.github/workflows/delete-tenant.yml` asks for the slug
  twice and runs from the `admin-tasks-<stage>` environment like
  provisioning. The **API function's role is unchanged** - it still cannot
  delete a user or an object; only the worker's role gained
  `AdminDeleteUser` and `s3:DeleteObject`, and `test/stacks.test.ts` now
  asserts that split per role rather than across the stack.
- **Prod config is committed** (`infra/config/prod.json`: same account
  `304442552123` and `eu-west-1` as dev and every other AmaniLabs product,
  MFA required, 90-day logs). The gitignore rule and `prod.json.example`
  are gone: dev.json already carried the account id, and a config CI cannot
  read is one CI cannot synthesise. `deploy.yml` needed no change - the
  typed confirmation for prod is the word `prod`, and the `prod` +
  `admin-tasks-prod` GitHub environments come from
  `scripts/deploy-identity.sh prod`.
- **Docs**: `docs/RUNBOOK.md` (alarms, stuck/failed/parked jobs and the DLQ
  redrive, 503/429 on AI, sign-in problems, immediate access removal, data
  held per tenant and erasure, PITR restore, rollback by tag, key rotation,
  costs); `docs/DECOMMISSION_EC2.md` (the teardown, step by step, by
  discovery from the Elastic IP rather than remembered ids, with the
  `audit-intelligence` profile for EC2 and an admin identity for the IAM
  user, gated on prod being live and walked); `docs/DEPLOYING.md` gained
  the prod section and tenant removal.
- **Deliberately not done**: a custom domain (none exists; CloudFront's
  URL is the address until one does - adding `domainName`/`certificateArn`
  to the config schema is a half-day when it comes), WAF (CFR2
  acknowledged in Phase 2; a fixed monthly cost for a tool used by a
  handful of staff behind Cognito), and the EC2 teardown itself, which the
  plan puts after the prod cutover and which needs identities this machine
  must not use.
- **Verified**: ruff clean; **89** backend tests (`test_budget.py`: the
  limit, per-tenant isolation, 503 not counted, the conditional write and
  the TTL attribute; `test_tenant_erasure.py`: a full tenant with a run,
  cases, dataset and login erased with the neighbour intact, S3 objects
  deleted without listing, Cognito accounts including a disabled one, and
  the worker task's typed confirmation); infra typecheck + **41** tests
  including the cdk-nag pass for dev and prod; a real `cdk synth` of the
  prod stage with Docker bundling.

### What the next session should do

Everything from here needs the one-time bootstrap, which only Hashim can
run (a non-root admin identity; `docs/DEPLOYING.md` section 1):

1. `cdk bootstrap aws://304442552123/eu-west-1`, then
   `scripts/deploy-identity.sh dev hashimamani/amanilabs-audit-intelligence <admin-profile>`
   and the `gh` commands it prints.
2. `gh workflow run deploy.yml -f stage=dev` (dry run), then with
   `-f confirm=dev`. Confirm the alarm email, put the Anthropic key in,
   provision a tenant, sign in through Cognito (new password, optional
   TOTP) and walk the app on the CloudFront URL. This is the first time the
   Cognito code path in the frontend runs against a real pool.
3. Repeat for prod (`deploy-identity.sh prod`, `confirm=prod`, MFA
   enrolment on first sign-in), provision the real SACCO tenant.
4. Then `docs/DECOMMISSION_EC2.md`.

Anything found broken on dev in step 2 is the next coding work; nothing in
the plan is left to build before that.
