import { App, Validations } from 'aws-cdk-lib';
import { Template } from 'aws-cdk-lib/assertions';
import { AwsSolutionsChecks } from 'cdk-nag';
import { defineStacks, type AppStacks } from '../lib/app.js';
import { parseDeployConfig, type DeployConfig, type Stage } from '../lib/config.js';

export function testConfig(stage: Stage, overrides: Record<string, unknown> = {}): DeployConfig {
  return parseDeployConfig({
    stage,
    account: '123456789012',
    alarmEmail: 'ops@amanilabs.co.ke',
    requireMfa: stage === 'prod',
    ...overrides,
  });
}

export interface Synthesised extends AppStacks {
  readonly app: App;
  readonly templates: Record<'data' | 'auth' | 'api' | 'web' | 'ops', Template>;
}

/**
 * Bundling the Lambda asset runs pip inside Docker and takes minutes; the
 * templates under test do not depend on the bundle's contents, so it is
 * skipped here and exercised by `cdk synth` in CI.
 */
export function buildApp(stage: Stage, outdir?: string, nag = true): Synthesised {
  const app = new App({
    ...(outdir !== undefined && { outdir }),
    context: { 'aws:cdk:bundling-stacks': [] },
  });
  if (nag) Validations.of(app).addPlugins(new AwsSolutionsChecks(app));
  const stacks = defineStacks(app, testConfig(stage));
  return {
    ...stacks,
    app,
    templates: {
      data: Template.fromStack(stacks.data),
      auth: Template.fromStack(stacks.auth),
      api: Template.fromStack(stacks.api),
      web: Template.fromStack(stacks.web),
      ops: Template.fromStack(stacks.ops),
    },
  };
}
