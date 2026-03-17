// src/context/ChatContext.jsx
// ─────────────────────────────────────────────────────────────────────────────
// Wraps useChat() in React Context so any component in the tree can access
// chat state without prop-drilling through Sidebar → App → MessageBubble etc.
//
// Usage in any component:
//   const { messages, sendMessage, streaming } = useChat()
//   (import useChat from this file, not from hooks/useChat.js directly)
//
// The actual state logic stays in hooks/useChat.js — this file is just the
// context plumbing that makes it globally accessible.
// ─────────────────────────────────────────────────────────────────────────────
import { createContext, useContext } from 'react'
import { useChat as useChatHook }   from '../hooks/useChat'

// ── Context definition ────────────────────────────────────────────────────────
const ChatContext = createContext(null)

// ── Provider component ────────────────────────────────────────────────────────
// Place this inside <AuthProvider> in main.jsx (after auth is confirmed).
export function ChatProvider({ children }) {
  // Run the hook once here — its state is shared with all consumers
  const chat = useChatHook()

  return <ChatContext.Provider value={chat}>{children}</ChatContext.Provider>
}

// ── Hook ──────────────────────────────────────────────────────────────────────
// Re-export as useChat so components import from one place and don't
// need to know whether state comes from a hook or context.
export function useChat() {
  const ctx = useContext(ChatContext)
  if (!ctx) throw new Error('useChat must be used inside <ChatProvider>')
  return ctx
}