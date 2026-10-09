import { Link } from "react-router";

import { formatDay, formatProb, REGIME_COLOR, REGIME_MEANING, REGIMES } from "../lib/format";
import type { Regime, RegimeToday } from "../lib/types";
import { Waves } from "./Waves";

export function RegimeIcon({ regime, className = "h-6 w-6" }: { regime: Regime; className?: string }) {
  const common = {
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 2.2,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
  };
  return (
    <svg viewBox="0 0 24 24" className={className} aria-hidden="true" style={{ color: REGIME_COLOR[regime] }}>
      {regime === "Bull" && <path {...common} d="M3 17l6-6 4 4 8-8M15 7h6v6" />}
      {regime === "Sideways" && <path {...common} d="M3 12h18M7 8l-4 4 4 4M17 8l4 4-4 4" />}
      {regime === "Crisis" && <path {...common} d="M3 7l6 6 4-4 8 8M21 11v6h-6" />}
    </svg>
  );
}

export function RegimeCard({ data }: { data: RegimeToday }) {
  const { regime, model } = data;
  const color = REGIME_COLOR[regime.label];
  const probs = regime.probabilities;
  const byRegime: Record<Regime, number> = { Bull: probs.bull, Sideways: probs.sideways, Crisis: probs.crisis };

  return (
    <section className="panel-soft p-5" aria-labelledby="regime-title">
      <Waves className="-right-10 -top-6 h-28 w-64 opacity-70" />
      <div className="relative">
        <div className="flex items-start justify-between gap-2">
          <p className="eyebrow">Today's market regime</p>
          {model?.status === "experimental" && (
            <Link
              to="/how-it-works#accuracy"
              className="rounded-full border border-warn/40 bg-warn/10 px-2 py-0.5 text-[0.7rem] font-semibold text-warn hover:bg-warn/20"
              title="The model misses some of its accuracy targets. See how it works."
            >
              Experimental model
            </Link>
          )}
        </div>

        <h2 id="regime-title" className="mt-2 flex items-center gap-3 text-3xl font-bold tracking-tight text-ink">
          <span
            className="grid h-11 w-11 place-items-center rounded-xl border"
            style={{ borderColor: `${color}66`, background: `${color}1f`, boxShadow: `0 0 24px -6px ${color}` }}
          >
            <RegimeIcon regime={regime.label} />
          </span>
          {regime.label}
        </h2>
        <p className="mt-2 text-sm text-ink-2">{REGIME_MEANING[regime.label]}</p>
        <p className="mt-2 text-sm text-ink-2">
          In this regime for <span className="font-semibold text-ink">{regime.days_in_regime} trading days</span>
          <span className="text-ink-3"> · since {formatDay(regime.since)}</span>
        </p>
        {regime.raw_label !== regime.label && (
          <p className="mt-2 rounded-lg bg-white/5 px-2.5 py-1.5 text-xs text-ink-2">
            Today's reading is <strong className="text-ink">{regime.raw_label}</strong>. The label changes only after two
            days in a row, so it may switch tomorrow.
          </p>
        )}

        <div className="mt-4">
          <div className="flex items-baseline justify-between text-sm">
            <span className="text-ink-2">How sure the model is</span>
            <span className="font-semibold text-ink">{formatProb(regime.confidence)}</span>
          </div>
          <div
            className="mt-1.5 flex h-2 overflow-hidden rounded-full bg-white/10"
            role="img"
            aria-label={REGIMES.map((r) => `${r} ${formatProb(byRegime[r])}`).join(", ")}
          >
            {REGIMES.map((r) => (
              <span
                key={r}
                style={{ width: `${byRegime[r] * 100}%`, background: REGIME_COLOR[r] }}
                className="h-full [&+&]:border-l-2 [&+&]:border-card"
              />
            ))}
          </div>
          <ul className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs text-ink-3">
            {REGIMES.map((r) => (
              <li key={r} className="flex items-center gap-1.5">
                <span className="h-2 w-2 rounded-full" style={{ background: REGIME_COLOR[r] }} aria-hidden="true" />
                {r} <span className="text-ink-2">{formatProb(byRegime[r])}</span>
              </li>
            ))}
          </ul>
          <p className="mt-2 text-[0.72rem] leading-snug text-ink-3">
            This is the model's own estimate, not the chance of the market rising or falling.
          </p>
        </div>
      </div>
    </section>
  );
}
