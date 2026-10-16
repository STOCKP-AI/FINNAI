import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "../lib/api";
import { streamChat } from "../lib/chat";
import type { ChipId } from "../lib/types";

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  text: string;
  status: "streaming" | "done" | "stopped" | "error";
  tool?: string | null; // label of the tool running right now
  label?: string; // "AI-generated · educational only"
  messageId?: number; // server id, for feedback
  sessionId?: string; // the conversation the answer belongs to (feedback must name it)
  rating?: "up" | "down";
  error?: { code: string; message: string; requestId: string | null };
}

const SESSION_KEY = "mm.chat.session";
const MESSAGES_KEY = "mm.chat.messages";
const KEEP = 20; // messages remembered in this browser for display; the server keeps the real history
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const STORED_STATUS = new Set(["done", "stopped", "error"]);

/** Today's date in India (YYYY-MM-DD): the chat limit resets at midnight IST. */
export const istToday = () => new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata" }).format(new Date());

function loadJson(key: string): unknown {
  try {
    const raw = localStorage.getItem(key);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

/** Messages saved by an earlier visit. Storage can hold anything (an older version, an extension,
 *  a manual edit), so every field is checked and anything unexpected is dropped. */
export function loadMessages(): ChatMessage[] {
  const raw = loadJson(MESSAGES_KEY);
  if (!Array.isArray(raw)) return [];
  const out: ChatMessage[] = [];
  for (const v of raw) {
    if (!v || typeof v !== "object") continue;
    const m = v as Record<string, unknown>;
    if (typeof m.id !== "string" || (m.role !== "user" && m.role !== "assistant")) continue;
    if (typeof m.text !== "string" || typeof m.status !== "string" || !STORED_STATUS.has(m.status)) continue;
    const msg: ChatMessage = { id: m.id, role: m.role, text: m.text, status: m.status as ChatMessage["status"] };
    if (typeof m.label === "string") msg.label = m.label;
    if (typeof m.messageId === "number" && Number.isInteger(m.messageId)) msg.messageId = m.messageId;
    if (typeof m.sessionId === "string" && UUID.test(m.sessionId)) msg.sessionId = m.sessionId;
    if (m.rating === "up" || m.rating === "down") msg.rating = m.rating;
    const e = m.error as Record<string, unknown> | undefined;
    if (e && typeof e === "object" && typeof e.code === "string" && typeof e.message === "string") {
      msg.error = { code: e.code, message: e.message, requestId: typeof e.requestId === "string" ? e.requestId : null };
    }
    out.push(msg);
  }
  return out.slice(-KEEP);
}

export function loadSession(): string | null {
  const raw = loadJson(SESSION_KEY);
  return typeof raw === "string" && UUID.test(raw) ? raw : null;
}

function save(key: string, value: unknown) {
  try {
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // private mode / storage full: the chat still works, it just won't survive a refresh
  }
}

let counter = 0;
const newId = () => `m${Date.now().toString(36)}${(counter++).toString(36)}`;

/** The chat state. Used once, by ChatProvider, so a running answer survives page changes. */
export function useChat() {
  const [messages, setMessages] = useState<ChatMessage[]>(loadMessages);
  const [sessionId, setSessionId] = useState<string | null>(loadSession);
  const [quota, setQuota] = useState<{ left: number; day: string } | null>(null);
  const [limit, setLimit] = useState<{ message: string; day: string } | null>(null);
  const [day, setDay] = useState(istToday);
  const abortRef = useRef<AbortController | null>(null);
  const busy = messages.some((m) => m.status === "streaming");

  useEffect(() => save(MESSAGES_KEY, messages.filter((m) => m.status !== "streaming").slice(-KEEP)), [messages]);
  useEffect(() => save(SESSION_KEY, sessionId), [sessionId]);
  useEffect(() => () => abortRef.current?.abort(), []);

  // The limit and the "questions left" counter belong to one IST day; notice midnight.
  useEffect(() => {
    if (!quota && !limit) return;
    const timer = setInterval(() => setDay(istToday()), 60_000);
    return () => clearInterval(timer);
  }, [quota, limit]);

  const patch = useCallback((id: string, change: (m: ChatMessage) => Partial<ChatMessage>) => {
    setMessages((all) => all.map((m) => (m.id === id ? { ...m, ...change(m) } : m)));
  }, []);

  const send = useCallback(
    async (text: string, chipId: ChipId | null = null) => {
      const question = text.trim();
      if (!question || busy) return;
      const answerId = newId();
      setMessages((all) => [
        ...all,
        { id: newId(), role: "user", text: question, status: "done" },
        { id: answerId, role: "assistant", text: "", status: "streaming", tool: null },
      ]);
      const controller = new AbortController();
      abortRef.current = controller;
      let settled = false;
      await streamChat(
        { message: question, session_id: sessionId, chip_id: chipId },
        {
          onToolStart: (label) => patch(answerId, () => ({ tool: label })),
          onToolEnd: () => patch(answerId, () => ({ tool: null })),
          onToken: (t) => patch(answerId, (m) => ({ text: m.text + t, tool: null })),
          onDone: (done) => {
            settled = true;
            setSessionId(done.session_id);
            if (done.quota_left !== null) setQuota({ left: done.quota_left, day: istToday() });
            patch(answerId, (m) => ({
              status: "done",
              tool: null,
              text: done.replace_text ?? m.text,
              label: done.label,
              messageId: done.message_id,
              sessionId: done.session_id,
            }));
          },
          onError: (err) => {
            settled = true;
            if (err.code === "MM-QUOTA-001") {
              setLimit({ message: err.message, day: istToday() });
              if (!chipId) setQuota({ left: 0, day: istToday() });
            }
            patch(answerId, () => ({
              status: "error",
              tool: null,
              error: { code: err.code, message: err.message, requestId: err.requestId },
            }));
          },
        },
        controller.signal,
      );
      if (controller.signal.aborted) {
        patch(answerId, (m) => (m.status === "streaming" ? { status: "stopped", tool: null } : {}));
        // The server counted the question when it started; keep the counter honest.
        if (!settled && !chipId) setQuota((q) => (q ? { ...q, left: Math.max(0, q.left - 1) } : q));
      }
      if (abortRef.current === controller) abortRef.current = null; // a newer question may own it now
    },
    [busy, patch, sessionId],
  );

  const stop = useCallback(() => abortRef.current?.abort(), []);

  const rate = useCallback(
    async (id: string, rating: "up" | "down") => {
      const msg = messages.find((m) => m.id === id);
      const session = msg?.sessionId ?? sessionId;
      if (!msg?.messageId || !session) return;
      const before = msg.rating;
      patch(id, () => ({ rating }));
      try {
        await api.feedback(session, msg.messageId, rating);
      } catch {
        patch(id, () => ({ rating: before })); // undo the highlight if it did not save
      }
    },
    [messages, patch, sessionId],
  );

  const reset = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setMessages([]);
    setSessionId(null);
  }, []);

  const quotaLeft = quota && quota.day === day ? quota.left : null;
  const limitReached = limit && limit.day === day ? limit.message : null;
  return { messages, busy, send, stop, rate, reset, quotaLeft, limitReached };
}

export type ChatState = ReturnType<typeof useChat>;
