import { QueryClientProvider, type QueryClient } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";

import { ChatProvider } from "./hooks/ChatContext";
import { makeQueryClient } from "./lib/queryClient";

export function AppProviders({ children, client }: { children: ReactNode; client?: QueryClient }) {
  const [queryClient] = useState(() => client ?? makeQueryClient());
  return (
    <QueryClientProvider client={queryClient}>
      <ChatProvider>{children}</ChatProvider>
    </QueryClientProvider>
  );
}
