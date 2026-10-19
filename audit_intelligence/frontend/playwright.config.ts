import { defineConfig, devices } from "@playwright/test";

/**
 * One smoke test against the real local stack: the backend on
 * E2E_API_URL (default http://127.0.0.1:8011) and this app served by Vite.
 * Run `npm run test:e2e` with the backend up; CI starts both.
 */
export default defineConfig({
  testDir: "./e2e",
  timeout: 120_000,
  retries: 0,
  use: {
    baseURL: "http://127.0.0.1:5174",
    trace: "retain-on-failure",
    ...devices["Desktop Chrome"],
  },
  webServer: {
    command: "npm run dev -- --port 5174 --strictPort",
    url: "http://127.0.0.1:5174",
    reuseExistingServer: !process.env.CI,
    env: { VITE_API_PROXY_TARGET: process.env.E2E_API_URL ?? "http://127.0.0.1:8011" },
    timeout: 60_000,
  },
});
