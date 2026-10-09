import { expect, test } from "@playwright/test";

import { mockApi } from "./mock";

// Visual check for reviewers, not an assertion: SCREENSHOTS=1 npm run test:e2e -- screenshots
test.skip(!process.env.SCREENSHOTS, "set SCREENSHOTS=1 to capture screenshots");

test("capture dashboard and how-it-works", async ({ page }, info) => {
  await mockApi(page);
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Sideways" })).toBeVisible();
  await page.waitForTimeout(600);
  await page.screenshot({ path: `screenshots/dashboard-${info.project.name}.png`, fullPage: true });
  await page.getByRole("button", { name: "Why is the model showing this regime?" }).click();
  await expect(page.getByText("AI-generated · educational only")).toBeVisible();
  await page.screenshot({ path: `screenshots/chat-${info.project.name}.png`, fullPage: true });
  await page.goto("/how-it-works");
  await page.screenshot({ path: `screenshots/how-${info.project.name}.png`, fullPage: true });
});
