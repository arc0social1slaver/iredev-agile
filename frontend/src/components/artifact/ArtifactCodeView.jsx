// src/components/artifact/ArtifactCodeView.jsx
// ─────────────────────────────────────────────────────────────────────────────
// Shows the raw source code of an artifact with line numbers.
// Rendered inside the "Code" tab of ArtifactPanel.
// ─────────────────────────────────────────────────────────────────────────────

export function ArtifactCodeView({ content, language }) {
  const lines = content.split('\n')
  return (
    <div className="h-full bg-[#F5F1EA] p-4 overflow-auto">
      <div className="mb-3">
        <span className="px-2 py-0.5 bg-[#EAE5DA] border border-[#E2DCCF]
                         rounded text-[10.5px] font-mono text-[#8A7F72]">
          {language || 'text'}
        </span>
      </div>
      <pre className="text-[12px] font-mono text-[#2D2820] leading-relaxed">
        {lines.map((line, i) => (
          <div key={i} className="flex gap-4 hover:bg-black/[0.025] px-1 rounded">
            <span className="select-none text-[#C0B8AE] text-right w-6 flex-shrink-0">
              {i + 1}
            </span>
            <span>{line || ' '}</span>
          </div>
        ))}
      </pre>
    </div>
  )
}