import { formatIndex, formatPct } from "../lib/format";
import type { RegimeToday } from "../lib/types";

function Tile({ label, value, sub, tone }: { label: string; value: string; sub?: string; tone?: "up" | "down" }) {
  return (
    <div className="tile flex min-h-[5.5rem] flex-col justify-between p-3.5">
      <dt className="text-xs text-ink-3">{label}</dt>
      <dd>
        <span className="block text-lg font-bold tabular-nums tracking-tight text-ink sm:text-xl">{value}</span>
        {sub && (
          <span
            className={`block text-xs tabular-nums ${tone === "up" ? "text-emerald-300" : tone === "down" ? "text-rose-300" : "text-ink-3"}`}
          >
            {sub}
          </span>
        )}
      </dd>
    </div>
  );
}

const tone = (n: number | null) => (n === null ? undefined : n >= 0 ? "up" : "down");

/** DASH-05: four headline numbers - hero stats, not a chart (dataviz: a single value is a tile). */
export function StatTiles({ data }: { data: RegimeToday }) {
  const n = data.nifty;
  return (
    <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4" aria-label="NIFTY 50 key numbers">
      <Tile label="NIFTY 50 close" value={formatIndex(n.close)} sub={`${formatPct(n.change_pct)} on the day`} tone={tone(n.change_pct)} />
      <Tile label="From 52-week high" value={formatPct(n.from_high_pct)} sub={`High ${formatIndex(n.high_52w)}`} />
      <Tile label="This year" value={formatPct(n.ytd_pct)} sub="Since 1 Jan" tone={tone(n.ytd_pct)} />
      <Tile
        label="52-week low"
        value={formatIndex(n.low_52w)}
        sub={n.close <= n.low_52w ? "Closed at the low" : `${formatPct((n.close / n.low_52w - 1) * 100)} above it`}
      />
    </dl>
  );
}
