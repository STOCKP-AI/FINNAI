import { QueryClient } from "@tanstack/react-query";

import { ApiError } from "./api";

export function makeQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        // Retry network blips once; never retry a real API answer such as 422 or 404.
        retry: (count, err) => count < 1 && (!(err instanceof ApiError) || err.status === 0 || err.status >= 502),
        refetchOnWindowFocus: false,
      },
    },
  });
}
