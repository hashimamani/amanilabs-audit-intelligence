# Deploying

Audit Intelligence deploys to AWS from GitHub Actions. Nothing in this
repository holds an AWS key; each workflow mints a short-lived credential
from GitHub's OIDC token and assumes a role that can do exactly one thing.

> **Never deploy with the account root user.** Root cannot assume a role
> at all ("Roles may not be assumed by root accounts"), and a deployment
> that ran as root would leave a trail no access review can accept. The
> one-time bootstrap below needs an IAM user or role with administrative
> permissions; after it, nothing needs those credentials again.

## What gets deployed

Five CloudFormation stacks per stage, `AuditIntelligence-<stage>-*`:

| Stack  | Holds                                                                                   |
| ------ | --------------------------------------------------------------------------------------- |
| `Data` | the DynamoDB table, the datasets bucket (raw uploads, expired after `datasetRetentionDays`), the access-logs bucket, the Anthropic API key secret |
| `Auth` | the Cognito user pool (no self sign-up, `admin`/`auditor` groups, `custom:tenant`), the web client |
| `Api`  | the HTTP API with its JWT authorizer, the API function, the jobs queue + dead-letter queue, the worker function, the alarms |
| `Web`  | the app bucket, the CloudFront distribution (fronting `/api/*`), `config.json` |
| `Ops`  | the alarm topic and email subscription, the composite alarm, the dashboard |

| Stage  | Account        | Region      | Config                                   |
| ------ | -------------- | ----------- | ---------------------------------------- |
| `dev`  | `304442552123` | `eu-west-1` | `infra/config/dev.json` (committed)      |
| `prod` | not yet set up | `eu-west-1` | `infra/config/prod.json` (not committed) |

## 1. One-time bootstrap (a human, with admin credentials)

Once per account and region:

```bash
cd infra && npx cdk bootstrap aws://304442552123/eu-west-1 --profile <admin-profile>
```

Then create the deploy identity for a stage. The script reads the numeric
GitHub owner and repository ids and builds the *immutable* OIDC subject from
them - the part that goes wrong when a trust policy is written from a
standard guide (the failure is a flat `Not authorized to perform
sts:AssumeRoleWithWebIdentity` that names nothing):

```bash
scripts/deploy-identity.sh dev hashimamani/amanilabs-audit-intelligence <admin-profile>
```

It refuses to run as root, needs the GitHub CLI (`gh`) signed in, and expects
the account to already hold a GitHub OIDC provider (it prints the one
command to create it if not). When it finishes it prints the exact `gh`
commands that create two GitHub environments and set their variables. Run
them.

It creates two roles, and the split is the point:

| Role                                   | What it can do                                                            |
| -------------------------------------- | ------------------------------------------------------------------------- |
| `audit-intelligence-deploy-<stage>`    | Assume the CDK bootstrap roles in one region and read the bootstrap version parameter. That is all. |
| `audit-intelligence-admin-tasks-<stage>` | Invoke the worker function. Nothing else - the worker's own role is what touches the table and Cognito. |

Everything that creates infrastructure lives in the CloudFormation execution
role that `cdk bootstrap` made, which only CloudFormation can use. A leaked
deploy credential cannot read a SACCO's data.

## 2. Configure the stage

`infra/config/dev.json` is committed. `prod.json` is not:

```bash
cp infra/config/prod.json.example infra/config/prod.json
```

Every value is validated at synth, before any construct exists:

```bash
cd infra && npm ci && npm run typecheck && npm test && npm run synth
```

`npm run synth` bundles the backend for Lambda inside Docker (wheels for
`manylinux2014_aarch64` / Python 3.14), so it needs Docker running and takes
a couple of minutes the first time.

## 3. Deploy

```bash
gh workflow run deploy.yml -f stage=dev            # dry run: assumes the role, shows the diff, stops
gh workflow run deploy.yml -f stage=dev -f confirm=dev
```

The typed confirmation is the approval gate: GitHub does not offer required
reviewers on private repositories on the free plan. An empty box is a dry
run. The workflow builds the frontend first, so the Web stack ships the real
bundle.

## 4. After the first deploy

1. **Confirm the alarm email.** AWS emails `alarmEmail` a subscription
   confirmation. Until the link is clicked the alarms exist and reach
   nobody.
2. **Put the Anthropic key in.** The `Data` stack created the secret holding
   the literal value `unset`, which the backend treats as "AI features are
   not configured" (case Q&A, chart analytics and board reports answer with
   a clean 503; everything else works). With any identity allowed to write
   that one secret:

   ```bash
   aws secretsmanager put-secret-value \
     --secret-id audit-intelligence-dev-anthropic-api-key \
     --secret-string "$ANTHROPIC_API_KEY" --region eu-west-1
   ```

   Functions read it at cold start; the next cold start after this picks it up.
3. **Provision the first tenant.** Nothing on a laptop touches the table or
   Cognito; the `provision tenant` workflow asks the deployed worker to do
   it, from the `admin-tasks-<stage>` environment:

   ```bash
   gh workflow run provision-tenant.yml -f stage=dev \
     -f slug=demo-sacco -f name="Demo SACCO" \
     -f admin_email=you@amanilabs.co.ke -f admin_name="Your Name"
   ```

   Cognito emails the administrator a temporary password; the first sign-in
   asks them to choose their own. Every further user for that tenant is
   created by that administrator inside the app.
4. **Open the app** at the `AppUrl` output of the Web stack (the workflow
   summary prints it) and sign in.

## Verifying

- `aws dynamodb describe-table --table-name audit-intelligence-prod-main`
  shows `ACTIVE`, point-in-time recovery on and deletion protection `true`
  (prod only; dev is rebuildable by design).
- The CloudWatch dashboard `audit-intelligence-<stage>-ops` shows the API,
  the worker and the queue; the composite alarm
  `audit-intelligence-<stage>-unhealthy` is `OK`.
- Run an analysis on the demo dataset from the app and open a case.

## Destroying

Production data resources are `RETAIN` with deletion protection, and prod
stacks carry termination protection. `cdk destroy` will refuse, and if forced
will leave the table and buckets behind. Removing a SACCO's audit records is
a manual act taken on purpose, not a side effect of tearing down a stack.
Dev can be destroyed and rebuilt freely.
