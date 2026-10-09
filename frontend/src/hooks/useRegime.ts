import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { api } from "../lib/api";
import type { Range } from "../lib/types";

const FIVE_MINUTES = 5 * 60 * 1000;

export function useRegimeToday() {
  return useQuery({
    queryKey: ["regime", "today"],
    queryFn: ({ signal }) => api.today(signal),
    staleTime: FIVE_MINUTES,
  });
}

export function useRegimeHistory(range: Range) {
  return useQuery({
    queryKey: ["regime", "history", range],
    queryFn: ({ signal }) => api.history(range, signal),
    staleTime: FIVE_MINUTES,
    placeholderData: keepPreviousData, // keep the old chart while another range loads
  });
}

/** True once `pending` has lasted `ms` - used for "Waking up the server…" (the free host
 *  sleeps when idle, so the first request after a quiet spell can take 30 s or more). */
export function useSlow(pending: boolean, ms = 3000) {
  const [slow, setSlow] = useState(false);
  useEffect(() => {
    if (!pending) return;
    const id = setTimeout(() => setSlow(true), ms);
    return () => {
      clearTimeout(id);
      setSlow(false);
    };
  }, [pending, ms]);
  return pending && slow;
}
