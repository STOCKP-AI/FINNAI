import { useEffect, type ReactNode } from "react";
import { Link } from "react-router";

import { RegimeIcon } from "../components/RegimeCard";
import { REGIME_COLOR, REGIME_MEANING, REGIMES } from "../lib/format";

function Section({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <section id={id} className="panel-soft scroll-mt-6 p-5 sm:p-7" aria-labelledby={`${id}-title`}>
      <h2 id={`${id}-title`} className="text-lg font-bold tracking-tight text-ink">
        {title}
      </h2>
      <div className="mt-3 space-y-3 text-[0.95rem] leading-relaxed text-ink-2">{children}</div>
    </section>
  );
}

// Facts below come from docs/validation.md and docs/adr/0001-regime-model.md (model
// hmm-20261008-c2) and docs/evals.md (AI analyst, 9 Oct 2026). Update them with the model.
const PERIODS: { when: string; event: string; expected: string; model: string; ok: boolean }[] = [
  { when: "2017", event: "Steady low-volatility rally", expected: "Bull", model: "Bull (93% of days)", ok: true },
  { when: "Sep–Oct 2018", event: "IL&FS credit scare", expected: "Crisis or Sideways", model: "Crisis (38%)", ok: true },
  { when: "Mar–Apr 2020", event: "COVID crash", expected: "Crisis", model: "Crisis (97%)", ok: true },
  { when: "Jun 2020–Oct 2021", event: "Post-COVID bull run", expected: "Bull", model: "Sideways (71%)", ok: false },
  { when: "Jan–Jun 2022", event: "Rate hikes, Russia–Ukraine", expected: "Crisis or Sideways", model: "Sideways (63%)", ok: true },
  { when: "Apr–Dec 2023", event: "Broad rally to new highs", expected: "Bull", model: "Bull (88%)", ok: true },
];

export function HowItWorks() {
  useEffect(() => {
    document.title = "How it works · MarketMood";
  }, []);

  return (
    <div className="mx-auto max-w-3xl space-y-5 pt-8">
      <header className="text-center">
        <h1 className="text-2xl font-bold tracking-tight text-ink sm:text-3xl">How MarketMood works</h1>
        <p className="mt-2 text-ink-2">What the model does, how good it is, and what it cannot do.</p>
      </header>

      <Section id="regimes" title="Three market regimes">
        <p>
          A regime is the market's overall mood over recent weeks, not a forecast. MarketMood labels every trading day of
          the NIFTY 50 as one of three:
        </p>
        <ul className="space-y-2">
          {REGIMES.map((r) => (
            <li key={r} className="flex items-start gap-3 rounded-xl bg-white/[0.04] p-3">
              <RegimeIcon regime={r} className="mt-0.5 h-5 w-5 shrink-0" />
              <span>
                <strong className="text-ink" style={{ textDecorationColor: REGIME_COLOR[r] }}>
                  {r}
                </strong>{" "}
                - {REGIME_MEANING[r]}
              </span>
            </li>
          ))}
        </ul>
      </Section>

      <Section id="model" title="The model">
        <p>
          After each trading day, a statistical model (a 3-state Hidden Markov Model) reads eight measures of how NIFTY 50
          and India VIX have behaved - such as how much prices swing day to day, how far NIFTY is below its recent high and
          how returns compare with the risk taken.
        </p>
        <p>
          Each day's label uses only data up to that day, never anything from the future. A new regime is shown only after
          the model sees it two days in a row, so one noisy day doesn't flip the label.
        </p>
        <p>
          "What's driving this" comes from a second, simpler model trained to imitate the first (it agrees on 99% of days);
          it tells us which three measures mattered most today.
        </p>
      </Section>

      <Section id="accuracy" title="How good is it?">
        <p>
          The model is marked <strong className="text-warn">experimental</strong>: it meets most of the targets we set
          before testing, but not all. On six well-known market periods it got five right:
        </p>
        <div
          className="overflow-x-auto rounded-xl border border-white/10"
          tabIndex={0}
          role="region"
          aria-label="Reference periods table (scrolls sideways on small screens)"
        >
          <table className="w-full min-w-[34rem] text-left text-sm">
            <caption className="sr-only">Model labels for six reference periods</caption>
            <thead className="bg-white/[0.04] text-ink-3">
              <tr>
                <th className="px-3 py-2 font-medium">Period</th>
                <th className="px-3 py-2 font-medium">Expected</th>
                <th className="px-3 py-2 font-medium">Model said</th>
                <th className="px-3 py-2 font-medium">Right?</th>
              </tr>
            </thead>
            <tbody>
              {PERIODS.map((p) => (
                <tr key={p.when} className="border-t border-white/5">
                  <td className="px-3 py-2">
                    <span className="text-ink">{p.when}</span>
                    <span className="block text-xs text-ink-3">{p.event}</span>
                  </td>
                  <td className="px-3 py-2">{p.expected}</td>
                  <td className="px-3 py-2">{p.model}</td>
                  <td className="px-3 py-2">{p.ok ? "Yes" : <strong className="text-crisis">No</strong>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <ul className="list-disc space-y-1.5 pl-5">
          <li>It flagged the March 2020 crash on its first day, and changes label about four times a year.</li>
          <li>
            It is weaker at telling a calm uptrend from a flat market: it called the 2020–21 rally Sideways. Against
            objective rule-based labels it scores 0.55 (target 0.60), and a simple rule scores higher (0.66).
          </li>
          <li>
            "How sure the model is" is usually above 90%. That is the model's own estimate and it is overconfident - it is
            not the chance of the market rising or falling.
          </li>
        </ul>
      </Section>

      <Section id="ai" title="The AI analyst">
        <p>
          The analyst is a large language model (currently Google's Gemini on its free tier, with a backup model) that may
          only answer using MarketMood's own data tools: today's regime, its history, past episodes, NIFTY statistics and a
          glossary. Every number it gives should come from those tools, with its date.
        </p>
        <p>
          It never recommends stocks or funds, price targets or what you should buy, sell or hold, and it suggests a
          SEBI-registered investment adviser for personal decisions. Before release it is tested on 20 fixed questions,
          including tricky ones; on 9 Oct 2026 it scored 4.72 out of 5 with no critical failures. It can still make
          mistakes - use the thumbs down to tell us.
        </p>
        <p>
          We store questions and answers to improve the analyst. We never ask for your name, and your IP address is kept
          only as a scrambled code used for the daily limit of 10 questions.
        </p>
      </Section>

      <Section id="limits" title="What MarketMood is not">
        <ul className="list-disc space-y-1.5 pl-5">
          <li>Not investment advice, and not a SEBI-registered investment adviser or research analyst.</li>
          <li>Not a forecast: a regime describes recent weeks; past patterns may not repeat.</li>
          <li>Not live: it uses end-of-day closes, updated after each trading day.</li>
        </ul>
        <p>
          <Link to="/" className="font-semibold text-sky-300 underline underline-offset-2">
            Back to today's regime
          </Link>
        </p>
      </Section>
    </div>
  );
}
