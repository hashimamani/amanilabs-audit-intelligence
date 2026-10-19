# Runbook

What to do when something goes wrong, written for whoever is on call rather
than for whoever wrote the code. Every command below runs from GitHub
Actions or from an AWS identity that is not the account root; see
`docs/DEPLOYING.md` for why.

**The one thing to hold on to:** the cases are the record, the uploaded CSVs
are not. A SACCO's raw export is deleted `datasetRetentionDays` after upload
by design; the cases, evidence, notes and activity built from it live in the
table, which in prod has point-in-time recovery and deletion protection.
Nothing slow runs inside an HTTP request: the rule engine and every AI
feature are jobs on a queue, so a failure parks a message rather than losing
a result.

---

## Alarms and what they mean

Every alarm rolls into one composite alarm, `audit-intelligence-<stage>-unhealthy`,
which emails `alarmEmail` on ALARM and again on OK. Open the dashboard
`audit-intelligence-<stage>-ops` to see which of these is red.

| Alarm | Means | Urgency |
| --- | --- | --- |
| API function errors | The API Lambda is raising | **High.** The app is broken for everyone |
| API 5xx | The gateway saw server errors (integration timeouts count) | **High.** Same |
| API p99 latency > 5 s (three periods) | Requests are slow enough that the app feels broken | Medium. Usually a cold-start burst or a slow DynamoDB query; read the X-Ray traces |
| Worker errors | A job crashed | Medium. The job record says `failed` with a safe message; the traceback is in the worker's log, keyed by `job_id` |
| Dead-letter queue not empty | A job failed twice and was parked | Medium. See "A job is parked" |
| Table throttled | DynamoDB refused a request | Medium. Should never happen on an on-demand table at this volume; a hot partition means one tenant did something unusual |

No invocations outside office hours is the normal state; every alarm treats
missing data as fine.

---

## An analysis run says "failed" or never finishes

1. Find the job. The run record carries `job_id`; `GET /api/jobs/{id}` (as a
   user of that tenant) or the `JOB#<id>` item under `TENANT#<slug>` shows
   `status`, `error` and timestamps.
2. **`failed` with a message** - the message is the one the auditor saw. A
   `JobFailed` from the code is a known, safe failure (dataset not ready,
   missing columns). Anything else is a generic "The job failed" and the
   traceback is in the worker's log group under the same `job_id`.
3. **`running` for more than ten minutes** - the worker timed out or
   crashed. SQS redelivers the message once (visibility 12 minutes); the
   worker treats a `running` job as retryable, so it usually completes on
   the second attempt. If it fails again it lands in the dead-letter queue.
4. **`queued` and nothing happens** - the API could not reach SQS or the
   worker's event source is disabled. Check the worker's error alarm and the
   `JobsQueueUrl` output; `aws lambda get-event-source-mapping` should say
   `Enabled`.

## A job is parked in the dead-letter queue

Jobs are idempotent on redelivery: a finished job is skipped, a `running`
one is retried. Fix the cause first (read the error, deploy the fix), then
move the messages back:

```bash
aws sqs start-message-move-task \
  --source-arn arn:aws:sqs:eu-west-1:<account>:audit-intelligence-<stage>-jobs-dlq \
  --destination-arn arn:aws:sqs:eu-west-1:<account>:audit-intelligence-<stage>-jobs
```

If the job is genuinely unrecoverable (a dataset that expired before the
run started), purge the DLQ and tell the auditor to upload and run again.
The failed run is never shown as the tenant's latest - the dashboard only
reads succeeded runs - so nothing on screen is wrong meanwhile.

## AI features say "not configured" (503)

The Anthropic key secret still holds `unset`, or the key was revoked. Put
the key in (`docs/DEPLOYING.md`, section 4). Functions read it at cold
start: new execution environments pick it up at once, warm ones within the
hour as they recycle. To force it, change any function configuration (the
description will do) from the console with an admin identity; that
recycles every environment.

## AI features say the daily allowance is used up (429)

Each tenant may make `aiDailyLimit` paid AI calls (case questions, charts,
board reports) per UTC day - 200 unless the stage config says otherwise.
This is a ceiling on the Anthropic bill per customer, not a product
feature, and the message tells the auditor it resets at midnight UTC.

- To see the count: the `USAGE#ai#<yyyy-mm-dd>` item under
  `TENANT#<slug>`. It expires by TTL after a month.
- To raise it for everyone: change `aiDailyLimit` in
  `infra/config/<stage>.json` and deploy.
- To raise it for one tenant today: delete that one item. A refused call
  is never counted and never reached the model.

## A user cannot sign in

Sign-in is Cognito's. The app only reads the ID token.

- **Forgot password** - self-service on the login page.
- **Lost authenticator** (prod requires one) - an administrator resets it
  in the Cognito console (user pool `audit-intelligence-<stage>`, the user,
  "Reset MFA"); the next sign-in enrols a new one. Nothing in the app can do
  this, by design.
- **"User is disabled"** - an admin of that tenant deactivated them on the
  Users page. Reactivating there re-enables the Cognito account.
- **Temporary password expired** - it lasts seven days. Deactivate and
  reactivate does not reissue it; create the user again with a new email
  address or resend from the Cognito console ("Resend invitation").

## Remove someone's access right now

Their tenant's administrator deactivates them on the Users page. That
disables the Cognito account, signs them out of every device, and - because
the API reads the user's mirror item on every request - takes effect on the
next request, not when their token expires.

## A SACCO asks what you hold about them, or asks you to delete it

**What is held, per tenant:** every item under `TENANT#<slug>` in the table
(the tenant, its users, runs, cases with evidence, notes and activity
trail, jobs, dataset records, usage counters); uploaded CSVs under
`tenants/<slug>/` in the datasets bucket until they expire; one Cognito
account per user. Logs carry tenant slugs, job ids and user subs, not
member names: the API access log has no bodies or query strings, and
application logs name ids. Logs expire after `logRetentionDays`.

**To delete it:** the `delete tenant` workflow (`docs/DEPLOYING.md`,
section 6). It removes the Cognito accounts first, then the files, then the
partition. There is no undo short of a point-in-time restore of the whole
table, which is why the slug is typed twice.

## Restoring from point-in-time recovery (prod)

The prod table has PITR (35-day window) and deletion protection. PITR
restores to a **new table**; it cannot overwrite in place. So a restore is a
deliberate operation, not a quick fix:

1. Restore to `audit-intelligence-prod-main-restore-<date>` from the
   console or `aws dynamodb restore-table-to-point-in-time`.
2. Compare against the live table and decide exactly which items are wrong -
   usually one tenant's partition, because everything a tenant owns shares
   one partition key.
3. Copy only those items back (a `Query` by `PK` on the restored table and
   a `BatchWriteItem` to the live one), or, if everything is wrong, repoint
   the functions at the restored table by renaming it into place with an
   admin identity. Never delete the live table; it has deletion protection
   for this reason.
4. Delete the restored copy when done; it is billed like any table.

Dev has no PITR. Destroy it and deploy again.

## Rolling back a deployment

CloudFormation rolls a failed deployment back by itself. To roll back a
successful one that turned out wrong, deploy the last good commit: tag it
and dispatch the workflow on the tag.

```bash
git tag rollback-$(date +%Y%m%d) <good sha> && git push origin rollback-$(date +%Y%m%d)
gh workflow run deploy.yml --ref rollback-$(date +%Y%m%d) -f stage=prod -f confirm=prod
```

Data is never part of a rollback: the table and buckets are shared by every
deployment of a stage.

## Rotating the Anthropic key

Issue a new key in the Anthropic console, `put-secret-value` as in
`docs/DEPLOYING.md` section 4, wait for the functions to recycle (or force
it as above), then revoke the old key. Doing it in that order means the AI
features never answer 503 in between.

## Costs look wrong

Idle cost is a few dollars a month: on-demand DynamoDB, S3, CloudFront,
Secrets Manager, CloudWatch. The two things that can grow are Anthropic
usage - bounded per tenant by `aiDailyLimit` - and Lambda time, bounded by
`maxConcurrency` 5 on the worker. Everything carries the `Project`,
`Environment` and `ManagedBy` tags, so Cost Explorer can split it by stage.
The old EC2 pilot in us-east-1 is the other place to look until it is
decommissioned (`docs/DECOMMISSION_EC2.md`).

## Testing against dev

Dev is disposable. Provision a tenant with the `provision tenant` workflow,
sign in, press "Run analysis" with the bundled demo dataset (101 flags,
91 cases is the known baseline) and open the top case. Erase the tenant
with `delete tenant` when done, or leave it: nothing in dev costs anything
while nobody is using it.
