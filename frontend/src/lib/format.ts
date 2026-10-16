import type { Regime } from "./types";

const inr = new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const day = new Intl.DateTimeFormat("en-IN", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
const dayShort = new Intl.DateTimeFormat("en-IN", { day: "numeric", month: "short", timeZone: "UTC" });

/** 22231.8 -> "22,231.80" (Indian digit grouping). */
export const formatIndex = (n: number) => inr.format(n);

/** -1.64 -> "−1.64%", 0.5 -> "+0.50%" (a real minus sign, so it reads well and is not hyphenated). */
export function formatPct(n: number | null | undefined, digits = 2): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  const r = Number(n.toFixed(digits)); // sign of what is shown: -0.001 is "0.00%", not "−0.00%"
  const sign = r > 0 ? "+" : r < 0 ? "−" : "";
  return `${sign}${Math.abs(r).toFixed(digits)}%`;
}

/** Sign of a change as shown with `digits` decimals: "up", "down" or "flat". */
export function direction(n: number, digits = 2): "up" | "down" | "flat" {
  const r = Number(n.toFixed(digits));
  return r > 0 ? "up" : r < 0 ? "down" : "flat";
}

/** 0.9972 -> "99.7%", 0.42 -> "42%". Near-certain values never round up to "100.0%" (or down to
 *  "0.0%") unless they really are 1 (or 0). */
export function formatProb(p: number): string {
  if (p >= 0.995 || p <= 0.005) {
    const tenths = p >= 0.995 ? Math.floor(p * 1000) : Math.ceil(p * 1000);
    const shown = p > 0 && p < 1 ? Math.min(999, Math.max(1, tenths)) : tenths;
    return `${(shown / 10).toFixed(1)}%`;
  }
  return `${Math.min(99, Math.max(1, Math.round(p * 100)))}%`;
}

/** "2026-10-08" -> "8 Oct 2026" (dates from the API are trading days, no time zone). */
export const formatDay = (iso: string) => day.format(new Date(`${iso}T00:00:00Z`));
export const formatDayShort = (iso: string) => dayShort.format(new Date(`${iso}T00:00:00Z`));

export const REGIMES: Regime[] = ["Bull", "Sideways", "Crisis"];

/** Regime colours, validated as a set on the dark surface (dataviz validator: lightness,
 *  chroma, normal-vision and contrast pass; red/green CVD is in the warn band, so a regime
 *  is never shown by colour alone - always with its name and icon). */
export const REGIME_COLOR: Record<Regime, string> = {
  Bull: "#199e70",
  Sideways: "#9085e9",
  Crisis: "#e66767",
};

export const REGIME_MEANING: Record<Regime, string> = {
  Bull: "Prices have been rising steadily with calm day-to-day moves.",
  Sideways: "No clear trend: the market is drifting, often with bigger daily swings.",
  Crisis: "Sharp falls and very high volatility, like March 2020.",
};
