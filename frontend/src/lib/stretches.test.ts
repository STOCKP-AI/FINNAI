import { describe, expect, it } from "vitest";

import { bandData, regimeStretches } from "./stretches";
import type { HistoryPoint, Regime } from "./types";

const day = (d: number, label: Regime, close = 100 + d): HistoryPoint => ({
  date: `2026-01-${String(d).padStart(2, "0")}`,
  label,
  confidence: 0.9,
  close,
});

// Bull, then Sideways, then Bull again: the case that used to draw the Bull band over the
// Sideways days in between (1Y / 5Y / Max ranges).
const points = [day(1, "Bull"), day(2, "Bull"), day(3, "Sideways"), day(4, "Sideways"), day(5, "Bull")];

describe("regime bands", () => {
  it("gives every day a value, 1 for the regime and 0 otherwise (no gaps to bridge)", () => {
    expect(bandData(points, "Bull").map((p) => p.value)).toEqual([1, 1, 0, 0, 1]);
    expect(bandData(points, "Sideways").map((p) => p.value)).toEqual([0, 0, 1, 1, 0]);
    expect(bandData(points, "Crisis").every((p) => p.value === 0)).toBe(true);
  });

  it("exactly one band is up on every day, so bands never overlap", () => {
    const bands = (["Bull", "Sideways", "Crisis"] as const).map((r) => bandData(points, r));
    points.forEach((_, i) => expect(bands.reduce((n, b) => n + b[i]!.value, 0)).toBe(1));
  });

  it("lists the stretches for the table view", () => {
    expect(regimeStretches(points).map((s) => [s.label, s.start, s.end])).toEqual([
      ["Bull", "2026-01-01", "2026-01-02"],
      ["Sideways", "2026-01-03", "2026-01-04"],
      ["Bull", "2026-01-05", "2026-01-05"],
    ]);
  });
});
