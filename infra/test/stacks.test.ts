import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { Match } from 'aws-cdk-lib/assertions';
import { beforeAll, describe, expect, it } from 'vitest';
import { GSI1_PROJECTED, TTL_ATTRIBUTE } from '../lib/stacks/data-stack.js';
import { buildApp, type Synthesised } from './helpers.js';

const repoRoot = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const tablePy = () => readFileSync(join(repoRoot, 'audit_intelligence', 'backend', 'app', 'db', 'table.py'), 'utf8');

let dev: Synthesised;
let prod: Synthesised;

beforeAll(() => {
  dev = buildApp('dev', undefined, false);
  prod = buildApp('prod', undefined, false);
});

/** The IAM policies attached to one function's role, as one searchable string. */
function policiesOf(synth: Synthesised, fn: 'ApiFn' | 'WorkerFn'): string {
  const policies = Object.values(synth.templates.api.findResources('AWS::IAM::Policy')).filter((policy) =>
    (policy.Properties.Roles as { Ref: string }[]).some((role) => role.Ref.startsWith(`${fn}Role`)),
  );
  expect(policies.length, `${fn} has no inline policy`).toBeGreaterThan(0);
  return JSON.stringify(policies);
}

describe('DataStack', () => {
  it('creates one on-demand table with the key schema the backend uses', () => {
    const t = prod.templates.data;
    t.resourceCountIs('AWS::DynamoDB::Table', 1);
    t.hasResourceProperties('AWS::DynamoDB::Table', {
      BillingMode: 'PAY_PER_REQUEST',
      KeySchema: [
        { AttributeName: 'PK', KeyType: 'HASH' },
        { AttributeName: 'SK', KeyType: 'RANGE' },
      ],
      GlobalSecondaryIndexes: [
        Match.objectLike({
          IndexName: 'GSI1',
          KeySchema: [
            { AttributeName: 'GSI1PK', KeyType: 'HASH' },
            { AttributeName: 'GSI1SK', KeyType: 'RANGE' },
          ],
          Projection: { ProjectionType: 'INCLUDE', NonKeyAttributes: GSI1_PROJECTED },
        }),
      ],
      TimeToLiveSpecification: { AttributeName: TTL_ATTRIBUTE, Enabled: true },
    });
  });

  it('projects exactly the attributes the backend declares', () => {
    const block = /GSI1_PROJECTED = \[([\s\S]*?)\]/u.exec(tablePy())?.[1] ?? '';
    const declared = [...block.matchAll(/"([a-z_]+)"/gu)].map((m) => m[1]);
    expect(declared).toEqual(GSI1_PROJECTED);
  });

  it('expires items by the attribute the backend writes', () => {
    expect(/TTL_ATTRIBUTE = "([a-z_]+)"/u.exec(tablePy())?.[1]).toBe(TTL_ATTRIBUTE);
  });

  it('protects production data from a stack deletion', () => {
    prod.templates.data.hasResource('AWS::DynamoDB::Table', {
      DeletionPolicy: 'Retain',
      Properties: Match.objectLike({
        PointInTimeRecoverySpecification: { PointInTimeRecoveryEnabled: true },
        DeletionProtectionEnabled: true,
      }),
    });
    expect(prod.data.terminationProtection).toBe(true);
  });

  it('lets dev be torn down and rebuilt freely', () => {
    dev.templates.data.hasResource('AWS::DynamoDB::Table', { DeletionPolicy: 'Delete' });
    expect(dev.data.terminationProtection).toBe(false);
  });

  it('blocks public access, enforces TLS and expires raw uploads', () => {
    const buckets = prod.templates.data.findResources('AWS::S3::Bucket');
    expect(Object.keys(buckets)).toHaveLength(2);
    for (const bucket of Object.values(buckets)) {
      expect(bucket.Properties.PublicAccessBlockConfiguration).toEqual({
        BlockPublicAcls: true, BlockPublicPolicy: true, IgnorePublicAcls: true, RestrictPublicBuckets: true,
      });
    }
    expect(JSON.stringify(prod.templates.data.findResources('AWS::S3::BucketPolicy'))).toMatch(/aws:SecureTransport/u);
    prod.templates.data.hasResourceProperties('AWS::S3::Bucket', {
      BucketName: 'audit-intelligence-prod-datasets-123456789012',
      LifecycleConfiguration: {
        Rules: Match.arrayWith([Match.objectLike({ Id: 'expire-raw-uploads', Prefix: 'tenants/', ExpirationInDays: 30 })]),
      },
    });
  });

  it('creates the AI key secret holding the sentinel the backend treats as unset', () => {
    prod.templates.data.hasResourceProperties('AWS::SecretsManager::Secret', {
      Name: 'audit-intelligence-prod-anthropic-api-key',
      SecretString: 'unset',
    });
  });
});

describe('AuthStack', () => {
  it('allows no public sign-up and carries the tenant as an immutable attribute', () => {
    prod.templates.auth.hasResourceProperties('AWS::Cognito::UserPool', {
      AdminCreateUserConfig: Match.objectLike({ AllowAdminCreateUserOnly: true }),
      Schema: Match.arrayWith([Match.objectLike({ Name: 'tenant', AttributeDataType: 'String', Mutable: false })]),
    });
  });

  it('creates one group per role', () => {
    prod.templates.auth.resourceCountIs('AWS::Cognito::UserPoolGroup', 2);
    for (const role of ['admin', 'auditor']) {
      prod.templates.auth.hasResourceProperties('AWS::Cognito::UserPoolGroup', { GroupName: role });
    }
  });

  it('requires MFA in prod and leaves it optional in dev', () => {
    prod.templates.auth.hasResourceProperties('AWS::Cognito::UserPool', { MfaConfiguration: 'ON' });
    dev.templates.auth.hasResourceProperties('AWS::Cognito::UserPool', { MfaConfiguration: 'OPTIONAL' });
  });

  it('issues one-hour tokens with revocation and no client secret', () => {
    prod.templates.auth.hasResourceProperties('AWS::Cognito::UserPoolClient', {
      AccessTokenValidity: 60,
      IdTokenValidity: 60,
      RefreshTokenValidity: 43_200,
      TokenValidityUnits: { AccessToken: 'minutes', IdToken: 'minutes', RefreshToken: 'minutes' },
      EnableTokenRevocation: true,
      PreventUserExistenceErrors: 'ENABLED',
      ExplicitAuthFlows: Match.arrayWith(['ALLOW_USER_SRP_AUTH']),
    });
    for (const client of Object.values(prod.templates.auth.findResources('AWS::Cognito::UserPoolClient'))) {
      expect(client.Properties.GenerateSecret ?? false).toBe(false);
    }
  });
});

describe('ApiStack', () => {
  it('authorises every route with the Cognito JWT authorizer, under /api', () => {
    const routes = prod.templates.api.findResources('AWS::ApiGatewayV2::Route');
    expect(Object.keys(routes)).toHaveLength(2);
    for (const [logicalId, route] of Object.entries(routes)) {
      expect(route.Properties.AuthorizationType, `${logicalId} is unauthenticated`).toBe('JWT');
      expect(route.Properties.RouteKey).toMatch(/^ANY \/api/u);
    }
  });

  it('runs two functions on python3.14 arm64 with tracing and JSON logs', () => {
    const fns = prod.templates.api.findResources('AWS::Lambda::Function');
    expect(Object.keys(fns)).toHaveLength(2);
    for (const fn of Object.values(fns)) {
      expect(fn.Properties.Runtime).toBe('python3.14');
      expect(fn.Properties.Architectures).toEqual(['arm64']);
      expect(fn.Properties.TracingConfig).toEqual({ Mode: 'Active' });
      expect(fn.Properties.LoggingConfig.LogFormat).toBe('JSON');
      expect(fn.Properties.Environment.Variables).toMatchObject({
        AUTH_MODE: 'cognito', DATASET_STORE: 's3', JOB_RUNNER: 'sqs', APP_ENV: 'prod', AI_DAILY_LIMIT: '200',
      });
    }
    const handlers = Object.values(fns).map((fn) => fn.Properties.Handler).sort();
    expect(handlers).toEqual(['app.lambda_handler.handler', 'app.worker_handler.handler']);
    const names = Object.values(fns).map((fn) => fn.Properties.FunctionName).sort();
    expect(names).toEqual(['audit-intelligence-prod-api', 'audit-intelligence-prod-worker']);
  });

  it('keeps the API under the gateway timeout and gives the worker ten minutes', () => {
    const fns = Object.values(prod.templates.api.findResources('AWS::Lambda::Function'));
    const api = fns.find((fn) => fn.Properties.Handler === 'app.lambda_handler.handler');
    const worker = fns.find((fn) => fn.Properties.Handler === 'app.worker_handler.handler');
    expect(api?.Properties.Timeout).toBe(29);
    expect(worker?.Properties.Timeout).toBe(600);
    expect(worker?.Properties.MemorySize).toBe(2048);
  });

  it('feeds the worker from the jobs queue one job at a time, with a dead-letter queue', () => {
    prod.templates.api.hasResourceProperties('AWS::Lambda::EventSourceMapping', {
      BatchSize: 1,
      FunctionResponseTypes: ['ReportBatchItemFailures'],
      ScalingConfig: { MaximumConcurrency: 5 },
    });
    prod.templates.api.hasResourceProperties('AWS::SQS::Queue', {
      QueueName: 'audit-intelligence-prod-jobs',
      VisibilityTimeout: 720,
      RedrivePolicy: Match.objectLike({ maxReceiveCount: 2 }),
    });
  });

  it('never grants Scan, a managed policy, or bucket-wide S3 actions', () => {
    const policies = JSON.stringify(prod.templates.api.findResources('AWS::IAM::Policy'));
    expect(policies).not.toMatch(/dynamodb:Scan/u);
    expect(policies).not.toMatch(/s3:List/u);
    expect(policies).not.toMatch(/s3:GetBucket/u);
    expect(policies).not.toMatch(/"s3:\*"/u);
    expect(policies).toMatch(/\/index\/GSI1/u);
    for (const [logicalId, role] of Object.entries(prod.templates.api.findResources('AWS::IAM::Role'))) {
      expect(role.Properties.ManagedPolicyArns ?? [], `${logicalId} uses a managed policy`).toEqual([]);
    }
  });

  it('lets the API manage users but never delete them or set a password', () => {
    const api = policiesOf(prod, 'ApiFn');
    expect(api).toMatch(/cognito-idp:AdminCreateUser/u);
    expect(api).not.toMatch(/cognito-idp:AdminDeleteUser/u);
    expect(api).not.toMatch(/cognito-idp:AdminSetUserPassword/u);
    expect(api).not.toMatch(/"cognito-idp:\*"/u);
    expect(api).not.toMatch(/s3:DeleteObject/u);
  });

  it('lets only the worker erase a tenant: delete its accounts and its uploaded files', () => {
    const worker = policiesOf(prod, 'WorkerFn');
    expect(worker).toMatch(/cognito-idp:AdminDeleteUser/u);
    expect(worker).not.toMatch(/cognito-idp:AdminSetUserPassword/u);
    expect(worker).toMatch(/s3:DeleteObject/u);
    expect(worker).not.toMatch(/s3:DeleteObjectVersion/u);
    expect(worker).not.toMatch(/s3:DeleteBucket/u);
    // Erasure deletes by key; it never needs to list.
    expect(worker).not.toMatch(/s3:List/u);
  });

  it('throttles and logs the stage', () => {
    prod.templates.api.hasResourceProperties('AWS::ApiGatewayV2::Stage', {
      DefaultRouteSettings: Match.objectLike({ ThrottlingRateLimit: 50, ThrottlingBurstLimit: 100 }),
      AccessLogSettings: Match.objectLike({ DestinationArn: Match.anyValue() }),
    });
  });
});

describe('WebStack', () => {
  it('routes /api/* to the API with caching off and Authorization forwarded', () => {
    const config = Object.values(prod.templates.web.findResources('AWS::CloudFront::Distribution'))[0]?.Properties.DistributionConfig;
    const apiBehaviour = config.CacheBehaviors.find((b: { PathPattern: string }) => b.PathPattern === '/api/*');
    expect(apiBehaviour).toBeDefined();
    expect(apiBehaviour.CachePolicyId).toBe('4135ea2d-6df8-44a3-9df3-4b5a84be39ad'); // CachingDisabled
    expect(apiBehaviour.OriginRequestPolicyId).toBe('b689b0a8-53d0-40ab-baf2-68738e2966ac'); // AllViewerExceptHostHeader
    expect(apiBehaviour.FunctionAssociations ?? []).toEqual([]);
    expect(config.DefaultCacheBehavior.FunctionAssociations).toHaveLength(1);
    expect(config.CustomErrorResponses).toBeUndefined();
    expect(config.DefaultCacheBehavior.ViewerProtocolPolicy).toBe('redirect-to-https');
  });

  it('sends a content security policy that admits Cognito and the datasets bucket only', () => {
    const headers = JSON.stringify(prod.templates.web.findResources('AWS::CloudFront::ResponseHeadersPolicy'));
    expect(headers).toMatch(/frame-ancestors 'none'/u);
    expect(headers).toMatch(/StrictTransportSecurity/u);
    expect(headers).toMatch(/audit-intelligence-prod-datasets-123456789012\.s3\.eu-west-1\.amazonaws\.com/u);
  });

  it('ships runtime configuration beside the bundle', () => {
    prod.templates.web.resourceCountIs('Custom::CDKBucketDeployment', 1);
  });
});

describe('OpsStack', () => {
  it('rolls every alarm into one composite alarm that emails', () => {
    prod.templates.ops.resourceCountIs('AWS::CloudWatch::CompositeAlarm', 1);
    prod.templates.ops.hasResourceProperties('AWS::SNS::Subscription', { Protocol: 'email', Endpoint: 'ops@amanilabs.co.ke' });
    prod.templates.ops.resourceCountIs('AWS::CloudWatch::Dashboard', 1);
  });

  it('watches the dead-letter queue, both functions, the API and the table', () => {
    const descriptions = Object.values(prod.templates.api.findResources('AWS::CloudWatch::Alarm')).map(
      (a) => a.Properties.AlarmDescription as string,
    );
    expect(descriptions).toEqual(
      expect.arrayContaining([
        expect.stringMatching(/dead-letter/u),
        expect.stringMatching(/HTTP API is returning errors/u),
        expect.stringMatching(/worker .* returning errors/u),
        expect.stringMatching(/server errors/u),
        expect.stringMatching(/throttling/u),
      ]),
    );
  });
});

describe('tagging', () => {
  it('tags the table so cost can be attributed to this project and stage', () => {
    prod.templates.data.hasResourceProperties('AWS::DynamoDB::Table', {
      Tags: Match.arrayWith([
        { Key: 'Environment', Value: 'prod' },
        { Key: 'ManagedBy', Value: 'cdk' },
        { Key: 'Project', Value: 'AuditIntelligence' },
      ]),
    });
  });
});
