import { CfnOutput, Duration, RemovalPolicy, Stack, Validations, type StackProps } from 'aws-cdk-lib';
import { type CfnStage, HttpApi, HttpMethod } from 'aws-cdk-lib/aws-apigatewayv2';
import { HttpJwtAuthorizer } from 'aws-cdk-lib/aws-apigatewayv2-authorizers';
import { HttpLambdaIntegration } from 'aws-cdk-lib/aws-apigatewayv2-integrations';
import { Alarm, ComparisonOperator, type IMetric, type Metric, TreatMissingData } from 'aws-cdk-lib/aws-cloudwatch';
import type { UserPool, UserPoolClient } from 'aws-cdk-lib/aws-cognito';
import { Operation, type Table } from 'aws-cdk-lib/aws-dynamodb';
import { Effect, PolicyStatement, type IGrantable } from 'aws-cdk-lib/aws-iam';
import { SqsEventSource } from 'aws-cdk-lib/aws-lambda-event-sources';
import { LogGroup, type RetentionDays } from 'aws-cdk-lib/aws-logs';
import type { Bucket } from 'aws-cdk-lib/aws-s3';
import type { Secret } from 'aws-cdk-lib/aws-secretsmanager';
import { Queue, QueueEncryption } from 'aws-cdk-lib/aws-sqs';
import type { Construct } from 'constructs';
import { API_BASE_PATH, datasetsBucketName, isProtectedStage, resourceName, type DeployConfig } from '../config.js';
import { PythonFunction } from '../constructs/python-function.js';

export interface ApiStackProps extends StackProps {
  readonly config: DeployConfig;
  readonly table: Table;
  readonly datasetsBucket: Bucket;
  readonly anthropicApiKey: Secret;
  readonly userPool: UserPool;
  readonly userPoolClient: UserPoolClient;
}

/** Only this prefix of the datasets bucket is ever touched; see backend core/datasets.py. */
const DATASETS_PREFIX = 'tenants/';

/** The worker runs the rule engine and AI jobs; nothing the API does takes longer than a gateway allows. */
const WORKER_TIMEOUT = Duration.minutes(10);
const WORKER_MAX_CONCURRENCY = 5;

const TABLE_READ = ['dynamodb:GetItem', 'dynamodb:BatchGetItem', 'dynamodb:Query', 'dynamodb:ConditionCheckItem', 'dynamodb:DescribeTable'];
const TABLE_WRITE = ['dynamodb:PutItem', 'dynamodb:UpdateItem', 'dynamodb:DeleteItem', 'dynamodb:BatchWriteItem'];

/**
 * Explicit grants naming the one index, instead of `grantReadWriteData`,
 * which would grant `table/index/*`. `Scan` is deliberately absent: no code
 * path may read the whole table.
 */
function grantTable(grantee: IGrantable, table: Table): void {
  grantee.grantPrincipal.addToPrincipalPolicy(
    new PolicyStatement({ effect: Effect.ALLOW, actions: TABLE_READ, resources: [table.tableArn, `${table.tableArn}/index/GSI1`] }),
  );
  grantee.grantPrincipal.addToPrincipalPolicy(
    new PolicyStatement({ effect: Effect.ALLOW, actions: TABLE_WRITE, resources: [table.tableArn] }),
  );
}

export class ApiStack extends Stack {
  readonly httpApi: HttpApi;
  readonly apiEndpointHost: string;
  readonly alarms: Alarm[] = [];
  readonly functionDurations: Metric[] = [];
  readonly jobsQueue: Queue;
  readonly jobsDlq: Queue;

  constructor(scope: Construct, id: string, props: ApiStackProps) {
    super(scope, id, props);
    const { config, table, datasetsBucket, anthropicApiKey, userPool, userPoolClient } = props;
    const protectedStage = isProtectedStage(config.stage);

    // --- the jobs queue -----------------------------------------------------

    this.jobsDlq = new Queue(this, 'JobsDlq', {
      queueName: resourceName(config, 'jobs-dlq'),
      encryption: QueueEncryption.SQS_MANAGED,
      enforceSSL: true,
      retentionPeriod: Duration.days(14),
    });
    Validations.of(this.jobsDlq).acknowledge({
      id: 'AwsSolutions-SQS3',
      reason: 'This is the dead-letter queue; a dead-letter queue for it would not have a consumer either.',
    });

    this.jobsQueue = new Queue(this, 'JobsQueue', {
      queueName: resourceName(config, 'jobs'),
      encryption: QueueEncryption.SQS_MANAGED,
      enforceSSL: true,
      // Must exceed the worker's timeout, or a slow job is delivered twice at once.
      visibilityTimeout: Duration.minutes(12),
      retentionPeriod: Duration.days(4),
      deadLetterQueue: { queue: this.jobsDlq, maxReceiveCount: 2 },
    });

    // --- the functions -------------------------------------------------------

    const sharedEnvironment = {
      TABLE_NAME: table.tableName,
      AUTH_MODE: 'cognito',
      COGNITO_USER_POOL_ID: userPool.userPoolId,
      COGNITO_CLIENT_ID: userPoolClient.userPoolClientId,
      DATASET_STORE: 's3',
      DATASETS_BUCKET: datasetsBucket.bucketName,
      DEMO_DATASET_DIR: '/var/task/synthetic_sacco_data',
      JOB_RUNNER: 'sqs',
      JOBS_QUEUE_URL: this.jobsQueue.queueUrl,
      ANTHROPIC_API_KEY_SECRET_ARN: anthropicApiKey.secretArn,
      AI_DAILY_LIMIT: String(config.aiDailyLimit),
    };

    const api = new PythonFunction(this, 'ApiFn', {
      config,
      functionName: resourceName(config, 'api'),
      handler: 'app.lambda_handler.handler',
      description: 'Audit Intelligence HTTP API',
      // Just under the gateway's 30 s ceiling; anything longer is a job.
      timeout: Duration.seconds(29),
      memorySize: 1024,
      environment: sharedEnvironment,
    });

    const worker = new PythonFunction(this, 'WorkerFn', {
      config,
      functionName: resourceName(config, 'worker'),
      handler: 'app.worker_handler.handler',
      description: 'Audit Intelligence jobs worker (rule engine, chart analytics, board reports)',
      timeout: WORKER_TIMEOUT,
      // The rule engine holds a year of transactions in pandas; CPU scales with memory.
      memorySize: 2048,
      environment: sharedEnvironment,
    });
    worker.fn.addEventSource(
      new SqsEventSource(this.jobsQueue, {
        batchSize: 1,
        maxConcurrency: WORKER_MAX_CONCURRENCY,
        reportBatchItemFailures: true,
      }),
    );

    for (const fn of [api.fn, worker.fn]) {
      grantTable(fn, table);
      anthropicApiKey.grantRead(fn);
    }
    this.jobsQueue.grantSendMessages(api.fn);

    /**
     * Object actions under one prefix. Deliberately not `grantReadWrite`,
     * which hands out s3:List*, s3:GetBucket* and s3:DeleteObjectVersion
     * across the bucket. The API presigns PUTs (so it needs PutObject) and
     * reads headers to validate; the worker reads datasets to analyse them
     * and deletes them when a tenant is erased - by key, never by listing.
     */
    const datasetObjects = `arn:aws:s3:::${datasetsBucketName(config)}/${DATASETS_PREFIX}*`;
    api.fn.addToRolePolicy(
      new PolicyStatement({ effect: Effect.ALLOW, actions: ['s3:PutObject', 's3:GetObject'], resources: [datasetObjects] }),
    );
    worker.fn.addToRolePolicy(
      new PolicyStatement({ effect: Effect.ALLOW, actions: ['s3:GetObject', 's3:DeleteObject'], resources: [datasetObjects] }),
    );
    for (const fn of [api, worker]) {
      Validations.of(fn.fn.role!).acknowledge({
        id: `AwsSolutions-IAM5[Resource::${datasetObjects}]`,
        reason:
          'Dataset objects cannot be enumerated in advance, so a prefix wildcard is the ' +
          'narrowest an object policy can be. Confined to the tenants/ prefix of one bucket, ' +
          'object actions only, no listing.',
      });
    }

    /**
     * Exactly what user management performs, from the API. Absent on purpose:
     * AdminDeleteUser (from the app, accounts are disabled, never deleted) and
     * AdminSetUserPassword (no password ever passes through code).
     */
    const userManagement = [
      'cognito-idp:AdminCreateUser',
      'cognito-idp:AdminGetUser',
      'cognito-idp:AdminAddUserToGroup',
      'cognito-idp:AdminRemoveUserFromGroup',
      'cognito-idp:AdminEnableUser',
      'cognito-idp:AdminDisableUser',
      'cognito-idp:AdminUserGlobalSignOut',
    ];
    api.fn.addToRolePolicy(new PolicyStatement({ effect: Effect.ALLOW, actions: userManagement, resources: [userPool.userPoolArn] }));
    /**
     * The worker provisions tenants (create-tenant workflow) and erases them
     * (delete-tenant workflow, the right-to-erasure path), so it alone may
     * delete accounts. Nothing reachable from an HTTP request can.
     */
    worker.fn.addToRolePolicy(
      new PolicyStatement({
        effect: Effect.ALLOW,
        actions: [...userManagement, 'cognito-idp:AdminDeleteUser'],
        resources: [userPool.userPoolArn],
      }),
    );

    // --- the HTTP API ----------------------------------------------------------

    const accessLogs = new LogGroup(this, 'ApiAccessLogs', {
      retention: config.logRetentionDays as RetentionDays,
      removalPolicy: protectedStage ? RemovalPolicy.RETAIN : RemovalPolicy.DESTROY,
    });

    const authorizer = new HttpJwtAuthorizer(
      'CognitoAuthorizer',
      `https://cognito-idp.${this.region}.amazonaws.com/${userPool.userPoolId}`,
      {
        // The ID token's `aud` is the client id; it is the token the app sends.
        jwtAudience: [userPoolClient.userPoolClientId],
        identitySource: ['$request.header.Authorization'],
      },
    );

    this.httpApi = new HttpApi(this, 'Api', {
      apiName: resourceName(config, 'api'),
      description: 'Audit Intelligence API',
      defaultAuthorizer: authorizer,
      createDefaultStage: true,
      // No CORS: the app reaches this API same-origin through CloudFront.
    });

    const stage = this.httpApi.defaultStage?.node.defaultChild as CfnStage;
    stage.defaultRouteSettings = {
      throttlingRateLimit: protectedStage ? 50 : 20,
      throttlingBurstLimit: protectedStage ? 100 : 40,
      detailedMetricsEnabled: true,
    };
    stage.accessLogSettings = {
      destinationArn: accessLogs.logGroupArn,
      // No bodies or query strings: those can carry member names.
      format: JSON.stringify({
        requestId: '$context.requestId',
        ip: '$context.identity.sourceIp',
        requestTime: '$context.requestTime',
        routeKey: '$context.routeKey',
        path: '$context.path',
        status: '$context.status',
        responseLength: '$context.responseLength',
        integrationErrorMessage: '$context.integrationErrorMessage',
        userSub: '$context.authorizer.claims.sub',
      }),
    };

    const integration = new HttpLambdaIntegration('ApiIntegration', api.fn);
    this.httpApi.addRoutes({ path: API_BASE_PATH, methods: [HttpMethod.ANY], integration });
    this.httpApi.addRoutes({ path: `${API_BASE_PATH}/{proxy+}`, methods: [HttpMethod.ANY], integration });

    // `apiEndpoint` includes the scheme, which a CloudFront origin must not.
    this.apiEndpointHost = `${this.httpApi.apiId}.execute-api.${this.region}.${this.urlSuffix}`;

    // --- alarms ----------------------------------------------------------------

    const alarm = (id: string, description: string, metric: IMetric, threshold: number, evaluationPeriods = 1) =>
      new Alarm(this, id, {
        alarmDescription: description,
        metric,
        threshold,
        evaluationPeriods,
        comparisonOperator: ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
        treatMissingData: TreatMissingData.NOT_BREACHING,
      });

    this.alarms.push(
      api.errorAlarm,
      worker.errorAlarm,
      alarm('Api5xxAlarm', 'The API is returning server errors', this.httpApi.metricServerError({ period: Duration.minutes(5), statistic: 'Sum' }), 1),
      alarm('ApiLatencyAlarm', 'The API is slow enough that the app feels broken', this.httpApi.metricLatency({ period: Duration.minutes(5), statistic: 'p99' }), Duration.seconds(5).toMilliseconds(), 3),
      alarm('JobsDlqAlarm', 'A job failed twice and is parked in the dead-letter queue', this.jobsDlq.metricApproximateNumberOfMessagesVisible({ period: Duration.minutes(5), statistic: 'Maximum' }), 1),
      alarm(
        'TableThrottleAlarm',
        'DynamoDB is throttling requests',
        table.metricThrottledRequestsForOperations({
          operations: [Operation.GET_ITEM, Operation.PUT_ITEM, Operation.UPDATE_ITEM, Operation.QUERY, Operation.BATCH_WRITE_ITEM],
          period: Duration.minutes(5),
        }),
        1,
      ),
    );
    this.functionDurations.push(
      api.fn.metricDuration({ period: Duration.minutes(5), statistic: 'p99', label: 'API' }),
      worker.fn.metricDuration({ period: Duration.minutes(5), statistic: 'p99', label: 'Worker' }),
    );

    new CfnOutput(this, 'ApiEndpoint', { value: this.httpApi.apiEndpoint });
    new CfnOutput(this, 'JobsQueueUrl', { value: this.jobsQueue.queueUrl });
  }
}
