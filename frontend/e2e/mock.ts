import type { Page, Route } from "@playwright/test";

import type { Range, Regime, RegimeToday } from "../src/lib/types";
import { historyFixture, sseBody, todayFixture } from "../src/test/fixtures";

export const API = "http://api.test"; // VITE_API_BASE_URL of the E2E build (playwright.config.ts)

const cors = { "Access-Control-Allow-Origin": "*", "Access-Control-Allow-Headers": "*" };

/** Answer the app's API calls from fixtures, so E2E tests need no backend. */
export async function mockApi(
  page: Page,
  opts: { regime?: Regime; today?: Partial<RegimeToday>; answer?: string; slowChatMs?: number } = {},
) {
  const feedback: unknown[] = [];
  await page.route(`${API}/**`, async (route: Route) => {
    const req = route.request();
    const url = new URL(req.url());
    if (req.method() === "OPTIONS") return route.fulfill({ status: 204, headers: cors });
    if (url.pathname === "/v1/regime/today") {
      return route.fulfill({ json: todayFixture(opts.regime, opts.today), headers: cors });
    }
    if (url.pathname === "/v1/regime/history") {
      const range = (url.searchParams.get("range") ?? "1y") as Range;
      return route.fulfill({ json: historyFixture(range, range === "60d" ? 40 : 120), headers: cors });
    }
    if (url.pathname === "/v1/chat") {
      if (opts.slowChatMs) await new Promise((r) => setTimeout(r, opts.slowChatMs));
      return route.fulfill({
        status: 200,
        headers: { ...cors, "Content-Type": "text/event-stream" },
        body: sseBody(
          opts.answer ??
            "As of **8 Oct 2026** the model reads the market as Sideways (confidence 99.7%). For personal decisions, speak to a SEBI-registered investment adviser.",
        ),
      });
    }
    if (url.pathname === "/v1/feedback") {
      feedback.push(req.postDataJSON());
      return route.fulfill({ status: 204, headers: cors });
    }
    return route.fulfill({ status: 404, json: { error: { code: "MM-REQ-003", message: "Not found.", request_id: "x" } } });
  });
  return { feedback };
}
