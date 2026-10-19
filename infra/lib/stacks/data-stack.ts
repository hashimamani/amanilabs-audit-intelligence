import { CfnOutput, Duration, RemovalPolicy, SecretValue, Stack, Validations, type StackProps } from 'aws-cdk-lib';
import { AttributeType, BillingMode, ProjectionType, Table, TableEncryption } from 'aws-cdk-lib/aws-dynamodb';
import { BlockPublicAccess, Bucket, BucketEncryption, HttpMethods, ObjectOwnership } from 'aws-cdk-lib/aws-s3';
import { Secret } from 'aws-cdk-lib/aws-secretsmanager';
import type { Construct } from 'constructs';
import { datasetsBucketName, isProtectedStage, resourceName, type DeployConfig } from '../config.js';

export interface DataStackProps extends StackProps {
  readonly config: DeployConfig;
}

/**
 * The attributes GSI1 carries. Listing a run's cases reads only these, never
 * the flag/evidence blobs. Must match GSI1_PROJECTED in
 * audit_intelligence/backend/app/db/table.py - infra/test asserts it does.
 */
export const GSI1_PROJECTED = [
  'case_ref', 'run_id', 'subject_type', 'subject_id', 'subject_name', 'risk_score',
  'severity', 'status', 'triggered_rules', 'flag_count', 'created_at', 'updated_at',
  'user_id', 'email', 'name', 'role', 'is_active', 'password_hash', 'tenant_slug',
];

/** Everything durable: the table, the uploaded datasets, and the AI key. */
export class DataStack extends Stack {
  readonly table: Table;
  readonly datasetsBucket: Bucket;
  readonly accessLogsBucket: Bucket;
  readonly anthropicApiKey: Secret;

  constructor(scope: Construct, id: string, props: DataStackProps) {
    super(scope, id, props);
    const { config } = props;
    const protectedStage = isProtectedStage(config.stage);
    const removalPolicy = protectedStage ? RemovalPolicy.RETAIN : RemovalPolicy.DESTROY;

    this.accessLogsBucket = new Bucket(this, 'AccessLogsBucket', {
      encryption: BucketEncryption.S3_MANAGED,
      blockPublicAccess: BlockPublicAccess.BLOCK_ALL,
      enforceSSL: true,
      objectOwnership: ObjectOwnership.BUCKET_OWNER_PREFERRED,
      removalPolicy,
      autoDeleteObjects: !protectedStage,
      lifecycleRules: [{ id: 'expire-logs', expiration: Duration.days(90) }],
    });

    /**
     * Single table; key layout documented in backend app/db/table.py. On-demand
     * billing: nothing is consumed when nobody is auditing.
     */
    this.table = new Table(this, 'Table', {
      tableName: resourceName(config, 'main'),
      partitionKey: { name: 'PK', type: AttributeType.STRING },
      sortKey: { name: 'SK', type: AttributeType.STRING },
      billingMode: BillingMode.PAY_PER_REQUEST,
      encryption: TableEncryption.AWS_MANAGED,
      pointInTimeRecoverySpecification: { pointInTimeRecoveryEnabled: protectedStage },
      removalPolicy,
      deletionProtection: protectedStage,
    });
    if (!protectedStage) {
      Validations.of(this.table).acknowledge({
        id: 'AwsSolutions-DDB3',
        reason: 'Point-in-time recovery is on in prod. Dev holds the demo dataset and test tenants, rebuilt at will.',
      });
    }
    this.table.addGlobalSecondaryIndex({
      indexName: 'GSI1',
      partitionKey: { name: 'GSI1PK', type: AttributeType.STRING },
      sortKey: { name: 'GSI1SK', type: AttributeType.STRING },
      projectionType: ProjectionType.INCLUDE,
      nonKeyAttributes: GSI1_PROJECTED,
    });

    /**
     * A SACCO's exported CSVs. Written only through presigned PUTs the API
     * hands out, read only by the worker, and deleted after
     * datasetRetentionDays - the cases built from them are what the auditors
     * keep, the raw member data is not.
     */
    this.datasetsBucket = new Bucket(this, 'DatasetsBucket', {
      bucketName: datasetsBucketName(config),
      encryption: BucketEncryption.S3_MANAGED,
      blockPublicAccess: BlockPublicAccess.BLOCK_ALL,
      enforceSSL: true,
      removalPolicy,
      autoDeleteObjects: !protectedStage,
      serverAccessLogsBucket: this.accessLogsBucket,
      serverAccessLogsPrefix: 'datasets/',
      cors: [
        {
          // The signed URL is the authorisation; CORS only lets the browser make the request.
          allowedMethods: [HttpMethods.PUT],
          allowedOrigins: ['*'],
          allowedHeaders: ['*'],
          exposedHeaders: ['ETag'],
          maxAge: 3000,
        },
      ],
      lifecycleRules: [
        { id: 'abort-incomplete-uploads', abortIncompleteMultipartUploadAfter: Duration.days(7) },
        { id: 'expire-raw-uploads', prefix: 'tenants/', expiration: Duration.days(config.datasetRetentionDays) },
      ],
    });

    /**
     * Created holding the literal value "unset", which the backend treats as
     * "AI features are not configured" (a clean 503, nothing else affected).
     * The real key is put in by hand after the first deploy - see
     * docs/DEPLOYING.md - and never passes through this repository.
     */
    this.anthropicApiKey = new Secret(this, 'AnthropicApiKey', {
      secretName: resourceName(config, 'anthropic-api-key'),
      description: 'Anthropic API key for case Q&A, chart analytics and board reports',
      secretStringValue: SecretValue.unsafePlainText('unset'),
      removalPolicy,
    });
    Validations.of(this.anthropicApiKey).acknowledge({
      id: 'AwsSolutions-SMG4',
      reason:
        'The key is issued by Anthropic from their console; only they can rotate it, so ' +
        'automatic rotation has nothing to rotate to. Replacement is a documented manual step.',
    });

    new CfnOutput(this, 'TableName', { value: this.table.tableName });
    new CfnOutput(this, 'DatasetsBucketName', { value: this.datasetsBucket.bucketName });
    new CfnOutput(this, 'AnthropicApiKeySecretName', { value: this.anthropicApiKey.secretName });
  }
}
