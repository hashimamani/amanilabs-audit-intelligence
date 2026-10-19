/**
 * Synthesises a stage under cdk-nag and lets CDK print every finding with
 * its construct path, which the vitest assertion cannot show.
 * `npx tsx scripts/nag-report.ts prod`
 */
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { App, Validations } from 'aws-cdk-lib';
import { AwsSolutionsChecks } from 'cdk-nag';
import { defineStacks } from '../lib/app.js';
import { resolveStage } from '../lib/config.js';
import { testConfig } from '../test/helpers.js';

const app = new App({
  outdir: mkdtempSync(join(tmpdir(), 'audit-intelligence-nag-')),
  context: { 'aws:cdk:bundling-stacks': [] },
});
Validations.of(app).addPlugins(new AwsSolutionsChecks(app));
defineStacks(app, testConfig(resolveStage(process.argv[2])));
app.synth();
console.log('clean');
