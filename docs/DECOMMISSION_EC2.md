# Decommissioning the EC2 pilot

The first pilot ran on one hand-built EC2 instance in `us-east-1`
(`PROJECT_CONTEXT.md`, section 18): Docker Compose, Postgres in a container,
plain HTTP on an Elastic IP, deployed by `rsync` with a dedicated IAM user.
The serverless rebuild (section 23) replaces all of it, and the decision was
to remove every manually created resource rather than leave it running or
improve it.

Nothing on the box needs migrating: only the bundled demo tenant and smoke
tenants ever existed on it. The real SACCO tenant was never provisioned
there.

## When

After - not before - production is deployed, the alarm email is confirmed,
and a real sign-in, analysis run and case review have been walked through
on the prod CloudFront URL. Until then the box is the only running copy of
the product.

Tell anyone who still has `http://34.233.59.94/` that it is going away;
the new address is the `AppUrl` output of the prod Web stack.

## Who

The `audit-intelligence` AWS CLI profile is the IAM user
`audit-intelligence-deploy` with `AmazonEC2FullAccess`. It can do steps 1
to 7 and cannot delete itself; step 8 needs an administrative identity that
is not the account root.

## Steps

Every command below is `--region us-east-1 --profile audit-intelligence`
unless it says otherwise. Each step prints what it found before it deletes
anything; read it.

1. **Find everything by the Elastic IP** rather than from memory:

   ```bash
   aws ec2 describe-addresses --public-ips 34.233.59.94 --region us-east-1 --profile audit-intelligence
   ```

   Note `InstanceId`, `AllocationId` and `AssociationId`.

2. **Confirm what is on the instance** (optional, last chance):

   ```bash
   ssh -i ~/.ssh/audit-intelligence-key.pem ubuntu@34.233.59.94 'sudo docker compose ps'
   ```

   No snapshot is taken on purpose: the volume holds only demo data and a
   rotated dev admin hash, and a snapshot would keep both indefinitely.

3. **Terminate the instance** and wait for it. The root volume was created
   with the instance and is deleted with it.

   ```bash
   aws ec2 terminate-instances --instance-ids <InstanceId> --region us-east-1 --profile audit-intelligence
   aws ec2 wait instance-terminated --instance-ids <InstanceId> --region us-east-1 --profile audit-intelligence
   ```

4. **Release the Elastic IP.** An address that is allocated but not
   attached is billed hourly, so this step matters more than it looks.

   ```bash
   aws ec2 disassociate-address --association-id <AssociationId> --region us-east-1 --profile audit-intelligence
   aws ec2 release-address --allocation-id <AllocationId> --region us-east-1 --profile audit-intelligence
   ```

5. **Delete the security group** `audit-intelligence-sg` (it can only go
   once the instance is terminated):

   ```bash
   aws ec2 describe-security-groups --filters Name=group-name,Values=audit-intelligence-sg --query 'SecurityGroups[].GroupId' --region us-east-1 --profile audit-intelligence
   aws ec2 delete-security-group --group-id <GroupId> --region us-east-1 --profile audit-intelligence
   ```

6. **Delete the key pair**, in AWS and on disk:

   ```bash
   aws ec2 describe-key-pairs --query 'KeyPairs[].KeyName' --region us-east-1 --profile audit-intelligence
   aws ec2 delete-key-pair --key-name audit-intelligence-key --region us-east-1 --profile audit-intelligence
   rm ~/.ssh/audit-intelligence-key.pem
   ```

7. **Look for leftovers** - a detached volume or a snapshot that should not
   exist:

   ```bash
   aws ec2 describe-volumes --filters Name=status,Values=available --query 'Volumes[].VolumeId' --region us-east-1 --profile audit-intelligence
   aws ec2 describe-snapshots --owner-ids self --query 'Snapshots[].SnapshotId' --region us-east-1 --profile audit-intelligence
   ```

   Delete anything listed (`delete-volume`, `delete-snapshot`).

8. **Remove the IAM user** `audit-intelligence-deploy`, with an
   administrative (non-root) identity. Its access key is the last
   long-lived AWS credential this project ever had.

   ```bash
   aws iam list-access-keys --user-name audit-intelligence-deploy --profile <admin-profile>
   aws iam delete-access-key --user-name audit-intelligence-deploy --access-key-id <AccessKeyId> --profile <admin-profile>
   aws iam detach-user-policy --user-name audit-intelligence-deploy --policy-arn arn:aws:iam::aws:policy/AmazonEC2FullAccess --profile <admin-profile>
   aws iam delete-user --user-name audit-intelligence-deploy --profile <admin-profile>
   ```

   Then remove the `[audit-intelligence]` profile from `~/.aws/credentials`
   and `~/.aws/config`.

9. **Verify** a week later: Cost Explorer filtered to `us-east-1` shows no
   EC2, EBS or Elastic IP charges, and
   `aws ec2 describe-instances --region us-east-1` lists nothing for this
   project.

10. **Record it**: change the heading of `PROJECT_CONTEXT.md` section 18
    to "(decommissioned <date>)" and remove the `http://34.233.59.94/`
    access line.

## What is deliberately not deleted

- The GitHub OIDC provider in IAM: Tender Tracker and the billing platform
  use it too.
- The CDK bootstrap stack `CDKToolkit` in `eu-west-1`: every product's
  deploys go through it.
- The `audit-intelligence-deploy-identity-<stage>` stacks: they are the
  new deploy path, not the old one.
