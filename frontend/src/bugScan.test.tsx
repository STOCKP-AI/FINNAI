// Regression tests for the bug scan of 15 Oct 2026 (front end).
import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { AskBar, ChatThread } from "./components/Chat";
import { ErrorBoundary, LoadFailed } from "./components/ErrorBoundary";
import { loadMessages, loadSession, type ChatMessage } from "./hooks/useChat";
import { isChunkLoadError } from "./lib/chunk";
import { direction, formatPct, formatProb } from "./lib/format";

describe("number formatting", () => {
  it("never shows a signed zero", () => {
    expect(formatPct(-0.001)).toBe("0.00%");
    expect(formatPct(0.004)).toBe("0.00%");
    expect(formatPct(-0.006)).toBe("−0.01%");
    expect(direction(-0.001)).toBe("flat");
    expect(direction(0.01)).toBe("up");
  });

  it("does not round near-certain probabilities up to 100% (or down to 0%)", () => {
    expect(formatProb(0.9996)).toBe("99.9%");
    expect(formatProb(0.99999)).toBe("99.9%");
    expect(formatProb(1)).toBe("100.0%");
    expect(formatProb(0.0004)).toBe("0.1%");
    expect(formatProb(0)).toBe("0.0%");
    expect(formatProb(0.9949)).toBe("99%");
    expect(formatProb(0.006)).toBe("1%");
  });
});

describe("saved chat", () => {
  it.each(["{}", "null", "[null]", "[1, \"x\"]", "not json", '[{"id": 1}]'])(
    "ignores storage of the wrong shape (%s)",
    (raw) => {
      localStorage.setItem("mm.chat.messages", raw);
      expect(loadMessages()).toEqual([]);
    },
  );

  it("keeps valid messages and drops bad fields", () => {
    localStorage.setItem(
      "mm.chat.messages",
      JSON.stringify([
        { id: "a", role: "user", text: "hi", status: "done" },
        { id: "b", role: "assistant", text: "Hello", status: "done", messageId: 7, rating: "sideways", tool: "x" },
        { id: "c", role: "assistant", text: "half", status: "streaming" },
        { id: "d", role: "robot", text: "?", status: "done" },
      ]),
    );
    expect(loadMessages()).toEqual([
      { id: "a", role: "user", text: "hi", status: "done" },
      { id: "b", role: "assistant", text: "Hello", status: "done", messageId: 7 },
    ]);
  });

  it("accepts only a UUID as the session id", () => {
    localStorage.setItem("mm.chat.session", JSON.stringify({ evil: true }));
    expect(loadSession()).toBeNull();
    localStorage.setItem("mm.chat.session", JSON.stringify("1b4e28ba-2fa1-11d2-883f-0016d3cca427"));
    expect(loadSession()).toBe("1b4e28ba-2fa1-11d2-883f-0016d3cca427");
  });
});

function Harness({ onStop }: { onStop: () => void }) {
  const [busy, setBusy] = useState(false);
  return <AskBar busy={busy} onSend={() => setBusy(true)} onStop={onStop} />;
}

describe("Ask / Stop", () => {
  it("a double-click on Ask sends the question and does not stop it", () => {
    const onStop = vi.fn();
    render(<Harness onStop={onStop} />);
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "What is India VIX?" } });
    fireEvent.click(screen.getByRole("button", { name: "Ask" }), { detail: 1 });
    // the second click of the double-click lands on the Stop button that replaced Ask
    fireEvent.click(screen.getByRole("button", { name: "Stop" }), { detail: 2 });
    expect(onStop).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Stop" }), { detail: 1 }); // a deliberate click
    expect(onStop).toHaveBeenCalledTimes(1);
  });
});

describe("AI label", () => {
  it.each<ChatMessage["status"]>(["stopped", "error"])("is shown on partial AI text that was %s", (status) => {
    const messages: ChatMessage[] = [
      { id: "1", role: "user", text: "q", status: "done" },
      {
        id: "2",
        role: "assistant",
        text: "Partial answer",
        status,
        error: status === "error" ? { code: "MM-LLM-002", message: "Busy", requestId: null } : undefined,
      },
    ];
    render(<ChatThread messages={messages} onRate={vi.fn()} onReset={vi.fn()} quotaLeft={null} limitReached={null} />);
    expect(screen.getByText("AI-generated · educational only")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Helpful answer" })).toBeNull(); // no feedback without an id
  });
});

describe("error boundary", () => {
  function Broken({ error }: { error: Error }): never {
    throw error;
  }

  it("shows a reload message instead of a blank page when a chunk is missing", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    const error = new TypeError("Failed to fetch dynamically imported module: /assets/HowItWorks-abc.js");
    expect(isChunkLoadError(error)).toBe(true);
    render(
      <ErrorBoundary fallback={(e) => <LoadFailed error={e} what="this page" />}>
        <Broken error={error} />
      </ErrorBoundary>,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("A newer version of MarketMood is available.");
    expect(screen.getByRole("button", { name: "Reload" })).toBeInTheDocument();
    spy.mockRestore();
  });

  it("explains other errors too", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    render(
      <ErrorBoundary fallback={(e) => <LoadFailed error={e} what="the chart" />}>
        <Broken error={new Error("boom")} />
      </ErrorBoundary>,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("Sorry, the chart could not be shown.");
    spy.mockRestore();
  });
});
