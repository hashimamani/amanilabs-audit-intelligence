import { Duration, Tags, type App, type Stack } from 'aws-cdk-lib';
import { commonTags, isProtectedStage, stackEnv, stackName, type DeployConfig } from './config.js';
import { ApiStack } from './stacks/api-stack.js';
import { AuthStack } from './stacks/auth-stack.js';
import { DataStack } from './stacks/data-stack.js';
import { OpsStack } from './stacks/ops-stack.js';
import { WebStack } from './stacks/web-stack.js';

export interface AppStacks {
  readonly data: DataStack;
  readonly auth: AuthStack;
  readonly api: ApiStack;
  readonly web: WebStack;
  readonly ops: OpsStack;
  readonly all: Stack[];
}

/**
 * Every stack the platform runs on, in dependency order, so `bin/app.ts` and
 * the tests synthesise exactly the same thing:
 *
 *   Data ─┐
 *   Auth ─┴─> Api ──> Web
 *               └──> Ops
 */
export function defineStacks(app: App, config: DeployConfig): AppStacks {
  const env = stackEnv(config);
  const terminationProtection = isProtectedStage(config.stage);

  const data = new DataStack(app, stackName(config, 'Data'), {
    env,
    config,
    terminationProtection,
    description: `Audit Intelligence durable state: table, datasets bucket, AI key (${config.stage})`,
  });
  const auth = new AuthStack(app, stackName(config, 'Auth'), {
    env,
    config,
    terminationProtection,
    description: `Audit Intelligence identity: Cognito user pool, role groups, web client (${config.stage})`,
  });
  const api = new ApiStack(app, stackName(config, 'Api'), {
    env,
    config,
    terminationProtection,
    description: `Audit Intelligence API, jobs queue and worker (${config.stage})`,
    table: data.table,
    datasetsBucket: data.datasetsBucket,
    anthropicApiKey: data.anthropicApiKey,
    userPool: auth.userPool,
    userPoolClient: auth.userPoolClient,
  });
  const web = new WebStack(app, stackName(config, 'Web'), {
    env,
    config,
    terminationProtection,
    description: `Audit Intelligence app: S3 behind CloudFront, fronting the API (${config.stage})`,
    apiEndpointHost: api.apiEndpointHost,
    accessLogsBucket: data.accessLogsBucket,
    userPoolId: auth.userPool.userPoolId,
    userPoolClientId: auth.userPoolClient.userPoolClientId,
  });
  const ops = new OpsStack(app, stackName(config, 'Ops'), {
    env,
    config,
    terminationProtection,
    description: `Audit Intelligence alarms and dashboard (${config.stage})`,
    alarms: api.alarms,
    apiRequests: api.httpApi.metricCount({ period: Duration.minutes(5), statistic: 'Sum' }),
    apiLatency: api.httpApi.metricLatency({ period: Duration.minutes(5), statistic: 'p99' }),
    apiServerErrors: api.httpApi.metricServerError({ period: Duration.minutes(5), statistic: 'Sum' }),
    functionDurations: api.functionDurations,
    queueDepth: api.jobsQueue.metricApproximateNumberOfMessagesVisible({ period: Duration.minutes(5), statistic: 'Maximum' }),
    tableReadCapacity: data.table.metricConsumedReadCapacityUnits({ period: Duration.minutes(5) }),
    tableWriteCapacity: data.table.metricConsumedWriteCapacityUnits({ period: Duration.minutes(5) }),
  });

  for (const [key, value] of Object.entries(commonTags(config))) {
    Tags.of(app).add(key, value);
  }

  return { data, auth, api, web, ops, all: [data, auth, api, web, ops] };
}
