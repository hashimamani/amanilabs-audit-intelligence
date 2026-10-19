#!/usr/bin/env bash
#
# Create or update the deploy identity for a stage.
#
# Run once per stage, with administrative (non-root) credentials. After it,
# those credentials are not needed again: deployments run as the role this
# creates, which can start a CloudFormation deployment and do nothing else.
#
#   scripts/deploy-identity.sh <stage> <owner/repo> [aws-profile]
#
# The second argument is the GitHub repository the deployment runs from. The
# script reads its numeric ids and builds the OIDC subject from them, which is
# the part everybody gets wrong — see below.
#
set -euo pipefail

STAGE="${1:-}"
REPO="${2:-}"
PROFILE="${3:-}"

if [[ -z "$STAGE" || -z "$REPO" ]]; then
  echo "usage: scripts/deploy-identity.sh <stage> <owner/repo> [aws-profile]" >&2
  exit 2
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG="$ROOT/infra/config/$STAGE.json"
TEMPLATE="$ROOT/infra/bootstrap/deploy-identity.yaml"
STACK="audit-intelligence-deploy-identity-$STAGE"

[[ -f "$CONFIG" ]] || { echo "no deploy config at $CONFIG" >&2; exit 2; }

# Under `set -u`, bash 3.2 (what macOS ships) treats an empty array expanded as
# "${arr[@]}" as unbound, so a wrapper rather than an argument array.
aws_cli() {
  if [[ -n "$PROFILE" ]]; then
    aws --profile "$PROFILE" "$@"
  else
    aws "$@"
  fi
}

REGION="$(node -e "process.stdout.write(require('$CONFIG').region ?? 'eu-west-1')")"
IDENTITY="$(aws_cli sts get-caller-identity --query Arn --output text)"
ACCOUNT="$(aws_cli sts get-caller-identity --query Account --output text)"

if [[ "$IDENTITY" == *":root" ]]; then
  echo "Refusing to run as the account root user ($IDENTITY)." >&2
  echo "Use an IAM user or role with administrative permissions instead." >&2
  exit 1
fi

# --- The OIDC subject ---------------------------------------------------------
#
# GitHub can issue either of two subject forms, and which one it sends is a
# repository setting rather than a choice the workflow makes. The *immutable*
# form carries numeric owner and repository ids:
#
#   repo:owner@<owner id>/<repo>@<repo id>:environment:<environment>
#
# A trust policy written from a standard guide uses the readable form, and the
# failure is a flat "Not authorized to perform sts:AssumeRoleWithWebIdentity"
# that names nothing. The ids are read from GitHub now rather than recovered
# from a denied attempt in CloudTrail afterwards.

OWNER="${REPO%%/*}"
NAME="${REPO##*/}"

command -v gh >/dev/null || { echo "the GitHub CLI (gh) is needed to read the repository ids" >&2; exit 2; }

OWNER_ID="$(gh api "users/$OWNER" --jq .id)"
REPO_ID="$(gh api "repos/$REPO" --jq .id)"

DEPLOY_SUBJECT="repo:${OWNER}@${OWNER_ID}/${NAME}@${REPO_ID}:environment:${STAGE}"

OIDC_ARN="$(aws_cli iam list-open-id-connect-providers \
  --query "OpenIDConnectProviderList[?contains(Arn,'token.actions.githubusercontent.com')].Arn | [0]" \
  --output text)"

if [[ "$OIDC_ARN" == "None" || -z "$OIDC_ARN" ]]; then
  echo "This account has no GitHub OIDC provider. Create one first:" >&2
  echo "  aws iam create-open-id-connect-provider \\" >&2
  echo "    --url https://token.actions.githubusercontent.com \\" >&2
  echo "    --client-id-list sts.amazonaws.com" >&2
  exit 1
fi

echo "identity     $IDENTITY"
echo "account      $ACCOUNT"
echo "region       $REGION"
echo "stage        $STAGE"
echo "repository   $REPO"
echo "deploy sub   $DEPLOY_SUBJECT"
echo "oidc         $OIDC_ARN"
echo

aws_cli cloudformation deploy \
  --stack-name "$STACK" \
  --template-file "$TEMPLATE" \
  --capabilities CAPABILITY_NAMED_IAM \
  --region "$REGION" \
  --parameter-overrides \
    "Stage=$STAGE" \
    'TrustMode=GitHubOidc' \
    "GitHubSubject=$DEPLOY_SUBJECT" \
    "OidcProviderArn=$OIDC_ARN" \
    "DeployRegion=$REGION"

DEPLOY_ROLE="$(aws_cli cloudformation describe-stacks --stack-name "$STACK" --region "$REGION" \
  --query "Stacks[0].Outputs[?OutputKey=='DeployRoleArn'].OutputValue | [0]" --output text)"

cat <<SUMMARY

Done. Now tell GitHub about it:

  gh api --method PUT "repos/$REPO/environments/$STAGE" >/dev/null
  gh variable set AWS_DEPLOY_ROLE_ARN --repo $REPO --env $STAGE --body "$DEPLOY_ROLE"
  gh variable set AWS_REGION          --repo $REPO --env $STAGE --body "$REGION"

The environment is what the trust policy pins the subject to, so a workflow run
outside it cannot assume the role however it is triggered. Add a required
reviewer to it if the plan allows one (GitHub does not offer that for private
repositories on the free plan — the deploy workflow's typed confirmation is the
guard instead).
SUMMARY
