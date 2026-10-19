# Deploying

Audit Intelligence deploys to AWS from GitHub Actions. Nothing in this
repository holds an AWS key; the workflow mints a short-lived credential from
GitHub's OIDC token and assumes a role that can start a CloudFormation
deployment and nothing else.

> **Never deploy with the account root user.** Root cannot assume a role at
> all ("Roles may not be assumed by root accounts"), and a deployment that
> ran as root would leave a trail no access review can accept. Every step
> below that touches AWS by hand needs an IAM user or role with administrative
> permissions — once, for the bootstrap — and nothing after that.

## What is deployed

| Stage  | Account         | Region      | Deployed by                       |
| ------ | --------------- | ----------- | --------------------------------- |
| `dev`  | the dev account | `eu-west-1` | `deploy.yml`, dispatched by hand  |
| `prod` | not yet set up  | `eu-west-1` | `deploy.yml`, dispatched by hand  |

The stacks arrive in phase 2 of the serverless rebuild (see
`PROJECT_CONTEXT.md` section 23). Until then `cdk synth` produces an empty
app, and a dry-run dispatch of `deploy.yml` proves the identity chain works
before there is anything to deploy.

## 1. One-time bootstrap (a human, with admin credentials)

Once per account and region:

```bash
npx --prefix infra cdk bootstrap aws://<account-id>/eu-west-1 --profile <admin-profile>
```

Then create the deploy identity for a stage. The script reads the numeric
GitHub owner and repository ids and builds the *immutable* OIDC subject from
them — the part that goes wrong when a trust policy is written from a
standard guide (the failure is a flat `Not authorized to perform
sts:AssumeRoleWithWebIdentity` that names nothing):

```bash
scripts/deploy-identity.sh dev hashimamani/amanilabs-audit-intelligence <admin-profile>
```

It refuses to run as root, needs the GitHub CLI (`gh`) signed in, and expects
the account to already hold a GitHub OIDC provider (it prints the one
command to create it if not). When it finishes it prints the exact `gh`
commands that create the GitHub environment and set
`AWS_DEPLOY_ROLE_ARN` / `AWS_REGION` on it. Run them.

The role it creates, `audit-intelligence-deploy-<stage>`, can assume the CDK
bootstrap roles in one region and read the bootstrap version parameter. That
is all. Everything that creates infrastructure lives in the CloudFormation
execution role `cdk bootstrap` made, which only CloudFormation can use.

## 2. Configure the stage

`infra/config/dev.json` is committed. `prod.json` is not, because it carries
a real account id:

```bash
cp infra/config/prod.json.example infra/config/prod.json
```

Every value is validated at synth, before any construct exists, so a bad
value fails here rather than in a running system:

```bash
cd infra && npm ci && npm run typecheck && npm test && npm run synth
```

## 3. Deploy

```bash
gh workflow run deploy.yml -f stage=dev            # dry run: assumes the role, shows the diff, stops
gh workflow run deploy.yml -f stage=dev -f confirm=dev
```

The typed confirmation is the approval gate: GitHub does not offer required
reviewers on private repositories on the free plan. An empty box is a dry
run.

## 4. Verify

After a deploy, the workflow summary lists the stack outputs. The checks that
matter once the stacks exist:

- `aws dynamodb describe-table` shows `ACTIVE`, point-in-time recovery on
  and deletion protection `true` for prod.
- The alarm email subscription has been confirmed (AWS emails a link; until
  it is clicked the alarms exist and reach nobody).
- Sign in at the CloudFront URL, run an analysis on the demo dataset, open a
  case.

## Destroying

Production data resources are `RETAIN` with deletion protection, and prod
stacks carry termination protection. `cdk destroy` will refuse, and if forced
will leave the table and buckets behind. Removing a SACCO's audit records is
a manual act taken on purpose, not a side effect of tearing down a stack.
