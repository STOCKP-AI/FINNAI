import type { HistoryPoint, Regime } from "./types";

/** Consecutive days with the same confirmed label: the bands, as a table for screen readers. */
export function regimeStretches(points: HistoryPoint[]) {
  const out: { label: Regime; start: string; end: string; changePct: number }[] = [];
  let startIdx = 0;
  points.forEach((p, i) => {
    const next = points[i + 1];
    if (!next || next.label !== p.label) {
      const first = points[startIdx]!;
      out.push({ label: p.label, start: first.date, end: p.date, changePct: (p.close / first.close - 1) * 100 });
      startIdx = i + 1;
    }
  });
  return out;
}
