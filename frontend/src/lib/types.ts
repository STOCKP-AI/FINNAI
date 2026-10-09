// Response shapes of the MarketMood API (docs/api.md, snapshot backend/tests/openapi.json).

export type Regime = "Bull" | "Sideways" | "Crisis";
export type Range = "60d" | "1y" | "5y" | "max";
export type ChipId = "today" | "why" | "history" | "after_crisis" | "vix";

export interface Signal {
  feature: string;
  name: string;
  value: number;
  direction: "up" | "down";
  text: string;
  contribution: number;
  percentile: number | null;
}

export interface RegimeToday {
  as_of: string;
  is_stale: boolean;
  regime: {
    label: Regime;
    raw_label: Regime;
    confidence: number;
    probabilities: { bull: number; sideways: number; crisis: number };
    days_in_regime: number;
    since: string;
  };
  signals: Signal[];
  signals_approximate: boolean;
  brief: { text: string; what_changed: string | null; source: "llm" | "template" };
  nifty: {
    as_of: string;
    close: number;
    change_pct: number | null;
    high_52w: number;
    low_52w: number;
    from_high_pct: number;
    ytd_pct: number | null;
  };
  model: { version: string; status: "validated" | "experimental" | "retired" } | null;
  disclaimer: string;
  warnings: string[];
}

export interface HistoryPoint {
  date: string;
  label: Regime;
  confidence: number;
  close: number;
}

export interface RegimeHistory {
  range: Range;
  as_of: string;
  points: HistoryPoint[];
}

export interface ApiErrorBody {
  error: { code: string; message: string; request_id: string; details?: unknown };
}

export interface ChatDone {
  message_id: number;
  session_id: string;
  usage: { in: number; out: number };
  quota_left: number | null;
  warnings: string[];
  replace_text: string | null;
  label: string;
  cached: boolean;
}
