import { Tags, type App, type Stack } from 'aws-cdk-lib';
import { commonTags, type DeployConfig } from './config.js';

/**
 * Every stack the platform runs on, in dependency order, so `bin/app.ts` and
 * the tests synthesise exactly the same thing.
 *
 * Phase 0 ships the toolchain only. Phase 2 adds, in this order:
 * Data (DynamoDB, S3, KMS) → Auth (Cognito) → Api (HTTP API, Lambda, SQS
 * worker) → Web (S3 + CloudFront fronting /api) → Ops (alarms, dashboard).
 */
export function defineStacks(app: App, config: DeployConfig): Stack[] {
  const stacks: Stack[] = [];

  for (const [key, value] of Object.entries(commonTags(config))) {
    Tags.of(app).add(key, value);
  }

  return stacks;
}
