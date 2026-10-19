import { cpSync, existsSync, mkdirSync, rmSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { Duration, RemovalPolicy, Stack, Validations, type CfnResource } from 'aws-cdk-lib';
import { Alarm, ComparisonOperator, TreatMissingData } from 'aws-cdk-lib/aws-cloudwatch';
import { Effect, PolicyStatement, Role, ServicePrincipal } from 'aws-cdk-lib/aws-iam';
import { Architecture, Code, Function as LambdaFunction, LoggingFormat, Runtime, Tracing } from 'aws-cdk-lib/aws-lambda';
import { LogGroup, type RetentionDays } from 'aws-cdk-lib/aws-logs';
import { Construct } from 'constructs';
import type { DeployConfig } from '../config.js';

const repoRoot = join(dirname(fileURLToPath(import.meta.url)), '..', '..', '..');
const stagingDir = join(repoRoot, 'infra', '.lambda-src');

/** The runtime both functions target; `.python-version` and the Dockerfile match it. */
export const LAMBDA_RUNTIME = Runtime.PYTHON_3_14;

/**
 * Every manylinux tag a wheel may carry and still run on Lambda's Amazon
 * Linux 2023 (glibc 2.34). pip does not widen a single `--platform` to the
 * tags beneath it reliably - numpy ships `manylinux_2_28`, cffi ships
 * `manylinux2014`, and asking for either alone refuses the other.
 */
const LAMBDA_PLATFORMS = [
  'manylinux2014_aarch64',
  'manylinux_2_17_aarch64',
  'manylinux_2_24_aarch64',
  'manylinux_2_27_aarch64',
  'manylinux_2_28_aarch64',
  'manylinux_2_31_aarch64',
  'manylinux_2_34_aarch64',
];

let staged = false;

/**
 * The backend as one Lambda asset, shared by the API and the worker.
 *
 * The source is copied into a staging directory first so the asset holds
 * exactly three things - requirements.txt, the app package and the demo
 * dataset - rather than the repository root with an exclude list that would
 * have to be kept in step with everything else that lives there. The ground
 * truth files (the founder's private answer key for the demo) are deliberately
 * left out of anything that gets deployed.
 *
 * Wheels are resolved for the Lambda platform explicitly, so the bundle is the
 * same whether synth runs on an Apple-silicon laptop or an x86 CI runner, and
 * a package without an aarch64 wheel fails the build instead of the function.
 */
export function backendCode(): Code {
  if (!staged) {
    rmSync(stagingDir, { recursive: true, force: true });
    mkdirSync(stagingDir, { recursive: true });
    cpSync(join(repoRoot, 'requirements.txt'), join(stagingDir, 'requirements.txt'));
    cpSync(join(repoRoot, 'audit_intelligence', 'backend', 'app'), join(stagingDir, 'app'), {
      recursive: true,
      filter: (src) => !src.includes('__pycache__'),
    });
    cpSync(join(repoRoot, 'synthetic_sacco_data'), join(stagingDir, 'synthetic_sacco_data'), {
      recursive: true,
      filter: (src) => !src.includes('ground_truth'),
    });
    staged = true;
  }
  if (!existsSync(join(stagingDir, 'requirements.txt'))) {
    throw new Error(`Lambda staging directory is incomplete: ${stagingDir}`);
  }
  return Code.fromAsset(stagingDir, {
    bundling: {
      image: LAMBDA_RUNTIME.bundlingImage,
      command: [
        'bash',
        '-c',
        [
          `pip install --no-cache-dir --quiet ${LAMBDA_PLATFORMS.map((p) => `--platform ${p}`).join(' ')} ` +
            '--implementation cp --python-version 3.14 --only-binary=:all: --target /asset-output -r requirements.txt',
          'cp -r app synthetic_sacco_data /asset-output/',
          'find /asset-output -type d -name __pycache__ -prune -exec rm -rf {} +',
        ].join(' && '),
      ],
    },
  });
}

export interface PythonFunctionProps {
  readonly config: DeployConfig;
  /** Fixed, so an operator workflow can invoke it by name. */
  readonly functionName: string;
  readonly handler: string;
  readonly description: string;
  readonly environment: Record<string, string>;
  readonly timeout: Duration;
  readonly memorySize: number;
}

/**
 * One Lambda with the platform's defaults: its own execution role scoped to
 * its own log group (not the AWS-managed basic execution policy, which can
 * write to every log group in the account), ARM64, JSON logs, X-Ray, and an
 * error alarm so a new function cannot be added without one.
 */
export class PythonFunction extends Construct {
  readonly fn: LambdaFunction;
  readonly errorAlarm: Alarm;

  constructor(scope: Construct, id: string, props: PythonFunctionProps) {
    super(scope, id);
    const { config } = props;

    const logGroup = new LogGroup(this, 'Logs', {
      retention: config.logRetentionDays as RetentionDays,
      removalPolicy: RemovalPolicy.DESTROY,
    });

    const role = new Role(this, 'Role', {
      assumedBy: new ServicePrincipal('lambda.amazonaws.com'),
      description: `Execution role for ${props.description}`,
    });
    role.addToPrincipalPolicy(
      new PolicyStatement({
        effect: Effect.ALLOW,
        actions: ['logs:CreateLogStream', 'logs:PutLogEvents'],
        resources: [logGroup.logGroupArn, `${logGroup.logGroupArn}:log-stream:*`],
      }),
    );
    const logGroupLogicalId = Stack.of(this).getLogicalId(logGroup.node.defaultChild as CfnResource);
    Validations.of(role).acknowledge({
      id: `AwsSolutions-IAM5[Resource::<${logGroupLogicalId}.Arn>:log-stream:*]`,
      reason:
        'Log-stream names are generated per execution environment, so the stream segment ' +
        "must be a wildcard. It is scoped to this function's own log group.",
    });
    role.addToPrincipalPolicy(
      new PolicyStatement({
        effect: Effect.ALLOW,
        actions: ['xray:PutTraceSegments', 'xray:PutTelemetryRecords'],
        resources: ['*'],
      }),
    );
    Validations.of(role).acknowledge({
      id: 'AwsSolutions-IAM5[Resource::*]',
      reason:
        'xray:PutTraceSegments and xray:PutTelemetryRecords are account-scoped APIs that take ' +
        'no resource ARN, so a wildcard is the only expressible form. They grant no access to data.',
    });

    this.fn = new LambdaFunction(this, 'Fn', {
      functionName: props.functionName,
      role,
      runtime: LAMBDA_RUNTIME,
      architecture: Architecture.ARM_64,
      code: backendCode(),
      handler: props.handler,
      description: props.description,
      timeout: props.timeout,
      memorySize: props.memorySize,
      logGroup,
      loggingFormat: LoggingFormat.JSON,
      tracing: Tracing.ACTIVE,
      environment: {
        APP_ENV: config.stage,
        POWERTOOLS_SERVICE_NAME: 'audit-intelligence',
        POWERTOOLS_LOG_LEVEL: config.stage === 'prod' ? 'INFO' : 'DEBUG',
        ...props.environment,
      },
    });

    this.errorAlarm = new Alarm(this, 'ErrorAlarm', {
      alarmDescription: `${props.description} is returning errors`,
      metric: this.fn.metricErrors({ period: Duration.minutes(5), statistic: 'Sum' }),
      threshold: 1,
      evaluationPeriods: 1,
      comparisonOperator: ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
      // No invocations is the normal state outside office hours.
      treatMissingData: TreatMissingData.NOT_BREACHING,
    });
  }
}
