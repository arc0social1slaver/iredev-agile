// src/components/sidebar/SidebarChatItem.jsx
// ─────────────────────────────────────────────────────────────────────────────
// A single row in the sidebar chat list.
// Shows the chat title, and reveals a delete button on hover.
// ─────────────────────────────────────────────────────────────────────────────
import { useState } from 'react'
import { Trash2 } from 'lucide-react'

export function SidebarChatItem({ chat, isActive, onSelect, onDelete }) {
  const [hovered, setHovered] = useState(false)

  return (
    <div
      onClick={onSelect}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      className={`
        group flex items-center gap-2 px-2.5 py-[7px] rounded-lg
        cursor-pointer text-[13px] transition-colors duration-100
        ${isActive
          ? 'bg-[#E2DDD0] text-[#1A1410]'
          : 'text-[#3D3530] hover:bg-[#E4E0D5]'}
      `}
    >
      <span className="flex-1 truncate leading-snug">{chat.title}</span>

      {/* Delete — only on hover */}
      {hovered && (
        <button
          onClick={e => { e.stopPropagation(); onDelete() }}
          className="p-0.5 rounded text-[#B5ADA4] hover:text-[#C96A42] transition-colors flex-shrink-0"
        >
          <Trash2 size={12} />
        </button>
      )}
    </div>
  )
}