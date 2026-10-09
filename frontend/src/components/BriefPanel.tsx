import type { RegimeToday } from "../lib/types";
import { Waves } from "./Waves";

/** DASH-03 / DASH-04: the daily brief and the top 3 signals behind today's regime. */
export function BriefPanel({ data }: { data: RegimeToday }) {
  const signals = data.signals.slice(0, 3);
  return (
    <section className="panel-soft flex flex-col p-5" aria-labelledby="brief-title">
      <Waves className="-bottom-8 -right-16 h-32 w-72 rotate-180 opacity-60" />
      <div className="relative">
        <h2 id="brief-title" className="eyebrow">
          Today's brief
        </h2>
        <p className="mt-2 text-[0.95rem] leading-relaxed text-ink">{data.brief.text}</p>
        {data.brief.what_changed && <p className="mt-2 text-sm text-ink-2">{data.brief.what_changed}</p>}

        <h3 className="eyebrow mt-5 flex items-center gap-2">
          What's driving this
          {data.signals_approximate && (
            <span className="rounded-full bg-white/10 px-2 py-0.5 normal-case tracking-normal text-ink-2">
              approximate
            </span>
          )}
        </h3>
        <ul className="mt-2 space-y-2.5">
          {signals.map((s) => (
            <li key={s.feature} className="flex gap-3 text-sm">
              <span
                className={`mt-0.5 grid h-6 w-6 shrink-0 place-items-center rounded-md text-xs font-bold ${
                  s.direction === "up" ? "bg-sky-400/15 text-sky-300" : "bg-indigo-400/15 text-indigo-300"
                }`}
                aria-label={s.direction === "up" ? "higher than usual" : "lower than usual"}
                role="img"
              >
                {s.direction === "up" ? "↑" : "↓"}
              </span>
              <span>
                <span className="font-semibold text-ink">{s.name}</span>
                <span className="block text-ink-2">{s.text}</span>
              </span>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
