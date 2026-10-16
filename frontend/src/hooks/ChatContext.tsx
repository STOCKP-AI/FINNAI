import type { ReactNode } from "react";

import { ChatContext } from "./chatContext";
import { useChat } from "./useChat";

/** Holds the conversation above the pages, so opening "How it works" while an answer is
 *  streaming does not cancel it (the server has already counted the question). */
export function ChatProvider({ children }: { children: ReactNode }) {
  const chat = useChat();
  return <ChatContext.Provider value={chat}>{children}</ChatContext.Provider>;
}
