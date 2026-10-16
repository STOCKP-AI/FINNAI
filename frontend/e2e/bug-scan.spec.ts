// Regression tests for the bug scan of 15 Oct 2026 (front end, real browser).
import { expect, test } from "@playwright/test";

import { mockApi } from "./mock";

test.describe("bug scan", () => {
  test("a double-click on Ask sends once and is not stopped", async ({ page }) => {
    let posts = 0;
    await mockApi(page, { slowChatMs: 1200 });
    page.on("request", (r) => {
      if (r.url().endsWith("/v1/chat") && r.method() === "POST") posts++;
    });
    await page.goto("/");
    await page.getByRole("textbox", { name: /ask the ai analyst/i }).fill("What is India VIX?");
    await page.getByRole("button", { name: "Ask", exact: true }).dblclick();
    await expect(page.getByText("the model reads the market as Sideways")).toBeVisible();
    await expect(page.getByText("Stopped.")).toHaveCount(0);
    expect(posts).toBe(1);
  });

  test("leaving the dashboard while an answer streams does not cancel it", async ({ page }) => {
    await mockApi(page, { slowChatMs: 1500 });
    await page.goto("/");
    await page.getByRole("textbox", { name: /ask the ai analyst/i }).fill("What is India VIX?");
    await page.getByRole("button", { name: "Ask", exact: true }).click();
    await page.getByRole("link", { name: "How it works" }).click();
    await expect(page.getByRole("heading", { name: "How MarketMood works" })).toBeVisible();
    await page.waitForTimeout(2000);
    await page.getByRole("link", { name: "Dashboard" }).click();
    await expect(page.getByText("the model reads the market as Sideways")).toBeVisible();
    await expect(page.getByText("Stopped.")).toHaveCount(0);
  });

  test("the Experimental model badge opens How it works at the accuracy section", async ({ page }) => {
    await mockApi(page);
    await page.goto("/");
    await page.getByRole("link", { name: "Experimental model" }).click();
    await expect(page.getByRole("heading", { name: "How good is it?" })).toBeVisible();
    await expect
      .poll(() => page.evaluate(() => Math.abs(document.getElementById("accuracy")!.getBoundingClientRect().top)))
      .toBeLessThan(80);
  });

  test("a new page starts at the top", async ({ page }) => {
    await mockApi(page);
    await page.goto("/");
    await expect(page.getByRole("heading", { name: "Sideways" })).toBeVisible();
    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
    await page.evaluate(() => (document.querySelector('a[href="/how-it-works"]') as HTMLAnchorElement).click());
    await expect(page.getByRole("heading", { name: "How MarketMood works" })).toBeAttached();
    await expect.poll(() => page.evaluate(() => window.scrollY)).toBe(0);
  });

  test("a missing lazy chunk (stale tab after a deploy) does not blank the app", async ({ page }) => {
    await mockApi(page);
    await page.route(/\/assets\/Markdown-.*\.js$/, (r) =>
      r.fulfill({ status: 200, contentType: "text/html", body: "<!doctype html><html></html>" }),
    );
    await page.goto("/");
    await expect(page.getByRole("heading", { name: "Sideways" })).toBeVisible();
    await page.getByRole("button", { name: "Why is the model showing this regime?" }).click();
    await expect(page.getByText(/the model reads the market as Sideways/)).toBeVisible(); // as plain text
    await expect(page.getByRole("heading", { name: "Sideways" })).toBeVisible();
  });

  test("chat storage of the wrong shape does not blank the app", async ({ page }) => {
    await mockApi(page);
    await page.addInitScript(() => {
      localStorage.setItem("mm.chat.messages", "{}");
      localStorage.setItem("mm.chat.session", "[null]");
    });
    await page.goto("/");
    await expect(page.getByRole("heading", { name: "Sideways" })).toBeVisible();
    await page.reload();
    await expect(page.getByRole("heading", { name: "Sideways" })).toBeVisible();
  });
});
