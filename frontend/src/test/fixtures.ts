// API samples shaped like docs/api.md (real 8 Oct 2026 numbers), shared by unit and E2E tests.
import type { HistoryPoint, Regime, RegimeHistory, RegimeToday } from "../lib/types";

export function todayFixture(label: Regime = "Sideways", overrides: Partial<RegimeToday> = {}): RegimeToday {
  const probabilities =
    label === "Bull"
      ? { bull: 0.981, sideways: 0.019, crisis: 0 }
      : label === "Crisis"
        ? { bull: 0, sideways: 0.12, crisis: 0.88 }
        : { bull: 0, sideways: 0.9972, crisis: 0.0028 };
  return {
    as_of: "2026-10-08",
    is_stale: false,
    regime: {
      label,
      raw_label: label,
      confidence: probabilities[label.toLowerCase() as "bull" | "sideways" | "crisis"],
      probabilities,
      days_in_regime: 20,
      since: "2026-09-09",
    },
    signals: [
      {
        feature: "volatility_20d",
        name: "Volatility (20 days)",
        value: 0.00799118,
        direction: "up",
        text: "Daily price swings are larger than usual",
        contribution: 0.9726,
        percentile: 58.9,
      },
      {
        feature: "drawdown_60d",
        name: "Drawdown from 60-day high",
        value: -0.1026,
        direction: "down",
        text: "NIFTY is well below its recent high",
        contribution: 0.41,
        percentile: 5.5,
      },
      {
        feature: "sharpe_60d",
        name: "Risk-adjusted return (60 days)",
        value: -0.2,
        direction: "down",
        text: "Returns have been weak for the risk taken",
        contribution: 0.22,
        percentile: 0.9,
      },
    ],
    signals_approximate: false,
    brief: {
      text: "NIFTY 50 closed at 22,231.80 on 2026-10-08 (-1.64%). MarketMood's model reads the market as Sideways.",
      what_changed: "No regime change since the previous trading day.",
      source: "template",
    },
    nifty: {
      as_of: "2026-10-08",
      close: 22231.8,
      change_pct: -1.64,
      high_52w: 26328.55,
      low_52w: 22231.8,
      from_high_pct: -15.56,
      ytd_pct: -14.92,
    },
    model: { version: "hmm-20261008-c2", status: "experimental" },
    disclaimer: "Educational information about market conditions, not investment advice.",
    warnings: [],
    ...overrides,
  };
}

export function historyFixture(range: RegimeHistory["range"] = "1y", n = 60): RegimeHistory {
  const points: HistoryPoint[] = [];
  const start = Date.UTC(2026, 6, 1);
  for (let i = 0; i < n; i++) {
    const d = new Date(start + i * 86_400_000).toISOString().slice(0, 10);
    const label: Regime = i < n * 0.5 ? "Bull" : i < n * 0.65 ? "Crisis" : "Sideways";
    points.push({ date: d, label, confidence: 0.97, close: 24_000 + Math.sin(i / 6) * 600 - i * 15 });
  }
  return { range, as_of: points[points.length - 1]!.date, points };
}

/** One SSE body as the backend sends it (docs/api.md). */
export function sseBody(answer: string, opts: { messageId?: number; quotaLeft?: number; replace?: string | null } = {}) {
  const ev = (event: string, data: unknown) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
  return [
    ev("tool_start", { tool: "get_current_regime", label: "Checking today's regime" }),
    ": ping\n\n",
    ev("tool_end", { tool: "get_current_regime", ms: 84, ok: true }),
    ...answer.split(" ").map((w, i, all) => ev("token", { text: w + (i < all.length - 1 ? " " : "") })),
    ev("done", {
      message_id: opts.messageId ?? 812,
      session_id: "8a0f3c2e-0000-4000-8000-000000000001",
      usage: { in: 2140, out: 312 },
      quota_left: opts.quotaLeft ?? 9,
      warnings: [],
      replace_text: opts.replace ?? null,
      label: "AI-generated · educational only",
      cached: false,
    }),
  ].join("");
}
