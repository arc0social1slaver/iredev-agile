// src/components/sidebar/Sidebar.jsx
// ─────────────────────────────────────────────────────────────────────────────
// Left sidebar panel.
// Contains: logo, new-chat button, search box, grouped chat list, bottom nav.
// Can be collapsed down to a narrow icon-only strip.
// ─────────────────────────────────────────────────────────────────────────────
import { useState }      from 'react'
import { PanelLeftClose, PanelLeft, SquarePen, Search, Sparkles, Settings, LogOut } from 'lucide-react'
import { Tooltip }           from '../ui'
import { LoadingSpinner }    from '../ui/LoadingSpinner'
import { SettingsModal }     from '../settings/SettingsModal'
import { SidebarChatItem }   from './SidebarChatItem'
import { groupByDate }       from '../../utils/helpers'
import { useAuth }           from '../../context/AuthContext'

export function Sidebar({ chats, activeChatId, loading, onNew, onSelect, onDelete }) {
  const [query,        setQuery]        = useState('')
  const [collapsed,    setCollapsed]    = useState(false)
  const [showSettings, setShowSettings] = useState(false)

  const { user, logout } = useAuth()

  const filtered = chats.filter(c =>
    c.title.toLowerCase().includes(query.toLowerCase())
  )
  const grouped = groupByDate(filtered)

  // ── Collapsed: icon-only strip ───────────────────────────────────────────
  if (collapsed) {
    return (
      <aside className="w-[52px] h-full flex flex-col items-center
                        bg-[#EDEADF] border-r border-[#E2DCCF]
                        py-3 gap-2 flex-shrink-0">
        <Tooltip text="Expand">
          <button onClick={() => setCollapsed(false)}
                  className="w-8 h-8 flex items-center justify-center rounded-lg
                             text-[#8A7F72] hover:bg-[#E4E0D5] transition-colors">
            <PanelLeft size={16} />
          </button>
        </Tooltip>
        <Tooltip text="New chat">
          <button onClick={onNew}
                  className="w-8 h-8 flex items-center justify-center rounded-lg
                             text-[#8A7F72] hover:bg-[#E4E0D5] transition-colors">
            <SquarePen size={15} />
          </button>
        </Tooltip>
      </aside>
    )
  }

  // ── Expanded ─────────────────────────────────────────────────────────────
  return (
    <>
      <aside className="w-[260px] h-full flex flex-col flex-shrink-0
                        bg-[#EDEADF] border-r border-[#E2DCCF]">

        {/* Top: logo + collapse */}
        <div className="flex items-center justify-between px-3 pt-3 pb-2">
          <div className="flex items-center gap-2">
            <div className="w-[26px] h-[26px] rounded-full bg-[#C96A42]
                            flex items-center justify-center flex-shrink-0">
              <span className="text-white text-[10px] font-semibold">C</span>
            </div>
            <span className="text-[13px] font-semibold text-[#1A1410] tracking-[-0.01em]">
              Claude
            </span>
          </div>
          <Tooltip text="Close sidebar">
            <button onClick={() => setCollapsed(true)}
                    className="w-7 h-7 flex items-center justify-center rounded-lg
                               text-[#8A7F72] hover:bg-[#E4E0D5] transition-colors">
              <PanelLeftClose size={15} />
            </button>
          </Tooltip>
        </div>

        {/* New chat */}
        <div className="px-2 pb-1">
          <button onClick={onNew}
                  className="w-full flex items-center gap-2 px-2.5 py-1.5 rounded-lg
                             text-[13px] text-[#3D3530] hover:bg-[#E4E0D5] transition-colors">
            <SquarePen size={14} className="text-[#8A7F72]" />
            New chat
          </button>
        </div>

        {/* Search */}
        <div className="px-2 pb-2">
          <div className="relative">
            <Search size={12} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-[#B5ADA4]" />
            <input
              type="text"
              placeholder="Search your chats…"
              value={query}
              onChange={e => setQuery(e.target.value)}
              className="w-full pl-7 pr-3 py-1.5 bg-[#F4F0E6]/70 border border-[#E2DCCF]
                         rounded-lg text-[12px] text-[#1A1410] placeholder:text-[#B5ADA4]
                         focus:outline-none focus:ring-1 focus:ring-[#C96A42]/30
                         focus:border-[#C96A42]/40 transition-all"
            />
          </div>
        </div>

        {/* Chat list */}
        <div className="flex-1 overflow-y-auto px-2 pb-2">
          {/* Loading skeleton */}
          {loading && chats.length === 0 && (
            <div className="flex items-center justify-center py-8">
              <LoadingSpinner size={18} className="text-[#C96A42]" />
            </div>
          )}

          {!loading && Object.entries(grouped).map(([label, items]) => (
            <div key={label} className="mb-4">
              <div className="px-2 pb-1 text-[10.5px] font-medium text-[#A89F97] uppercase tracking-wide">
                {label}
              </div>
              {items.map(chat => (
                <SidebarChatItem
                  key={chat.id}
                  chat={chat}
                  isActive={chat.id === activeChatId}
                  onSelect={() => onSelect(chat.id)}
                  onDelete={() => onDelete(chat.id)}
                />
              ))}
            </div>
          ))}

          {!loading && filtered.length === 0 && query && (
            <p className="px-3 py-8 text-center text-xs text-[#B5ADA4]">No chats found</p>
          )}
        </div>

        {/* Bottom nav */}
        <div className="border-t border-[#E2DCCF] p-2 space-y-0.5">
          <button className="w-full flex items-center gap-2 px-2.5 py-1.5 rounded-lg
                             text-[12px] text-[#8A7F72] hover:bg-[#E4E0D5]
                             hover:text-[#3D3530] transition-colors">
            <Sparkles size={13} /> Upgrade plan
          </button>
          <button
            onClick={() => setShowSettings(true)}
            className="w-full flex items-center gap-2 px-2.5 py-1.5 rounded-lg
                       text-[12px] text-[#8A7F72] hover:bg-[#E4E0D5]
                       hover:text-[#3D3530] transition-colors">
            <Settings size={13} /> Settings
          </button>

          {/* User row */}
          <div className="flex items-center gap-2.5 px-2.5 py-2 mt-0.5 rounded-lg group">
            <div className="w-6 h-6 rounded-full bg-[#8A7F72] flex items-center
                            justify-center flex-shrink-0">
              <span className="text-white text-[10px] font-semibold">
                {(user?.name || user?.email || 'U')[0].toUpperCase()}
              </span>
            </div>
            <span className="text-[12px] text-[#3D3530] truncate flex-1">
              {user?.email || 'user@example.com'}
            </span>
            <Tooltip text="Sign out">
              <button onClick={logout}
                      className="opacity-0 group-hover:opacity-100 w-5 h-5 flex items-center
                                 justify-center rounded text-[#B5ADA4] hover:text-red-400
                                 transition-all">
                <LogOut size={12} />
              </button>
            </Tooltip>
          </div>
        </div>
      </aside>

      {/* Settings modal (rendered outside the aside so it overlays everything) */}
      <SettingsModal open={showSettings} onClose={() => setShowSettings(false)} />
    </>
  )
}