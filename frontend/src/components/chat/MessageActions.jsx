// src/components/chat/MessageActions.jsx
// ─────────────────────────────────────────────────────────────────────────────
// Small row of action buttons shown below every assistant message:
//   Copy · Thumbs Up · Thumbs Down · Retry
// ─────────────────────────────────────────────────────────────────────────────
import { useState } from 'react'
import { Copy, Check, ThumbsUp, ThumbsDown, RotateCcw } from 'lucide-react'
import { Tooltip } from '../ui'

export function MessageActions({ content }) {
  const [copied, setCopied] = useState(false)
  const [rating, setRating] = useState(null) // 'up' | 'down' | null

  function handleCopy() {
    navigator.clipboard?.writeText(content)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  function toggleRating(value) {
    // Clicking the same button again clears the rating
    setRating((prev) => (prev === value ? null : value))
  }

  return (
    <div className="flex items-center gap-0.5 mt-0.5">

      {/* Copy */}
      <Tooltip text="Copy">
        <button
          onClick={handleCopy}
          className="p-1.5 rounded-md text-claude-muted hover:text-claude-dark
                     hover:bg-black/[0.06] transition-colors"
        >
          {copied ? <Check size={13} /> : <Copy size={13} />}
        </button>
      </Tooltip>

      {/* Thumbs up */}
      <Tooltip text="Good response">
        <button
          onClick={() => toggleRating('up')}
          className={`p-1.5 rounded-md hover:bg-black/[0.06] transition-colors ${
            rating === 'up'
              ? 'text-claude-orange'
              : 'text-claude-muted hover:text-claude-dark'
          }`}
        >
          <ThumbsUp size={13} />
        </button>
      </Tooltip>

      {/* Thumbs down */}
      <Tooltip text="Bad response">
        <button
          onClick={() => toggleRating('down')}
          className={`p-1.5 rounded-md hover:bg-black/[0.06] transition-colors ${
            rating === 'down'
              ? 'text-red-400'
              : 'text-claude-muted hover:text-claude-dark'
          }`}
        >
          <ThumbsDown size={13} />
        </button>
      </Tooltip>

      {/* Retry */}
      <Tooltip text="Retry">
        <button
          className="p-1.5 rounded-md text-claude-muted hover:text-claude-dark
                     hover:bg-black/[0.06] transition-colors"
        >
          <RotateCcw size={13} />
        </button>
      </Tooltip>

    </div>
  )
}