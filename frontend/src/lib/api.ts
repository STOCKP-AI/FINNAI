import type { ApiErrorBody, Range, RegimeHistory, RegimeToday } from "./types";

/** Where the backend lives: VITE_API_BASE_URL at build time (see .env.example). */
export const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000").replace(/\/+$/, "");

/** An API failure the UI can explain: a code (MM-...), a message and a reference to quote. */
export class ApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly requestId: string | null;

  constructor(code: string, message: string, status: number, requestId: string | null) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.status = status;
    this.requestId = requestId;
  }
}

/** Turn a failed response into an ApiError, whatever its body looks like. */
export async function toApiError(res: Response): Promise<ApiError> {
  const requestId = res.headers.get("X-Request-ID");
  try {
    const body = (await res.json()) as ApiErrorBody;
    if (body?.error?.code) {
      return new ApiError(body.error.code, body.error.message, res.status, body.error.request_id ?? requestId);
    }
  } catch {
    // not JSON (a proxy page, an empty body): fall through
  }
  return new ApiError(`HTTP-${res.status}`, "The server returned an unexpected error.", res.status, requestId);
}

async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, { signal, headers: { Accept: "application/json" } });
  } catch (err) {
    if ((err as Error).name === "AbortError") throw err;
    throw new ApiError("MM-NET-001", "Can't reach the MarketMood server. Check your connection.", 0, null);
  }
  if (!res.ok) throw await toApiError(res);
  return (await res.json()) as T;
}

export const api = {
  today: (signal?: AbortSignal) => getJson<RegimeToday>("/v1/regime/today", signal),
  history: (range: Range, signal?: AbortSignal) =>
    getJson<RegimeHistory>(`/v1/regime/history?range=${range}`, signal),

  async feedback(sessionId: string, messageId: number, rating: "up" | "down"): Promise<void> {
    const res = await fetch(`${API_BASE}/v1/feedback`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId, message_id: messageId, rating }),
    });
    if (!res.ok) throw await toApiError(res);
  },
};
