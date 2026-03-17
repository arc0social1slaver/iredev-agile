// src/components/ui/Modal.jsx
// ─────────────────────────────────────────────────────────────────────────────
// Accessible modal dialog with backdrop, keyboard (Escape) dismiss, and
// a slide-up animation. Used by SettingsModal and any future dialogs.
//
// Usage:
//   <Modal open={showSettings} onClose={() => setShowSettings(false)} title="Settings">
//     <p>Modal content here</p>
//   </Modal>
// ─────────────────────────────────────────────────────────────────────────────
import { useEffect } from 'react'
import { X }         from 'lucide-react'

export function Modal({ open, onClose, title, children, width = 'max-w-lg' }) {
  // Close on Escape key press
  useEffect(() => {
    if (!open) return
    function onKey(e) { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  // Don't render anything when closed
  if (!open) return null

  return (
    // Backdrop — clicking outside the card closes the modal
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4
                 bg-black/30 backdrop-blur-[2px]"
      onClick={onClose}
    >
      {/* Modal card — stop clicks from bubbling to backdrop */}
      <div
        className={`relative w-full ${width} bg-white rounded-2xl
                    border border-[#E8E3D9]
                    shadow-[0_24px_48px_rgba(0,0,0,0.14)]
                    animate-[modalIn_0.18s_cubic-bezier(0.16,1,0.3,1)_both]`}
        onClick={(e) => e.stopPropagation()}
        style={{ '--tw-animation': 'modalIn' }}
      >
        {/* Header */}
        {title && (
          <div className="flex items-center justify-between px-5 py-4
                          border-b border-[#F0ECE6]">
            <h2 className="text-[15px] font-semibold text-[#1A1410]">{title}</h2>
            <button
              onClick={onClose}
              className="w-7 h-7 flex items-center justify-center rounded-lg
                         text-[#8A7F72] hover:text-[#1A1410] hover:bg-[#EAE6DC]
                         transition-colors"
            >
              <X size={15} />
            </button>
          </div>
        )}

        {/* Body */}
        <div className="px-5 py-4">{children}</div>
      </div>

      {/* Inline keyframe (Tailwind doesn't have modalIn by default) */}
      <style>{`
        @keyframes modalIn {
          from { opacity: 0; transform: scale(0.96) translateY(8px); }
          to   { opacity: 1; transform: scale(1) translateY(0); }
        }
      `}</style>
    </div>
  )
}