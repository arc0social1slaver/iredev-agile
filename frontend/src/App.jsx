// src/App.jsx
// ─────────────────────────────────────────────────────────────────────────────
// Root component — wires all pieces together.
//
// Layout:
//   MainLayout
//   ├── Sidebar          (left, fixed width)
//   ├── Chat column      (centre, flex-1)
//   │   ├── ChatHeader
//   │   ├── HomeScreen   (when no messages)
//   │   │   OR
//   │   │   message list (when chat is active)
//   │   └── ChatInput
//   └── ArtifactPanel    (right, fixed width, shown only when open)
// ─────────────────────────────────────────────────────────────────────────────
import { useRef, useEffect } from 'react'
import { useChat }               from './context/ChatContext'
import { ProtectedRoute }        from './components/layout/ProtectedRoute'
import { MainLayout }            from './components/layout/MainLayout'
import { Sidebar }               from './components/sidebar/Sidebar'
import { ChatHeader }            from './components/chat/ChatHeader'
import { HomeScreen }            from './components/chat/HomeScreen'
import { MessageBubble }         from './components/chat/MessageBubble'
import { ChatInput }             from './components/chat/ChatInput'
import { ArtifactPanel }         from './components/artifact/ArtifactPanel'
import { LoadingSpinner }        from './components/ui/LoadingSpinner'
import { ErrorBanner }           from './components/ui/ErrorBanner'

function ChatLayout() {
  const {
    chats, messages, activeChatId,
    streaming, openArtifact,
    loadingChats, loadingMessages, error,
    setOpenArtifact, setError,
    newChat, selectChat, deleteChat,
    sendMessage, cancelStream,
    sendArtifactFeedback,
  } = useChat()

  const bottomRef = useRef(null)
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  return (
    <MainLayout>
      <Sidebar
        chats={chats}
        activeChatId={activeChatId}
        loading={loadingChats}
        onNew={newChat}
        onSelect={selectChat}
        onDelete={deleteChat}
      />

      <div className="flex-1 flex flex-col min-w-0 h-full bg-[#F4F0E6]">
        <ChatHeader activeChatId={activeChatId} chats={chats} onNew={newChat} />
        <ErrorBanner message={error} onDismiss={() => setError(null)} />

        <div className="flex-1 overflow-y-auto">
          {loadingMessages ? (
            <div className="flex items-center justify-center h-full">
              <LoadingSpinner size={22} className="text-[#C96A42]" />
            </div>
          ) : messages.length === 0 ? (
            <HomeScreen onSend={sendMessage} />
          ) : (
            <div className="max-w-[720px] mx-auto px-6 py-8 space-y-7">
              {messages.map(msg => (
                <MessageBubble
                  key={msg.id}
                  message={msg}
                  onOpenArtifact={(art) => {
                    // Attach the messageId so feedback can reference it
                    setOpenArtifact({ ...art, messageId: msg.id })
                  }}
                />
              ))}
              <div ref={bottomRef} />
            </div>
          )}
        </div>

        <ChatInput
          onSend={sendMessage}
          disabled={streaming}
          onCancel={cancelStream}
        />
      </div>

      {openArtifact && (
        <div className="w-[500px] flex-shrink-0 h-full border-l border-[#E8E3D9]">
          <ArtifactPanel
            artifact={openArtifact}
            onClose={() => setOpenArtifact(null)}
            onAccept={() => sendArtifactFeedback('accept', '')}
            onRevise={(comment) => sendArtifactFeedback('revise', comment)}
          />
        </div>
      )}
    </MainLayout>
  )
}

export default function App() {
  return (
    <ProtectedRoute>
      <ChatLayout />
    </ProtectedRoute>
  )
}