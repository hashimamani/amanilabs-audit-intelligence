import { existsSync, mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { App, Stack, Validations } from 'aws-cdk-lib';
import { Bucket } from 'aws-cdk-lib/aws-s3';
import { AwsSolutionsChecks } from 'cdk-nag';
import { afterEach, describe, expect, it } from 'vitest';
import { defineStacks } from '../lib/app.js';
import { testConfig } from './helpers.js';

/**
 * cdk-nag reports nothing when an app is compliant, so a silently disabled
 * pack is indistinguishable from a clean app. The first test plants a known
 * violation and asserts it is caught; without it the rest of this file would
 * pass just as happily with no pack registered at all.
 */

const tempDirs: string[] = [];

function freshOutdir(): string {
  const dir = mkdtempSync(join(tmpdir(), 'audit-intelligence-nag-'));
  tempDirs.push(dir);
  return dir;
}

afterEach(() => {
  for (const dir of tempDirs.splice(0)) {
    rmSync(dir, { recursive: true, force: true });
  }
});

interface ValidationReport {
  readonly pluginReports: {
    readonly violations: { readonly ruleName: string; readonly violatingResources?: { readonly resourceLogicalId: string }[] }[];
  }[];
}

function violationsIn(outdir: string): string[] {
  const file = join(outdir, 'validation-report.json');
  if (!existsSync(file)) return [];
  const report = JSON.parse(readFileSync(file, 'utf8')) as ValidationReport;
  return report.pluginReports.flatMap((plugin) =>
    plugin.violations.map((v) => `${v.ruleName}: ${(v.violatingResources ?? []).map((r) => r.resourceLogicalId).join(', ')}`),
  );
}

describe('cdk-nag enforcement', () => {
  it('fails synthesis on a known violation, proving the pack is active', () => {
    const outdir = freshOutdir();
    const app = new App({ outdir });
    Validations.of(app).addPlugins(new AwsSolutionsChecks(app));

    const stack = new Stack(app, 'NagProbe', { env: { account: '123456789012', region: 'eu-west-1' } });
    // A default bucket has no server access logs and no SSL-only bucket policy.
    new Bucket(stack, 'NonCompliantBucket');

    expect(() => app.synth()).toThrow();
    const rules = violationsIn(outdir).join('\n');
    expect(rules).toContain('AwsSolutions-S1');
    expect(rules).toContain('AwsSolutions-S10');
  });

  for (const stage of ['dev', 'prod'] as const) {
    it(`passes on every ${stage} stack, with only the acknowledgements in the source`, () => {
      const outdir = freshOutdir();
      const app = new App({ outdir, context: { 'aws:cdk:bundling-stacks': [] } });
      Validations.of(app).addPlugins(new AwsSolutionsChecks(app));
      defineStacks(app, testConfig(stage));

      let error: unknown;
      try {
        app.synth();
      } catch (e) {
        error = e;
      }
      expect(violationsIn(outdir)).toEqual([]);
      expect(error).toBeUndefined();
    });
  }
});
