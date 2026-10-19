/**
 * Runtime configuration. Deployed, CloudFront serves /config.json beside the
 * bundle (written by the Web stack), so one build is valid in every stage.
 * Locally there is no config.json and the app falls back to the backend's
 * local auth mode, which mints tokens of the same shape as Cognito's.
 */
export type AuthMode = "cognito" | "local";

export interface AppConfig {
  stage: string;
  region: string;
  authMode: AuthMode;
  userPoolId?: string;
  userPoolClientId?: string;
  apiBasePath: string;
}

const LOCAL_CONFIG: AppConfig = { stage: "local", region: "eu-west-1", authMode: "local", apiBasePath: "/api" };

let current: AppConfig | undefined;

export async function loadConfig(): Promise<AppConfig> {
  try {
    const response = await fetch("/config.json", { cache: "no-store" });
    if (response.ok) {
      const json = (await response.json()) as Partial<AppConfig>;
      if (json.userPoolId && json.userPoolClientId) {
        current = {
          stage: json.stage ?? "dev",
          region: json.region ?? "eu-west-1",
          authMode: "cognito",
          userPoolId: json.userPoolId,
          userPoolClientId: json.userPoolClientId,
          apiBasePath: json.apiBasePath ?? "/api",
        };
        return current;
      }
    }
  } catch {
    // No config served: local development.
  }
  current = LOCAL_CONFIG;
  return current;
}

export function getConfig(): AppConfig {
  if (!current) throw new Error("loadConfig() has not completed");
  return current;
}

export function setConfigForTests(config: AppConfig): void {
  current = config;
}
