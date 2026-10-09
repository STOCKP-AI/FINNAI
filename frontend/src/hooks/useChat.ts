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
  rating?: "up" | "down";
  error?: { code: string; message: string; requestId: string | null };
}

const SESSION_KEY = "mm.chat.session";
const MESSAGES_KEY = "mm.chat.messages";
const KEEP = 20; // messages remembered in this browser for display; the server keeps the real history

function load<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
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

export function useChat() {
  const [messages, setMessages] = useState<ChatMessage[]>(() =>
    load<ChatMessage[]>(MESSAGES_KEY, []).filter((m) => m.status !== "streaming"),
  );
  const [sessionId, setSessionId] = useState<string | null>(() => load<string | null>(SESSION_KEY, null));
  const [quotaLeft, setQuotaLeft] = useState<number | null>(null);
  const [limitReached, setLimitReached] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const busy = messages.some((m) => m.status === "streaming");

  useEffect(() => save(MESSAGES_KEY, messages.filter((m) => m.status !== "streaming").slice(-KEEP)), [messages]);
  useEffect(() => save(SESSION_KEY, sessionId), [sessionId]);
  useEffect(() => () => abortRef.current?.abort(), []);

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
      await streamChat(
        { message: question, session_id: sessionId, chip_id: chipId },
        {
          onToolStart: (label) => patch(answerId, () => ({ tool: label })),
          onToolEnd: () => patch(answerId, () => ({ tool: null })),
          onToken: (t) => patch(answerId, (m) => ({ text: m.text + t, tool: null })),
          onDone: (done) => {
            setSessionId(done.session_id);
            if (done.quota_left !== null) setQuotaLeft(done.quota_left);
            patch(answerId, (m) => ({
              status: "done",
              tool: null,
              text: done.replace_text ?? m.text,
              label: done.label,
              messageId: done.message_id,
            }));
          },
          onError: (err) => {
            if (err.code === "MM-QUOTA-001") {
              setLimitReached(err.message);
              setQuotaLeft(0);
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
      }
      abortRef.current = null;
    },
    [busy, patch, sessionId],
  );

  const stop = useCallback(() => abortRef.current?.abort(), []);

  const rate = useCallback(
    async (id: string, rating: "up" | "down") => {
      const msg = messages.find((m) => m.id === id);
      if (!msg?.messageId || !sessionId) return;
      const before = msg.rating;
      patch(id, () => ({ rating }));
      try {
        await api.feedback(sessionId, msg.messageId, rating);
      } catch {
        patch(id, () => ({ rating: before })); // undo the highlight if it did not save
      }
    },
    [messages, patch, sessionId],
  );

  const reset = useCallback(() => {
    abortRef.current?.abort();
    setMessages([]);
    setSessionId(null);
  }, []);

  return { messages, busy, send, stop, rate, reset, quotaLeft, limitReached };
}
