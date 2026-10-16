import { Component, type ErrorInfo, type ReactNode } from "react";

import { isChunkLoadError } from "../lib/chunk";

interface Props {
  children: ReactNode;
  /** What to show instead of the children once they have failed. */
  fallback: (error: unknown, retry: () => void) => ReactNode;
}

/** Catches render errors (including failed lazy imports) below it, so one broken part never
 *  blanks the whole page. */
export class ErrorBoundary extends Component<Props, { error: unknown }> {
  state: { error: unknown } = { error: null };

  static getDerivedStateFromError(error: unknown) {
    return { error: error ?? new Error("Unknown error") };
  }

  componentDidCatch(error: unknown, info: ErrorInfo) {
    console.error("MarketMood: a part of the page failed", error, info.componentStack);
  }

  retry = () => this.setState({ error: null });

  render() {
    return this.state.error ? this.props.fallback(this.state.error, this.retry) : this.props.children;
  }
}

/** Full-width message for a part of the page that could not load, with a reload button. */
export function LoadFailed({ error, what }: { error: unknown; what: string }) {
  const stale = isChunkLoadError(error);
  return (
    <div role="alert" className="mx-auto my-8 max-w-xl rounded-2xl border border-white/10 bg-white/[0.04] p-6 text-center">
      <p className="font-semibold text-ink">
        {stale ? "A newer version of MarketMood is available." : `Sorry, ${what} could not be shown.`}
      </p>
      <p className="mt-1 text-sm text-ink-3">
        {stale ? "Reload the page to get it." : "Reloading the page usually fixes this."}
      </p>
      <button
        type="button"
        onClick={() => window.location.reload()}
        className="mt-4 rounded-lg bg-gradient-to-r from-indigo-500 to-sky-500 px-4 py-2 text-sm font-semibold text-white"
      >
        Reload
      </button>
    </div>
  );
}
