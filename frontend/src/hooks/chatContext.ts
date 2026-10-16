import { createContext, useContext } from "react";

import type { ChatState } from "./useChat";

export const ChatContext = createContext<ChatState | null>(null);

export function useChatContext(): ChatState {
  const chat = useContext(ChatContext);
  if (!chat) throw new Error("useChatContext must be used inside <ChatProvider>");
  return chat;
}
