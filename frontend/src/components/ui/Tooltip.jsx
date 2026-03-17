// src/components/ui/Tooltip.jsx
// ─────────────────────────────────────────────────────────────────────────────
// Simple hover tooltip — shows a small dark label above the wrapped child.
//
// Usage:
//   <Tooltip text="Delete chat">
//     <button>...</button>
//   </Tooltip>
// ─────────────────────────────────────────────────────────────────────────────
import { useState } from 'react'

export function Tooltip({ text, children }) {
  const [show, setShow] = useState(false)
  return (
    <div
      className="relative inline-flex"
      onMouseEnter={() => setShow(true)}
      onMouseLeave={() => setShow(false)}
    >
      {children}
      {show && (
        <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2
                        px-2 py-1 text-[11px] leading-tight text-white
                        bg-[#1A1410] rounded-md whitespace-nowrap
                        pointer-events-none z-50 shadow-sm">
          {text}
          <div className="absolute top-full left-1/2 -translate-x-1/2
                          border-4 border-transparent border-t-[#1A1410]" />
        </div>
      )}
    </div>
  )
}