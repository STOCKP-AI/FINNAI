import type { ReactNode } from "react";
import { Link, NavLink } from "react-router";

import { useRegimeToday } from "../hooks/useRegime";
import { formatDayShort } from "../lib/format";

function Logo() {
  return (
    <svg viewBox="0 0 32 32" className="h-8 w-8" aria-hidden="true">
      <rect width="32" height="32" rx="9" fill="#06102a" stroke="rgb(56 189 248 / 0.35)" />
      <path
        d="M5 20c3-6 6-9 9-5s5 5 8-1 4-6 5-5"
        fill="none"
        stroke="#38bdf8"
        strokeWidth="2.6"
        strokeLinecap="round"
      />
      <circle cx="26" cy="9" r="2.4" fill="#22c55e" />
    </svg>
  );
}

/** "Market data · 8 Oct close": honest freshness, not a "LIVE" claim - the model runs on
 *  end-of-day data, so the pill says which close it is showing (amber when stale). */
export function StatusPill() {
  const { data, isError } = useRegimeToday();
  const stale = data?.is_stale;
  const dot = isError ? "bg-crisis" : stale ? "bg-warn" : data ? "bg-live" : "bg-ink-3";
  const text = isError
    ? "Offline"
    : data
      ? stale
        ? `Data from ${formatDayShort(data.as_of)}`
        : `${formatDayShort(data.as_of)} close`
      : "Loading";
  return (
    <div
      className="flex items-center gap-3 rounded-full border border-white/10 bg-[#0d1632]/90 px-4 py-2 text-sm text-ink"
      role="status"
      aria-label={`Market data: ${text}`}
    >
      <span className="flex items-center gap-2">
        <span className="h-2 w-2 rounded-full bg-live" aria-hidden="true" />
        Market data
      </span>
      <span className="flex items-center gap-2 font-semibold">
        <span className={`h-2 w-2 rounded-full ${dot} ${data && !stale ? "animate-pulse" : ""}`} aria-hidden="true" />
        {text}
      </span>
    </div>
  );
}

const navClass = ({ isActive }: { isActive: boolean }) =>
  `rounded-lg px-3 py-1.5 text-sm transition ${isActive ? "bg-white/10 text-ink" : "text-ink-2 hover:text-ink"}`;

export function Layout({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-dvh flex-col">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-lg focus:bg-panel focus:px-4 focus:py-2"
      >
        Skip to content
      </a>
      <header className="mx-auto flex w-full max-w-6xl flex-wrap items-center justify-between gap-3 px-4 pt-5 sm:px-6">
        <Link to="/" className="flex items-center gap-2.5 text-lg font-bold tracking-tight text-ink">
          <Logo />
          MarketMood
        </Link>
        <div className="flex flex-wrap items-center gap-2 sm:gap-4">
          <nav aria-label="Main" className="flex gap-1">
            <NavLink to="/" end className={navClass}>
              Dashboard
            </NavLink>
            <NavLink to="/how-it-works" className={navClass}>
              How it works
            </NavLink>
          </nav>
          <StatusPill />
        </div>
      </header>

      <main id="main" className="mx-auto w-full max-w-6xl flex-1 px-4 pb-10 sm:px-6">
        {children}
      </main>

      <footer className="border-t border-white/10 px-4 py-6 text-center text-xs leading-relaxed text-ink-3 sm:px-6">
        <p className="font-medium text-ink-2">Educational market context, not investment advice.</p>
        <p className="mt-1">
          MarketMood is not a SEBI-registered investment adviser. Data: NIFTY 50 and India VIX end-of-day closes.
          Charts by{" "}
          <a
            className="underline underline-offset-2 hover:text-ink"
            href="https://www.tradingview.com/"
            target="_blank"
            rel="noopener noreferrer"
          >
            TradingView Lightweight Charts
          </a>
          .
        </p>
      </footer>
    </div>
  );
}
