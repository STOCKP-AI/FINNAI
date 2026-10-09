import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse, type JsonBodyType } from "msw";
import { describe, expect, it, vi } from "vitest";

import { API_BASE } from "../lib/api";
import { REGIME_COLOR } from "../lib/format";
import type { Regime } from "../lib/types";
import { todayFixture } from "../test/fixtures";
import { renderWithApp } from "../test/render";
import { server } from "../test/server";
import { Dashboard } from "./Dashboard";

// The chart draws on <canvas>, which jsdom does not have; it is covered by the E2E tests.
vi.mock("../components/RegimeChart", () => ({ RegimeChart: () => <div data-testid="chart" /> }));

const today = (body: JsonBodyType, init?: ResponseInit) =>
  server.use(http.get(`${API_BASE}/v1/regime/today`, () => HttpResponse.json(body, init)));

describe("Dashboard", () => {
  it.each<[Regime, string]>([
    ["Bull", "98%"],
    ["Sideways", "99.7%"],
    ["Crisis", "88%"],
  ])("TC-FE-01: shows the %s regime with its colour and confidence", async (label, confidence) => {
    today(todayFixture(label));
    renderWithApp(<Dashboard />);
    const heading = await screen.findByRole("heading", { level: 2, name: label });
    const card = heading.closest("section")!;
    expect(within(card).getByText("How sure the model is").nextSibling).toHaveTextContent(confidence);
    expect(heading.querySelector("svg")).toHaveStyle({ color: REGIME_COLOR[label] });
    expect(within(card).getByText("Experimental model")).toBeInTheDocument();
    expect(screen.getAllByText("22,231.80")).toHaveLength(2); // close and 52-week low, Indian grouping
    expect(screen.getByText("−15.56%")).toBeInTheDocument();
  });

  it("explains a regime change that is not confirmed yet", async () => {
    const data = todayFixture("Sideways");
    data.regime.raw_label = "Crisis";
    today(data);
    renderWithApp(<Dashboard />);
    expect(await screen.findByText(/Today's reading is/)).toHaveTextContent("Crisis");
  });

  it("TC-FE-02: an API error shows a card with the reference and a working retry", async () => {
    let calls = 0;
    server.use(
      http.get(`${API_BASE}/v1/regime/today`, () => {
        calls += 1;
        if (calls === 1) {
          return HttpResponse.json(
            { error: { code: "MM-DB-001", message: "The database is not reachable right now.", request_id: "req-123" } },
            { status: 503 },
          );
        }
        return HttpResponse.json(todayFixture("Bull"));
      }),
    );
    renderWithApp(<Dashboard />);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("The database is not reachable right now.");
    expect(alert).toHaveTextContent("Reference: req-123 (MM-DB-001)");
    await userEvent.click(within(alert).getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("heading", { level: 2, name: "Bull" })).toBeInTheDocument();
  });

  it("TC-FE-02: an error page that is not JSON still gets a friendly message", async () => {
    server.use(http.get(`${API_BASE}/v1/regime/today`, () => new HttpResponse("<html>Bad gateway</html>", { status: 502 })));
    renderWithApp(<Dashboard />);
    expect(await screen.findByRole("alert")).toHaveTextContent("unexpected error");
  });

  it("TC-FE-03: stale data shows a banner with the date of the data", async () => {
    today(todayFixture("Sideways", { is_stale: true, as_of: "2026-10-06", warnings: ["MM-DATA-001"] }));
    renderWithApp(<Dashboard />);
    expect(await screen.findByText("Showing data from 6 Oct 2026.")).toBeInTheDocument();
  });

  it("no stale banner when the data is fresh", async () => {
    renderWithApp(<Dashboard />);
    await screen.findByRole("heading", { level: 2, name: "Sideways" });
    expect(screen.queryByText(/Showing data from/)).not.toBeInTheDocument();
  });
});
