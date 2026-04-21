// src/components/layout/ResizableDivider.jsx
// Thanh kéo giữa chat panel và artifact panel
import { GripVertical } from 'lucide-react'

export function ResizableDivider({ onMouseDown }) {
  return (
    <div
      onMouseDown={onMouseDown}
      className="relative flex-shrink-0 w-[5px] h-full
                 cursor-col-resize group z-10
                 flex items-center justify-center"
      style={{ background: 'transparent' }}
    >
      {/* Line track */}
      <div
        className="absolute inset-y-0 left-1/2 -translate-x-1/2 w-px
                   bg-[#E2DCCF] group-hover:bg-[#C96A42]
                   group-active:bg-[#B85E38]
                   transition-colors duration-150"
      />

      {/* Grip handle in the middle */}
      <div
        className="relative z-10 flex items-center justify-center
                   w-5 h-10 rounded-full
                   bg-[#EDEADF] border border-[#E2DCCF]
                   group-hover:bg-[#FDF0EA] group-hover:border-[#C96A42]
                   group-active:bg-[#F5E6DC] group-active:border-[#B85E38]
                   shadow-sm transition-all duration-150
                   opacity-0 group-hover:opacity-100"
      >
        <GripVertical size={12} className="text-[#B5ADA4] group-hover:text-[#C96A42]" />
      </div>
    </div>
  )
}