// src/components/ui/ErrorBanner.jsx
// Dismissable error banner shown at the top of the chat area.
// Appears when an API call fails (send, load, delete, etc.)

import { X, AlertCircle } from 'lucide-react'

export function ErrorBanner({ message, onDismiss }) {
  if (!message) return null

  return (
    <div className="flex items-center gap-3 mx-4 mt-3 px-4 py-2.5
                    bg-red-50 border border-red-200 rounded-xl text-sm text-red-700">
      <AlertCircle size={15} className="flex-shrink-0 text-red-400" />
      <span className="flex-1">{message}</span>
      <button
        onClick={onDismiss}
        className="text-red-400 hover:text-red-600 transition-colors"
      >
        <X size={14} />
      </button>
    </div>
  )
}