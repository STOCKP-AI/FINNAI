import { fetchEventSource, type EventSourceMessage } from "@microsoft/fetch-event-source";

import { API_BASE, ApiError, toApiError } from "./api";
import type { ChatDone, ChipId } from "./types";

/** Callbacks for one streamed answer (SSE contract in docs/api.md: tool_start, tool_end,
 *  token, done, error; ": ping" keep-alives are comments and never reach onmessage). */
export interface ChatHandlers {
  onToolStart(label: string, tool: string): void;
  onToolEnd(tool: string, ok: boolean): void;
  onToken(text: string): void;
  onDone(done: ChatDone): void;
  onError(error: ApiError): void;
}

class FatalStreamError extends Error {}

/** POST /v1/chat and dispatch its events. Resolves when the stream ends; abort with `signal`.
 *  Never retries: a retried POST would ask the AI twice and count twice against the limit. */
export async function streamChat(
  body: { message: string; session_id?: string | null; chip_id?: ChipId | null },
  handlers: ChatHandlers,
  signal: AbortSignal,
): Promise<void> {
  if (signal.aborted) return;
  let finished = false;
  try {
    await fetchEventSource(`${API_BASE}/v1/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify({
        message: body.message,
        ...(body.session_id ? { session_id: body.session_id } : {}),
        ...(body.chip_id ? { chip_id: body.chip_id } : {}),
      }),
      signal,
      openWhenHidden: true, // keep streaming when the tab is in the background
      async onopen(res) {
        const type = res.headers.get("content-type") ?? "";
        if (res.ok && type.startsWith("text/event-stream")) return;
        throw new FatalStreamError("", { cause: await toApiError(res) });
      },
      onmessage(msg: EventSourceMessage) {
        if (!msg.event || signal.aborted) return;
        const data = msg.data ? JSON.parse(msg.data) : {};
        switch (msg.event) {
          case "tool_start":
            handlers.onToolStart(data.label ?? "Working…", data.tool);
            break;
          case "tool_end":
            handlers.onToolEnd(data.tool, data.ok !== false);
            break;
          case "token":
            handlers.onToken(String(data.text ?? ""));
            break;
          case "done":
            finished = true;
            handlers.onDone(data as ChatDone);
            break;
          case "error":
            finished = true;
            handlers.onError(new ApiError(data.code ?? "MM-LLM-003", data.message ?? "The AI analyst failed.", 200, null));
            break;
        }
      },
      onclose() {
        if (!finished) throw new FatalStreamError("closed");
      },
      onerror(err) {
        throw err; // stop fetch-event-source from reconnecting
      },
    });
  } catch (err) {
    if (signal.aborted) return;
    if (err instanceof FatalStreamError && err.cause instanceof ApiError) {
      handlers.onError(err.cause);
      return;
    }
    if (!finished) {
      handlers.onError(
        new ApiError("MM-NET-002", "The connection dropped before the answer finished. Please try again.", 0, null),
      );
    }
  }
}
