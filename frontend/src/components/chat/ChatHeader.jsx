// src/components/chat/ChatHeader.jsx
// ─────────────────────────────────────────────────────────────────────────────
// Top bar of the main chat area.
// Shows the active chat title (or "Claude" on the home screen),
// a model selector pill, and icon buttons for Share and New Chat.
// ─────────────────────────────────────────────────────────────────────────────
import { ChevronDown, Share2, SquarePen } from 'lucide-react'
import { Tooltip } from '../ui'

export function ChatHeader({ activeChatId, chats, onNew }) {
  const title = activeChatId
    ? (chats.find(c => c.id === activeChatId)?.title ?? 'Chat')
    : 'Claude'

  return (
    <header className="flex items-center justify-between h-[52px] px-4
                       border-b border-[#E8E3D9] bg-[#F4F0E6] flex-shrink-0">

      {/* Left: title + model pill */}
      <div className="flex items-center gap-2.5 min-w-0">
        <span className="text-[14px] font-semibold text-[#1A1410] truncate max-w-[260px]">
          {title}
        </span>

        {/* Model selector pill */}
        <button className="flex items-center gap-1 pl-2.5 pr-1.5 py-1
                           text-[12px] text-[#8A7F72] font-medium
                           bg-[#EAE6DC] hover:bg-[#E2DCCF]
                           rounded-full border border-[#DDD8CC]
                           transition-colors flex-shrink-0">
          Claude Sonnet 4
          <ChevronDown size={12} className="text-[#B5ADA4]" />
        </button>
      </div>

      {/* Right: icon actions */}
      <div className="flex items-center gap-0.5">
        <Tooltip text="Share">
          <button className="w-8 h-8 flex items-center justify-center rounded-lg
                             text-[#8A7F72] hover:bg-[#EAE6DC] hover:text-[#1A1410]
                             transition-colors">
            <Share2 size={15} />
          </button>
        </Tooltip>
        <Tooltip text="New chat">
          <button onClick={onNew}
                  className="w-8 h-8 flex items-center justify-center rounded-lg
                             text-[#8A7F72] hover:bg-[#EAE6DC] hover:text-[#1A1410]
                             transition-colors">
            <SquarePen size={15} />
          </button>
        </Tooltip>
      </div>
    </header>
  )
}