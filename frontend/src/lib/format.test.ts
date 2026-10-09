import { renderHook } from "@testing-library/react";
import { act } from "react";
import { describe, expect, it, vi } from "vitest";

import { useSlow } from "../hooks/useRegime";
import { historyFixture } from "../test/fixtures";
import { formatDay, formatIndex, formatPct, formatProb } from "./format";
import { regimeStretches } from "./stretches";

describe("format", () => {
  it("uses Indian digit grouping and real minus signs", () => {
    expect(formatIndex(1234567.8)).toBe("12,34,567.80");
    expect(formatPct(-1.64)).toBe("−1.64%");
    expect(formatPct(0.5)).toBe("+0.50%");
    expect(formatPct(null)).toBe("—");
    expect(formatProb(0.9972)).toBe("99.7%");
    expect(formatProb(0.88)).toBe("88%");
    expect(formatDay("2026-10-08")).toBe("8 Oct 2026");
  });
});

describe("regimeStretches", () => {
  it("turns daily labels into consecutive stretches", () => {
    const s = regimeStretches(historyFixture("1y", 20).points);
    expect(s.map((x) => x.label)).toEqual(["Bull", "Crisis", "Sideways"]);
    expect(s[0]!.start).toBe("2026-07-01");
    expect(s[2]!.end).toBe("2026-07-20");
  });
});

describe("useSlow (waking-up message)", () => {
  it("turns true only after the wait and resets when done", () => {
    vi.useFakeTimers();
    const { result, rerender } = renderHook(({ p }) => useSlow(p, 3000), { initialProps: { p: true } });
    expect(result.current).toBe(false);
    act(() => vi.advanceTimersByTime(3100));
    expect(result.current).toBe(true);
    rerender({ p: false });
    expect(result.current).toBe(false);
    rerender({ p: true });
    expect(result.current).toBe(false);
    vi.useRealTimers();
  });
});
