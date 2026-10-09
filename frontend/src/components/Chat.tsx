import { lazy, Suspense, useEffect, useRef, useState, type FormEvent } from "react";

import type { ChatMessage } from "../hooks/useChat";
import { SUGGESTIONS } from "../lib/suggestions";
import type { ChipId } from "../lib/types";

// Markdown rendering (react-markdown + GFM) is loaded with the first answer.
const Markdown = lazy(() => import("./Markdown").then((m) => ({ default: m.Markdown })));


/** The ask bar at the bottom of the main card. Enter sends; while answering it becomes Stop. */
export function AskBar({
  onSend,
  onStop,
  busy,
  disabled,
}: {
  onSend: (text: string) => void;
  onStop: () => void;
  busy: boolean;
  disabled?: boolean;
}) {
  const [text, setText] = useState("");
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (busy || disabled || !text.trim()) return;
    onSend(text);
    setText("");
  };
  return (
    <form onSubmit={submit} className="ask-bar flex items-center gap-2 p-1.5 pl-4" role="search" aria-label="Ask the AI analyst">
      <label htmlFor="ask" className="sr-only">
        Ask the AI analyst about the market
      </label>
      <input
        id="ask"
        value={text}
        onChange={(e) => setText(e.target.value)}
        maxLength={2000}
        autoComplete="off"
        disabled={disabled}
        placeholder={disabled ? "Today's questions are used up" : "Ask about today's market…"}
        className="min-w-0 flex-1 bg-transparent py-2 text-sm text-ink placeholder:text-indigo-200/60 focus:outline-none disabled:cursor-not-allowed"
      />
      {busy ? (
        <button
          type="button"
          onClick={onStop}
          className="rounded-lg border border-white/20 bg-white/10 px-4 py-2 text-sm font-semibold text-ink hover:bg-white/15"
        >
          Stop
        </button>
      ) : (
        <button
          type="submit"
          disabled={disabled || !text.trim()}
          className="rounded-lg bg-gradient-to-r from-indigo-500 to-sky-500 px-4 py-2 text-sm font-semibold text-white shadow-[0_0_20px_-4px_rgb(99_102_241)] transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50"
        >
          Ask
        </button>
      )}
    </form>
  );
}

export function SuggestionChips({ onPick, disabled }: { onPick: (id: ChipId, text: string) => void; disabled: boolean }) {
  return (
    <div className="grid gap-3 sm:grid-cols-3" role="group" aria-label="Suggested questions">
      {SUGGESTIONS.map((s) => (
        <button key={s.id} type="button" className="chip px-4 py-3" disabled={disabled} onClick={() => onPick(s.id, s.text)}>
          {s.text}
        </button>
      ))}
    </div>
  );
}

function Thumb({ up, pressed, onClick }: { up: boolean; pressed: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      aria-pressed={pressed}
      aria-label={up ? "Helpful answer" : "Not helpful"}
      onClick={onClick}
      className={`rounded-md p-1.5 transition ${pressed ? "bg-sky-400/20 text-sky-200" : "text-ink-3 hover:bg-white/10 hover:text-ink"}`}
    >
      <svg viewBox="0 0 24 24" className={`h-4 w-4 ${up ? "" : "rotate-180"}`} fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
        <path strokeLinecap="round" strokeLinejoin="round" d="M7 10v11H3V10h4zm0 0l4-7a2 2 0 012 2v4h5.5a2 2 0 012 2.3l-1.3 7A2 2 0 0117.2 21H7" />
      </svg>
    </button>
  );
}

function AssistantMessage({ m, onRate }: { m: ChatMessage; onRate: (r: "up" | "down") => void }) {
  return (
    <div className="max-w-[46rem]">
      {m.tool && (
        <p role="status" className="mb-1 flex items-center gap-2 text-xs text-sky-200">
          <span className="h-2 w-2 animate-pulse rounded-full bg-sky-300" aria-hidden="true" />
          {m.tool}
        </p>
      )}
      {m.status === "streaming" && !m.text && !m.tool && (
        <p role="status" className="text-sm text-ink-3">
          Thinking…
        </p>
      )}
      {m.text && (
        <Suspense fallback={<p className="prose-ai whitespace-pre-wrap">{m.text}</p>}>
          <Markdown text={m.text} />
        </Suspense>
      )}
      {m.status === "stopped" && <p className="mt-1 text-xs text-ink-3">Stopped.</p>}
      {m.status === "error" && m.error && (
        <div role="alert" className="mt-1 rounded-xl border border-crisis/40 bg-crisis/10 px-3 py-2 text-sm">
          <p className="text-ink">{m.error.message}</p>
          <p className="mt-0.5 font-mono text-[0.7rem] text-ink-3">
            {m.error.code}
            {m.error.requestId ? ` · Reference: ${m.error.requestId}` : ""}
          </p>
        </div>
      )}
      {m.status === "done" && (
        <div className="mt-1.5 flex items-center gap-2">
          <span className="text-[0.7rem] text-ink-3">{m.label ?? "AI-generated · educational only"}</span>
          {m.messageId !== undefined && (
            <span className="flex">
              <Thumb up pressed={m.rating === "up"} onClick={() => onRate("up")} />
              <Thumb up={false} pressed={m.rating === "down"} onClick={() => onRate("down")} />
            </span>
          )}
        </div>
      )}
    </div>
  );
}

/** The conversation box under the chips (CHAT-01..05, 09). */
export function ChatThread({
  messages,
  onRate,
  onReset,
  quotaLeft,
  limitReached,
}: {
  messages: ChatMessage[];
  onRate: (id: string, r: "up" | "down") => void;
  onReset: () => void;
  quotaLeft: number | null;
  limitReached: string | null;
}) {
  const end = useRef<HTMLDivElement>(null);
  const last = messages[messages.length - 1];
  useEffect(() => {
    end.current?.scrollIntoView?.({ block: "nearest", behavior: "smooth" });
  }, [messages.length, last?.status]);

  return (
    <section className="outline-box p-4 sm:p-6" aria-labelledby="chat-title">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="chat-title" className="text-sm font-semibold text-ink">
          AI analyst
        </h2>
        <div className="flex items-center gap-3 text-xs text-ink-3">
          {quotaLeft !== null && <span>{quotaLeft} questions left today</span>}
          {messages.length > 0 && (
            <button type="button" onClick={onReset} className="underline underline-offset-2 hover:text-ink">
              New conversation
            </button>
          )}
        </div>
      </div>

      {limitReached && (
        <div role="alert" className="mt-3 rounded-xl border border-warn/40 bg-warn/10 px-3 py-2 text-sm text-ink">
          {limitReached} Suggested questions that were already answered today may still work.
        </div>
      )}

      <div className="mt-3 space-y-5" aria-live="polite" aria-busy={last?.status === "streaming"}>
        {messages.length === 0 ? (
          <p className="py-4 text-sm leading-relaxed text-ink-3">
            Ask anything about today's regime, past market phases or a term like "India VIX". Answers use MarketMood's
            data and say which date they are from. You can ask 10 questions a day.
          </p>
        ) : (
          messages.map((m) =>
            m.role === "user" ? (
              <div key={m.id} className="flex justify-end">
                <p className="max-w-[85%] rounded-2xl rounded-br-md bg-indigo-500/25 px-4 py-2 text-sm text-ink">{m.text}</p>
              </div>
            ) : (
              <AssistantMessage key={m.id} m={m} onRate={(r) => onRate(m.id, r)} />
            ),
          )
        )}
        <div ref={end} />
      </div>
    </section>
  );
}
