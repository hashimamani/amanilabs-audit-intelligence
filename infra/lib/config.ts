import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { z } from 'zod';

const configDir = join(dirname(fileURLToPath(import.meta.url)), '..', 'config');

export const STAGES = ['dev', 'prod'] as const;
export type Stage = (typeof STAGES)[number];
export const stageSchema = z.enum(STAGES);

/**
 * Everything that differs between a dev and a prod deployment lives in
 * `infra/config/<stage>.json` and is validated here, before any construct
 * exists, so a bad value fails at synth with a readable message.
 */
export const deployConfigSchema = z
  .strictObject({
    stage: stageSchema,
    region: z
      .string()
      .regex(/^[a-z]{2}-[a-z]+-\d$/u, 'region must look like eu-west-1')
      .default('eu-west-1'),
    /** Pinned for prod so a deploy cannot land in whichever account the CLI happens to hold. */
    account: z.string().regex(/^\d{12}$/u, 'account must be the 12-digit account id').optional(),
    /** Receives every CloudWatch alarm. AWS emails a confirmation that must be clicked. */
    alarmEmail: z.email(),
    logRetentionDays: z
      .union([z.literal(7), z.literal(14), z.literal(30), z.literal(60), z.literal(90), z.literal(180), z.literal(365)])
      .default(30),
  })
  .superRefine((config, ctx) => {
    if (config.stage === 'prod' && config.account === undefined) {
      ctx.addIssue({
        code: 'custom',
        path: ['account'],
        message: 'prod must pin "account" to the 12-digit account id',
      });
    }
  });

export type DeployConfig = z.infer<typeof deployConfigSchema>;

export function parseDeployConfig(raw: unknown): DeployConfig {
  const result = deployConfigSchema.safeParse(raw);
  if (!result.success) {
    throw new Error(`Invalid deploy configuration:\n${z.prettifyError(result.error)}`);
  }
  return result.data;
}

/**
 * Resolve the target stage from CDK context (`-c stage=prod`), defaulting to
 * `dev` so a careless `cdk deploy` cannot touch production.
 */
export function resolveStage(contextValue: unknown): Stage {
  if (contextValue === undefined || contextValue === null || contextValue === '') {
    return 'dev';
  }
  const result = stageSchema.safeParse(contextValue);
  if (!result.success) {
    throw new Error(
      `Unknown stage ${JSON.stringify(contextValue)}. Expected one of: ${STAGES.join(', ')}. ` +
        'Pass it as `cdk deploy -c stage=prod`.',
    );
  }
  return result.data;
}

export function loadDeployConfig(stage: Stage, overrides: Record<string, unknown> = {}): DeployConfig {
  const file = join(configDir, `${stage}.json`);

  let raw: string;
  try {
    raw = readFileSync(file, 'utf8');
  } catch (cause) {
    throw new Error(
      `No deploy configuration for stage "${stage}". Expected ${file}. ` +
        'Copy infra/config/prod.json.example and edit it; see docs/DEPLOYING.md.',
      { cause },
    );
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch (cause) {
    throw new Error(`${file} is not valid JSON.`, { cause });
  }
  if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
    throw new Error(`${file} must contain a JSON object.`);
  }

  // `stage` is owned by the file path, not the file body, so it cannot drift.
  return parseDeployConfig({ ...parsed, ...overrides, stage });
}

export const isProtectedStage = (stage: Stage): boolean => stage === 'prod';

export const stackName = (config: DeployConfig, part: string): string =>
  `AuditIntelligence-${config.stage}-${part}`;

/** Resource name prefix, so two stages in one account cannot collide. */
export const resourceName = (config: DeployConfig, suffix: string): string =>
  `audit-intelligence-${config.stage}-${suffix}`;

export function stackEnv(config: DeployConfig): { account?: string; region: string } {
  return {
    ...(config.account !== undefined && { account: config.account }),
    region: config.region,
  };
}

export function commonTags(config: DeployConfig): Record<string, string> {
  return {
    Project: 'AuditIntelligence',
    Environment: config.stage,
    ManagedBy: 'cdk',
  };
}
