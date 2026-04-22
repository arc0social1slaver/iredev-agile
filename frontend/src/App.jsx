// src/App.jsx
// ─────────────────────────────────────────────────────────────────────────────
// Root component — wires all pieces together.
//
// Layout:
//   MainLayout
//   ├── Sidebar          (left, fixed width)
//   ├── Chat column      (centre, flex-1 hoặc fixed % khi artifact open)
//   ├── ResizableDivider (kéo thả, chỉ hiện khi artifact open)
//   └── ArtifactPanel    (right, fixed % width, shown only when open)
// ─────────────────────────────────────────────────────────────────────────────
import { useRef, useEffect, useState, useCallback } from 'react'
import { useChat }           from './context/ChatContext'
import { ProtectedRoute }    from './components/layout/ProtectedRoute'
import { MainLayout }        from './components/layout/MainLayout'
import { Sidebar }           from './components/sidebar/Sidebar'
import { ChatHeader }        from './components/chat/ChatHeader'
import { HomeScreen }        from './components/chat/HomeScreen'
import { MessageBubble }     from './components/chat/MessageBubble'
import { ChatInput }         from './components/chat/ChatInput'
import { ArtifactPanel }     from './components/artifact/ArtifactPanel'
import { LoadingSpinner }    from './components/ui/LoadingSpinner'
import { ErrorBanner }       from './components/ui/ErrorBanner'
import { GripVertical }      from 'lucide-react'

// ── Resizable Divider component ───────────────────────────────────────────────
function ResizableDivider({ onMouseDown }) {
  return (
    <div
      onMouseDown={onMouseDown}
      className="relative flex-shrink-0 w-[6px] h-full
                 cursor-col-resize group z-10 select-none"
    >
      {/* Track line */}
      <div className="absolute inset-y-0 left-1/2 -translate-x-1/2 w-[1px]
                      bg-[#E2DCCF] group-hover:bg-[#C96A42]
                      group-active:bg-[#C96A42]
                      transition-colors duration-150" />

      {/* Grip handle */}
      <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2
                      flex items-center justify-center
                      w-5 h-9 rounded-full
                      bg-[#EDEADF] border border-[#E2DCCF]
                      group-hover:bg-[#FDF0EA] group-hover:border-[#C96A42]
                      shadow-sm transition-all duration-150
                      opacity-0 group-hover:opacity-100">
        <GripVertical size={11} className="text-[#C0B8AE] group-hover:text-[#C96A42]" />
      </div>
    </div>
  )
}

// ── useResizable hook ─────────────────────────────────────────────────────────
function useResizable({ defaultRightPercent = 40, minRightPercent = 25, maxRightPercent = 70 } = {}) {
  const [rightPercent, setRightPercent] = useState(defaultRightPercent)
  const isDragging = useRef(false)
  const containerRef = useRef(null)

  const handleMouseDown = useCallback((e) => {
    e.preventDefault()
    isDragging.current = true
    document.body.style.userSelect = 'none'
    document.body.style.cursor = 'col-resize'
  }, [])

  useEffect(() => {
    const handleMouseMove = (e) => {
      if (!isDragging.current || !containerRef.current) return
      const rect = containerRef.current.getBoundingClientRect()
      // rightPercent = % tính từ bên phải
      const distFromRight = rect.right - e.clientX
      const newPercent = (distFromRight / rect.width) * 100
      if (newPercent >= minRightPercent && newPercent <= maxRightPercent) {
        setRightPercent(newPercent)
      }
    }
    const handleMouseUp = () => {
      if (!isDragging.current) return
      isDragging.current = false
      document.body.style.userSelect = ''
      document.body.style.cursor = ''
    }
    document.addEventListener('mousemove', handleMouseMove)
    document.addEventListener('mouseup', handleMouseUp)
    return () => {
      document.removeEventListener('mousemove', handleMouseMove)
      document.removeEventListener('mouseup', handleMouseUp)
    }
  }, [minRightPercent, maxRightPercent])

  return { rightPercent, containerRef, handleMouseDown }
}

// ── ChatLayout ────────────────────────────────────────────────────────────────
function ChatLayout() {
  const {
    chats, messages, activeChatId, streaming,
    openArtifact, loadingChats, loadingMessages,
    error, setOpenArtifact, setError,
    newChat, selectChat, deleteChat,
    sendMessage, cancelStream, sendArtifactFeedback,
    handleStartProcess, subChat,
  } = useChat()

  const bottomRef = useRef(null)
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const { rightPercent, containerRef, handleMouseDown } = useResizable({
    defaultRightPercent: 40,
    minRightPercent: 22,
    maxRightPercent: 68,
  })

  return (
    <MainLayout>
      <Sidebar
        chats={chats}
        activeChatId={activeChatId}
        loading={loadingChats}
        onNew={newChat}
        onSelect={selectChat}
        onDelete={deleteChat}
        onStart={handleStartProcess}
      />

      {/* ── Content area: chat + optional artifact ── */}
      <div ref={containerRef} className="flex flex-1 min-w-0 h-full overflow-hidden">

        {/* ── Chat column ───────────────────────────────────────────────── */}
        <div
          className="flex flex-col h-full min-w-0 bg-[#F4F0E6]"
          style={openArtifact ? { width: `${100 - rightPercent}%` } : { flex: 1 }}
        >
          <ChatHeader
            activeChatId={activeChatId}
            chats={chats}
            onNew={newChat}
            subChat={subChat}
            onSelect={selectChat}
          />
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
                {messages.map((msg) => (
                  <MessageBubble
                    key={msg.id}
                    message={msg}
                    onOpenArtifact={(art) => setOpenArtifact({ ...art, messageId: msg.id })}
                  />
                ))}
                <div ref={bottomRef} />
              </div>
            )}
          </div>

          <ChatInput
            onSend={sendMessage}
            disabled={streaming || subChat === 0}
            onCancel={cancelStream}
          />
        </div>

        {/* ── Resizable divider ─────────────────────────────────────────── */}
        {openArtifact && (
          <ResizableDivider onMouseDown={handleMouseDown} />
        )}

        {/* ── Artifact panel ────────────────────────────────────────────── */}
        {openArtifact && (
          <div
            className="h-full flex-shrink-0 border-l border-[#E8E3D9] overflow-hidden"
            style={{ width: `${rightPercent}%` }}
          >
            <ArtifactPanel
              artifact={openArtifact}
              onClose={() => setOpenArtifact(null)}
              onAccept={() => sendArtifactFeedback('accept', '')}
              onRevise={(comment) => sendArtifactFeedback('revise', comment)}
            />
          </div>
        )}
      </div>
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