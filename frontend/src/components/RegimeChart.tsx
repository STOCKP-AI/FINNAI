import {
  AreaSeries,
  ColorType,
  CrosshairMode,
  LineSeries,
  createChart,
  type IChartApi,
  type ISeriesApi,
  type MouseEventParams,
} from "lightweight-charts";
import { useEffect, useMemo, useRef, useState } from "react";

import { useRegimeHistory } from "../hooks/useRegime";
import { formatDay, formatIndex, formatPct, REGIME_COLOR, REGIMES } from "../lib/format";
import { regimeStretches } from "../lib/stretches";
import type { HistoryPoint, Range, Regime } from "../lib/types";
import { ErrorCard, Skeleton } from "./States";

const RANGES: { id: Range; label: string }[] = [
  { id: "60d", label: "60D" },
  { id: "1y", label: "1Y" },
  { id: "5y", label: "5Y" },
  { id: "max", label: "Max" },
];

const alpha = (hex: string, a: number) =>
  `${hex}${Math.round(a * 255)
    .toString(16)
    .padStart(2, "0")}`;

function PriceChart({ points }: { points: HistoryPoint[] }) {
  const el = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const bandsRef = useRef<Record<Regime, ISeriesApi<"Area">> | null>(null);
  const lineRef = useRef<ISeriesApi<"Line"> | null>(null);
  const [hover, setHover] = useState<HistoryPoint | null>(null);
  const byDate = useMemo(() => new Map(points.map((p) => [p.date, p])), [points]);

  useEffect(() => {
    if (!el.current) return;
    const chart = createChart(el.current, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: "#8593ad",
        fontFamily: "Manrope Variable, ui-sans-serif, system-ui, sans-serif",
        fontSize: 11,
        attributionLogo: true, // TradingView attribution required by the licence
      },
      grid: { vertLines: { visible: false }, horzLines: { color: "rgba(148, 163, 184, 0.07)" } },
      rightPriceScale: { borderVisible: false, scaleMargins: { top: 0.12, bottom: 0.08 } },
      timeScale: { borderVisible: false, fixLeftEdge: true, fixRightEdge: true },
      crosshair: {
        mode: CrosshairMode.Magnet,
        vertLine: { color: "rgba(186, 230, 253, 0.35)", labelBackgroundColor: "#0c4a6e" },
        horzLine: { color: "rgba(186, 230, 253, 0.2)", labelBackgroundColor: "#0c4a6e" },
      },
      handleScroll: false,
      handleScale: false,
    });
    // Regime bands: one filled area per regime on a hidden 0-1 scale, so each stretch is a
    // solid block behind the price line (a histogram leaves 1 px gaps between days).
    const band = (r: Regime) =>
      chart.addSeries(AreaSeries, {
        priceScaleId: "bands",
        lineVisible: false,
        topColor: alpha(REGIME_COLOR[r], 0.24),
        bottomColor: alpha(REGIME_COLOR[r], 0.24),
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: false,
        autoscaleInfoProvider: () => ({ priceRange: { minValue: 0, maxValue: 1 } }),
      });
    const bands = { Bull: band("Bull"), Sideways: band("Sideways"), Crisis: band("Crisis") };
    chart.priceScale("bands").applyOptions({ scaleMargins: { top: 0, bottom: 0 }, visible: false });
    const line = chart.addSeries(LineSeries, {
      color: "#e0f2fe",
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: true,
      crosshairMarkerRadius: 4,
      crosshairMarkerBorderColor: "#0ea5e9",
      priceFormat: { type: "price", precision: 0, minMove: 1 },
    });
    chartRef.current = chart;
    bandsRef.current = bands;
    lineRef.current = line;
    return () => {
      chart.remove();
      chartRef.current = null;
    };
  }, []);

  useEffect(() => {
    if (!bandsRef.current || !lineRef.current || !chartRef.current) return;
    for (const r of REGIMES) {
      // A stretch also covers the first day of the next one, so neighbouring blocks touch.
      bandsRef.current[r].setData(
        points.map((p, i) =>
          p.label === r || points[i - 1]?.label === r ? { time: p.date, value: 1 } : { time: p.date },
        ),
      );
    }
    lineRef.current.setData(points.map((p) => ({ time: p.date, value: p.close })));
    chartRef.current.timeScale().fitContent();
    const chart = chartRef.current;
    const onMove = (param: MouseEventParams) => {
      const t = typeof param.time === "string" ? param.time : null;
      setHover(t ? (byDate.get(t) ?? null) : null);
    };
    chart.subscribeCrosshairMove(onMove);
    return () => chart.unsubscribeCrosshairMove(onMove);
  }, [points, byDate]);

  const shown = hover ?? points[points.length - 1];
  return (
    <div className="relative flex flex-1 flex-col">
      <p className="mb-2 min-h-5 text-xs tabular-nums text-ink-2" aria-live="off">
        {shown && (
          <>
            <span className="text-ink">{formatDay(shown.date)}</span> · NIFTY {formatIndex(shown.close)} ·{" "}
            <span className="inline-flex items-center gap-1">
              <span className="h-2 w-2 rounded-full" style={{ background: REGIME_COLOR[shown.label] }} />
              {shown.label}
            </span>
          </>
        )}
      </p>
      <figure className="m-0 flex flex-1 flex-col">
        <figcaption className="sr-only">
          NIFTY 50 closing level from {formatDay(points[0]!.date)} to {formatDay(points[points.length - 1]!.date)}, with
          the confirmed regime as coloured bands. The table below lists the same regimes.
        </figcaption>
        <div ref={el} className="h-56 w-full sm:h-64 lg:h-auto lg:min-h-64 lg:flex-1" />
      </figure>
    </div>
  );
}

/** DASH-06: NIFTY 50 with the confirmed regime as coloured bands; 60D / 1Y / 5Y / Max. */
export function RegimeChart({ className = "" }: { className?: string }) {
  const [range, setRange] = useState<Range>("1y");
  const { data, error, isPending, isFetching, refetch } = useRegimeHistory(range);
  const stretches = useMemo(() => (data ? regimeStretches(data.points) : []), [data]);

  return (
    <section className={`panel flex flex-col p-4 sm:p-5 ${className}`} aria-labelledby="chart-title">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="chart-title" className="text-sm font-semibold text-ink">
          NIFTY 50 and the market regime
        </h2>
        <div className="flex rounded-lg border border-white/10 bg-black/30 p-0.5" role="group" aria-label="Chart range">
          {RANGES.map((r) => (
            <button
              key={r.id}
              type="button"
              aria-pressed={range === r.id}
              onClick={() => setRange(r.id)}
              className={`rounded-md px-2.5 py-1 text-xs font-semibold transition ${
                range === r.id ? "bg-sky-400/20 text-sky-100" : "text-ink-3 hover:text-ink"
              }`}
            >
              {r.label}
            </button>
          ))}
        </div>
      </div>

      <ul className="mt-2 flex flex-wrap gap-3 text-xs text-ink-2" aria-label="Legend">
        {REGIMES.map((r) => (
          <li key={r} className="flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-sm" style={{ background: alpha(REGIME_COLOR[r], 0.7) }} aria-hidden="true" />
            {r}
          </li>
        ))}
        <li className="flex items-center gap-1.5">
          <span className="h-0.5 w-3 rounded bg-sky-100" aria-hidden="true" /> NIFTY 50 close
        </li>
      </ul>

      <div className={`mt-3 flex flex-1 flex-col transition-opacity ${isFetching && !isPending ? "opacity-60" : ""}`}>
        {isPending ? (
          <Skeleton className="h-64" />
        ) : error ? (
          <ErrorCard error={error} onRetry={() => refetch()} title="Couldn't load the chart" />
        ) : data && data.points.length > 1 ? (
          <PriceChart points={data.points} />
        ) : (
          <p className="py-16 text-center text-sm text-ink-3">Not enough history for this range yet.</p>
        )}
      </div>

      {stretches.length > 0 && (
        <details className="mt-3 text-xs text-ink-2">
          <summary className="cursor-pointer select-none text-ink-3 hover:text-ink">
            Show the regimes in this range as a table
          </summary>
          <div className="mt-2 max-h-56 overflow-auto rounded-lg border border-white/10">
            <table className="w-full text-left tabular-nums">
              <caption className="sr-only">Confirmed regimes and NIFTY 50 change in the selected range</caption>
              <thead className="sticky top-0 bg-panel text-ink-3">
                <tr>
                  <th className="px-2 py-1.5 font-medium">Regime</th>
                  <th className="px-2 py-1.5 font-medium">From</th>
                  <th className="px-2 py-1.5 font-medium">To</th>
                  <th className="px-2 py-1.5 font-medium">NIFTY change</th>
                </tr>
              </thead>
              <tbody>
                {[...stretches].reverse().map((s) => (
                  <tr key={s.start} className="border-t border-white/5">
                    <td className="px-2 py-1.5">{s.label}</td>
                    <td className="px-2 py-1.5">{formatDay(s.start)}</td>
                    <td className="px-2 py-1.5">{formatDay(s.end)}</td>
                    <td className="px-2 py-1.5">{formatPct(s.changePct, 1)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      )}
    </section>
  );
}
