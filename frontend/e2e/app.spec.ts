import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

import { mockApi } from "./mock";

test.describe("dashboard", () => {
  test("shows today's regime, stats and chart", async ({ page }) => {
    await mockApi(page);
    await page.goto("/");
    await expect(page.getByRole("heading", { name: "Sideways" })).toBeVisible();
    await expect(page.getByText("22,231.80").first()).toBeVisible();
    await expect(page.getByRole("heading", { name: "NIFTY 50 and the market regime" })).toBeVisible();
    await page.getByRole("button", { name: "60D" }).click();
    await expect(page.getByRole("button", { name: "60D" })).toHaveAttribute("aria-pressed", "true");
  });

  test("TC-FE-05: no horizontal scroll, everything reachable", async ({ page }) => {
    await mockApi(page);
    await page.goto("/");
    await expect(page.getByRole("heading", { name: "Sideways" })).toBeVisible();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow).toBeLessThanOrEqual(0);
    await expect(page.getByRole("textbox", { name: /ask the ai analyst/i })).toBeVisible();
    await page.getByRole("link", { name: "How it works" }).click();
    await expect(page.getByRole("heading", { name: "How MarketMood works" })).toBeVisible();
    const overflow2 = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow2).toBeLessThanOrEqual(0);
  });
});

test.describe("chat", () => {
  test("TC-FE-04: suggested question streams with a tool chip; feedback is sent", async ({ page }) => {
    const { feedback } = await mockApi(page);
    await page.goto("/");
    await page.getByRole("button", { name: "Why is the model showing this regime?" }).click();
    const thread = page.getByRole("region", { name: "AI analyst" });
    await expect(thread.getByText("SEBI-registered investment adviser", { exact: false })).toBeVisible();
    await expect(thread.getByText("AI-generated · educational only")).toBeVisible(); // TC-AGT-11
    await expect(thread.getByText("9 questions left today")).toBeVisible();
    await thread.getByRole("button", { name: "Helpful answer" }).click();
    await expect(thread.getByRole("button", { name: "Helpful answer" })).toHaveAttribute("aria-pressed", "true");
    expect(feedback).toEqual([{ session_id: "8a0f3c2e-0000-4000-8000-000000000001", message_id: 812, rating: "up" }]);
  });

  test("TC-FE-04: Stop aborts a slow answer", async ({ page }) => {
    await mockApi(page, { slowChatMs: 5000 });
    await page.goto("/");
    await page.getByRole("textbox", { name: /ask the ai analyst/i }).fill("What is India VIX?");
    await page.getByRole("button", { name: "Ask", exact: true }).click();
    await page.getByRole("button", { name: "Stop" }).click();
    await expect(page.getByText("Stopped.")).toBeVisible();
    await expect(page.getByRole("button", { name: "Ask", exact: true })).toBeVisible();
  });

  test("TC-AGT-09: AI text cannot inject HTML or load images", async ({ page }) => {
    await mockApi(page, {
      answer: 'Hello <img src="http://evil.test/x.png" onerror="window.__pwned=1"> ![pixel](http://evil.test/p.png) <b>bold</b>',
    });
    const loaded: string[] = [];
    page.on("request", (r) => r.url().includes("evil.test") && loaded.push(r.url()));
    await page.goto("/");
    await page.getByRole("button", { name: "What happened to NIFTY after past Crisis regimes?" }).click();
    const thread = page.getByRole("region", { name: "AI analyst" });
    await expect(thread.getByText("AI-generated · educational only")).toBeVisible();
    await expect(thread.locator("img")).toHaveCount(0);
    await expect(thread.locator("b")).toHaveCount(0);
    expect(await page.evaluate(() => (window as unknown as { __pwned?: number }).__pwned)).toBeUndefined();
    expect(loaded).toEqual([]);
  });
});

test.describe("accessibility", () => {
  for (const path of ["/", "/how-it-works"]) {
    test(`TC-FE-06: no serious or critical axe violations on ${path}`, async ({ page }) => {
      await mockApi(page);
      await page.goto(path);
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      if (path === "/") await expect(page.getByRole("heading", { name: "Sideways" })).toBeVisible();
      const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
      const bad = results.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
      expect(bad.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`)).toEqual([]);
    });
  }
});
