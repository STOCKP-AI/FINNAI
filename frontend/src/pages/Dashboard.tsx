import { lazy, Suspense, useEffect, useRef } from "react";

import { BriefPanel } from "../components/BriefPanel";
import { AskBar, ChatThread, SuggestionChips } from "../components/Chat";
import { RegimeCard } from "../components/RegimeCard";
import { ErrorCard, Skeleton, StaleBanner, WakingUp } from "../components/States";
import { StatTiles } from "../components/StatTiles";
import { useChat } from "../hooks/useChat";
import { useRegimeToday, useSlow } from "../hooks/useRegime";
import type { ChipId } from "../lib/types";

// The chart library is the biggest dependency: load it after the regime card is on screen.
const RegimeChart = lazy(() => import("../components/RegimeChart").then((m) => ({ default: m.RegimeChart })));

export function Dashboard() {
  const today = useRegimeToday();
  const slow = useSlow(today.isPending);
  const chat = useChat();
  const threadRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    document.title = today.data
      ? `${today.data.regime.label} · MarketMood`
      : "MarketMood - India's market regime, explained";
  }, [today.data]);

  const ask = (text: string, chipId: ChipId | null = null) => {
    chat.send(text, chipId);
    requestAnimationFrame(() => threadRef.current?.scrollIntoView?.({ behavior: "smooth", block: "start" }));
  };

  return (
    <div className="space-y-8 pt-8">
      <section className="mx-auto max-w-2xl rounded-2xl border border-white/10 bg-gradient-to-b from-white/[0.03] to-transparent px-5 py-6 text-center sm:px-8">
        <h1 className="text-2xl font-bold tracking-tight text-ink sm:text-3xl">What mood is the Indian market in?</h1>
        <p className="mt-2 text-sm text-ink-2 sm:text-base">
          The NIFTY 50 regime - Bull, Sideways or Crisis - from a statistical model, updated after every trading day,
          with an AI analyst to explain it.
        </p>
      </section>

      <div className="space-y-3">
        {slow && <WakingUp />}
        {today.data?.is_stale && <StaleBanner asOf={today.data.as_of} />}
      </div>

      <div className="glass-card p-3 sm:p-5">
        {today.error ? (
          <ErrorCard error={today.error} onRetry={() => today.refetch()} />
        ) : (
          <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_1px_minmax(17rem,22rem)]">
            <div className="order-2 flex flex-col gap-4 lg:order-1">
              <Suspense fallback={<Skeleton className="h-80 lg:flex-1" />}>
                <RegimeChart className="lg:flex-1" />
              </Suspense>
              {today.data ? <StatTiles data={today.data} /> : <Skeleton className="h-24" />}
            </div>
            <div className="hidden bg-white/10 lg:order-2 lg:block" aria-hidden="true" />
            <div className="order-1 space-y-4 lg:order-3">
              {today.data ? (
                <>
                  <RegimeCard data={today.data} />
                  <BriefPanel data={today.data} />
                </>
              ) : (
                <>
                  <Skeleton className="h-64" />
                  <Skeleton className="h-72" />
                </>
              )}
            </div>
          </div>
        )}

        <div className="mt-5 flex flex-col gap-3 border-t border-white/10 pt-4 md:flex-row md:items-center md:justify-between">
          <p className="text-xs leading-relaxed text-ink-3 md:max-w-[16rem]">
            Ask the AI analyst. It answers from MarketMood's data and never tells you what to buy or sell.
          </p>
          <div className="md:w-[60%]">
            <AskBar
              onSend={(t) => ask(t)}
              onStop={chat.stop}
              busy={chat.busy}
              disabled={chat.quotaLeft === 0}
            />
          </div>
        </div>
      </div>

      <SuggestionChips disabled={chat.busy} onPick={(id, text) => ask(text, id)} />

      <div ref={threadRef} className="scroll-mt-6">
        <ChatThread
          messages={chat.messages}
          onRate={chat.rate}
          onReset={chat.reset}
          quotaLeft={chat.quotaLeft}
          limitReached={chat.limitReached}
        />
      </div>
    </div>
  );
}
