// src/components/chat/HomeScreen.jsx
// ─────────────────────────────────────────────────────────────────────────────
// Welcome / home screen shown when no conversation is active.
// Displays a greeting and a grid of quick-start prompt chips.
// Clicking a chip fires the onSend callback with its preset text.
// ─────────────────────────────────────────────────────────────────────────────
import { STARTER_PROMPTS } from '../../data/sampleData'

// Stagger class per chip index
const CHIP_ANIM = ['chip-1', 'chip-2', 'chip-3', 'chip-4']

export function HomeScreen({ onSend }) {
  return (
    <div className="flex flex-col items-center justify-center h-full px-6 pb-20 gap-0">

      {/* Greeting — no logo, matches Claude's minimal home */}
      <h1 className="text-[1.65rem] font-semibold text-[#1A1410] tracking-[-0.02em] mb-8">
        How can I help you?
      </h1>

      {/* 2×2 prompt chip grid */}
      <div className="grid grid-cols-2 gap-2.5 w-full max-w-[560px]">
        {STARTER_PROMPTS.map((p, i) => (
          <button
            key={p.id}
            onClick={() => onSend(p.text)}
            className={`
              ${CHIP_ANIM[i]}
              flex items-start gap-3 text-left
              px-4 py-3.5 rounded-xl
              bg-white border border-[#E8E3D9]
              hover:border-[#D9D3C8] hover:bg-[#FAF8F4]
              shadow-[0_1px_3px_rgba(0,0,0,0.05)]
              hover:shadow-[0_2px_6px_rgba(0,0,0,0.07)]
              transition-all duration-150
            `}
          >
            <span className="text-[18px] mt-0.5 flex-shrink-0">{p.icon}</span>
            <div>
              <div className="text-[13px] font-semibold text-[#1A1410] leading-snug">
                {p.label}
              </div>
              <div className="text-[11.5px] text-[#8A7F72] mt-0.5 leading-snug">
                {p.text}
              </div>
            </div>
          </button>
        ))}
      </div>
    </div>
  )
}