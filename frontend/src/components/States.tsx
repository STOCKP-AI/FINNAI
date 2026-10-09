import { ApiError } from "../lib/api";
import { formatDay } from "../lib/format";

export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`animate-pulse rounded-xl bg-white/[0.06] ${className}`} aria-hidden="true" />;
}

/** TC-FE-02: what went wrong, a retry button and the reference to quote to the team. */
export function ErrorCard({ error, onRetry, title = "Couldn't load the market data" }: {
  error: unknown;
  onRetry?: () => void;
  title?: string;
}) {
  const api = error instanceof ApiError ? error : null;
  return (
    <div role="alert" className="rounded-2xl border border-crisis/40 bg-crisis/10 p-4 text-sm">
      <p className="font-semibold text-ink">{title}</p>
      <p className="mt-1 text-ink-2">{api?.message ?? "Something went wrong. Please try again."}</p>
      {api?.requestId && (
        <p className="mt-1 font-mono text-xs text-ink-3">
          Reference: {api.requestId} ({api.code})
        </p>
      )}
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="mt-3 rounded-lg border border-white/20 bg-white/10 px-3 py-1.5 font-medium text-ink hover:bg-white/15"
        >
          Try again
        </button>
      )}
    </div>
  );
}

/** TC-FE-03: the data is older than the last trading session. */
export function StaleBanner({ asOf }: { asOf: string }) {
  return (
    <div role="status" className="rounded-2xl border border-warn/40 bg-warn/10 px-4 py-3 text-sm text-ink">
      <span className="font-semibold">Showing data from {formatDay(asOf)}.</span>{" "}
      <span className="text-ink-2">Today's update hasn't arrived yet, so the regime may change once it does.</span>
    </div>
  );
}

export function WakingUp() {
  return (
    <div role="status" className="flex items-center gap-3 rounded-2xl border border-sky-400/25 bg-sky-400/10 px-4 py-3 text-sm">
      <span className="h-3 w-3 animate-spin rounded-full border-2 border-sky-300 border-t-transparent" aria-hidden="true" />
      <span>
        <span className="font-semibold">Waking up the server…</span>{" "}
        <span className="text-ink-2">The free server sleeps when nobody is using it; this can take up to a minute.</span>
      </span>
    </div>
  );
}
