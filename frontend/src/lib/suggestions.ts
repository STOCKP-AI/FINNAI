import type { ChipId } from "./types";

/** The three chips under the card (chip ids from docs/api.md; answers are cached daily). */
export const SUGGESTIONS: { id: ChipId; text: string }[] = [
  { id: "why", text: "Why is the model showing this regime?" },
  { id: "history", text: "How has the regime changed over the last year?" },
  { id: "after_crisis", text: "What happened to NIFTY after past Crisis regimes?" },
];
