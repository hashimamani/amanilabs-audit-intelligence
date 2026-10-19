import { expect, test } from "@playwright/test";

/**
 * The golden path an auditor walks on day one: sign in, run the demo
 * analysis, open the top case, change its status, see it in the trail.
 */
test("sign in, run the demo analysis, work a case", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Email").fill("admin@default.local");
  await page.getByLabel("Password").fill("local-dev-admin");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();

  await page.getByRole("link", { name: "Upload & Analyze" }).first().click();
  await page.getByRole("button", { name: "Run analysis on demo dataset" }).click();
  await expect(page.getByRole("heading", { name: "Analysis complete" })).toBeVisible({ timeout: 90_000 });
  await expect(page.getByText(/Cases created/)).toBeVisible();

  await page.getByRole("button", { name: "View cases" }).click();
  await expect(page.getByRole("heading", { name: "Cases" })).toBeVisible();
  const firstCase = page.getByRole("link", { name: /^CASE-/ }).first();
  const caseRef = (await firstCase.textContent()) ?? "";
  await firstCase.click();
  await expect(page.getByRole("heading", { name: caseRef })).toBeVisible();

  await page.getByLabel("Status").selectOption("In Progress");
  await expect(page.getByText("Status set to In Progress.")).toBeVisible();
  await expect(page.getByText(/changed status from Open to In Progress/)).toBeVisible();

  await page.getByRole("link", { name: "Rules" }).first().click();
  await expect(page.getByRole("heading", { name: "What the engine checks" })).toBeVisible();
  await expect(page.getByText("Fraud Ring / Collusion Network")).toBeVisible();
});
