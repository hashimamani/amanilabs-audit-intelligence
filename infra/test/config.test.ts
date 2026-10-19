import { describe, expect, it } from 'vitest';
import {
  isProtectedStage,
  loadDeployConfig,
  parseDeployConfig,
  resolveStage,
  resourceName,
  stackName,
} from '../lib/config.js';

describe('resolveStage', () => {
  it('defaults to dev, so a careless deploy cannot reach production', () => {
    expect(resolveStage(undefined)).toBe('dev');
    expect(resolveStage(null)).toBe('dev');
    expect(resolveStage('')).toBe('dev');
  });

  it('accepts the two known stages', () => {
    expect(resolveStage('dev')).toBe('dev');
    expect(resolveStage('prod')).toBe('prod');
  });

  it('rejects an unknown or near-miss stage with a message naming the fix', () => {
    for (const value of ['staging', 'production', 'DEV']) {
      expect(() => resolveStage(value)).toThrow(/Unknown stage/u);
      expect(() => resolveStage(value)).toThrow(/stage=prod/u);
    }
  });
});

describe('loadDeployConfig', () => {
  it('loads and validates the committed dev configuration', () => {
    const config = loadDeployConfig('dev');
    expect(config.stage).toBe('dev');
    expect(config.region).toBe('eu-west-1');
    // The alarm topic emails a confirmation that has to be clicked; a
    // placeholder domain breaks that without any error.
    expect(config.alarmEmail).not.toMatch(/example\.(com|co\.ke|org)$/u);
  });

  it('loads the committed prod configuration, which requires MFA and keeps logs longer', () => {
    const prod = loadDeployConfig('prod');
    const dev = loadDeployConfig('dev');
    expect(prod.stage).toBe('prod');
    expect(prod.requireMfa).toBe(true);
    expect(prod.logRetentionDays).toBeGreaterThanOrEqual(dev.logRetentionDays);
    // One AmaniLabs account hosts every stage of every product.
    expect(prod.account).toBe(dev.account);
    expect(prod.region).toBe(dev.region);
  });

  it('points at the docs when a stage has no configuration', () => {
    const missing = 'staging' as Parameters<typeof loadDeployConfig>[0];
    expect(() => loadDeployConfig(missing)).toThrow(/No deploy configuration for stage "staging"/u);
    expect(() => loadDeployConfig(missing)).toThrow(/DEPLOYING\.md/u);
  });

  it('takes the stage from the file path, so the file body cannot contradict it', () => {
    expect(loadDeployConfig('dev', { stage: 'prod' }).stage).toBe('dev');
  });

  it('rejects an override that breaks the schema', () => {
    expect(() => loadDeployConfig('dev', { region: 'Ireland' })).toThrow(/Invalid deploy configuration/u);
    expect(() => loadDeployConfig('dev', { surprise: true })).toThrow(/Invalid deploy configuration/u);
  });
});

describe('parseDeployConfig', () => {
  const minimal = { stage: 'dev', account: '123456789012', alarmEmail: 'ops@amanilabs.co.ke' };

  it('fills every optional setting so a minimal config is deployable', () => {
    const config = parseDeployConfig(minimal);
    expect(config.region).toBe('eu-west-1');
    expect(config.logRetentionDays).toBe(30);
    expect(config.requireMfa).toBe(false);
    expect(config.datasetRetentionDays).toBe(30);
  });

  it('requires every stage to pin the account id', () => {
    expect(() => parseDeployConfig({ stage: 'dev', alarmEmail: 'ops@amanilabs.co.ke' })).toThrow(/account/u);
    expect(() => parseDeployConfig({ ...minimal, account: '1234' })).toThrow(/12-digit/u);
  });

  it('refuses a log retention CloudWatch does not offer', () => {
    expect(() => parseDeployConfig({ ...minimal, logRetentionDays: 45 })).toThrow(
      /Invalid deploy configuration/u,
    );
  });
});

describe('naming', () => {
  const config = parseDeployConfig({ stage: 'dev', account: '123456789012', alarmEmail: 'ops@amanilabs.co.ke' });

  it('prefixes stacks and resources with the stage so stages cannot collide', () => {
    expect(stackName(config, 'Data')).toBe('AuditIntelligence-dev-Data');
    expect(resourceName(config, 'uploads')).toBe('audit-intelligence-dev-uploads');
  });

  it('protects only production from destruction', () => {
    expect(isProtectedStage('prod')).toBe(true);
    expect(isProtectedStage('dev')).toBe(false);
  });
});
