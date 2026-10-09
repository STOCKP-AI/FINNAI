import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";

import { sseBody } from "../test/fixtures";
import { server } from "../test/server";
import { API_BASE } from "./api";
import { streamChat, type ChatHandlers } from "./chat";

function spyHandlers() {
  const log: string[] = [];
  const h: ChatHandlers = {
    onToolStart: vi.fn((label: string) => log.push(`tool:${label}`)),
    onToolEnd: vi.fn(() => log.push("tool_end")),
    onToken: vi.fn((t: string) => log.push(`token:${t}`)),
    onDone: vi.fn(() => log.push("done")),
    onError: vi.fn((e) => log.push(`error:${e.code}`)),
  };
  return { h, log };
}

const sse = (body: string) =>
  server.use(
    http.post(`${API_BASE}/v1/chat`, () => new HttpResponse(body, { headers: { "Content-Type": "text/event-stream" } })),
  );

describe("streamChat (SSE contract, docs/api.md)", () => {
  it("dispatches tool, token and done events in order and ignores pings", async () => {
    let sent: unknown;
    server.use(
      http.post(`${API_BASE}/v1/chat`, async ({ request }) => {
        sent = await request.json();
        return new HttpResponse(sseBody("Sideways today"), { headers: { "Content-Type": "text/event-stream" } });
      }),
    );
    const { h, log } = spyHandlers();
    await streamChat({ message: "Why?", session_id: "s1", chip_id: "why" }, h, new AbortController().signal);
    expect(sent).toEqual({ message: "Why?", session_id: "s1", chip_id: "why" });
    expect(log).toEqual(["tool:Checking today's regime", "tool_end", "token:Sideways ", "token:today", "done"]);
    expect(h.onDone).toHaveBeenCalledWith(expect.objectContaining({ message_id: 812, quota_left: 9 }));
  });

  it("sends only the new message: no history, no empty ids", async () => {
    let sent: unknown;
    server.use(
      http.post(`${API_BASE}/v1/chat`, async ({ request }) => {
        sent = await request.json();
        return new HttpResponse(sseBody("ok"), { headers: { "Content-Type": "text/event-stream" } });
      }),
    );
    await streamChat({ message: "hi" }, spyHandlers().h, new AbortController().signal);
    expect(sent).toEqual({ message: "hi" });
  });

  it("reports the daily limit (429 JSON before the stream)", async () => {
    server.use(
      http.post(`${API_BASE}/v1/chat`, () =>
        HttpResponse.json(
          { error: { code: "MM-QUOTA-001", message: "You have used today's 10 chats.", request_id: "r1" } },
          { status: 429 },
        ),
      ),
    );
    const { h } = spyHandlers();
    await streamChat({ message: "hi" }, h, new AbortController().signal);
    expect(h.onError).toHaveBeenCalledWith(expect.objectContaining({ code: "MM-QUOTA-001", status: 429, requestId: "r1" }));
  });

  it("reports an error event from the stream", async () => {
    sse('event: error\ndata: {"code": "MM-LLM-002", "message": "The AI analyst is busy - try again in a minute.", "session_id": "s"}\n\n');
    const { h, log } = spyHandlers();
    await streamChat({ message: "hi" }, h, new AbortController().signal);
    expect(log).toEqual(["error:MM-LLM-002"]);
  });

  it("a stream that ends without done is an error, not a silent stop", async () => {
    sse('event: token\ndata: {"text": "half"}\n\n');
    const { h, log } = spyHandlers();
    await streamChat({ message: "hi" }, h, new AbortController().signal);
    expect(log).toEqual(["token:half", "error:MM-NET-002"]);
  });

  it("an aborted request reports nothing", async () => {
    sse(sseBody("never"));
    const controller = new AbortController();
    controller.abort();
    const { h, log } = spyHandlers();
    await streamChat({ message: "hi" }, h, controller.signal);
    expect(log).toEqual([]);
  });
});
