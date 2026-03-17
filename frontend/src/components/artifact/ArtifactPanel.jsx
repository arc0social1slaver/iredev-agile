// src/components/artifact/ArtifactPanel.jsx
// =============================================================================
// Right-side panel showing an artifact with:
//   - Preview / Code tabs
//   - Copy + Download + Close toolbar
//   - Feedback bar (Accept / Request changes) when awaitingFeedback is true
//   - "Accepted" banner when the artifact has been finalized
// =============================================================================
import { useState } from 'react'
import { Copy, Check, Download, X } from 'lucide-react'
import { Tooltip }              from '../ui'
import { ArtifactCodeView }     from './ArtifactCodeView'
import { ArtifactPreviewView }  from './ArtifactPreviewView'
import { ArtifactFeedbackBar }  from './ArtifactFeedbackBar'

const TABS = ['preview', 'code']

export function ArtifactPanel({ artifact, onClose, onAccept, onRevise }) {
  const [tab,    setTab]    = useState('preview')
  const [copied, setCopied] = useState(false)

  function handleCopy() {
    navigator.clipboard?.writeText(artifact.content)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  function handleDownload() {
    const ext  = { react:'jsx', html:'html', code:'js', markdown:'md', svg:'svg' }[artifact.type] ?? 'txt'
    const blob = new Blob([artifact.content], { type: 'text/plain' })
    const url  = URL.createObjectURL(blob)
    const a    = Object.assign(document.createElement('a'), {
      href: url,
      download: `${artifact.title.replace(/\s+/g, '-').toLowerCase()}.${ext}`
    })
    a.click()
    URL.revokeObjectURL(url)
  }

  const iconBtn = "w-7 h-7 flex items-center justify-center rounded-md " +
                  "text-[#8A7F72] hover:text-[#1A1410] hover:bg-[#EAE6DC] transition-colors"

  return (
    <div className="flex flex-col h-full bg-white panel-enter">

      {/* ── Header ─────────────────────────────────────────────────────── */}
      <div className="flex items-center gap-3 px-4 h-[52px]
                      border-b border-[#E8E3D9] bg-[#F9F7F3] flex-shrink-0">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-[13px] font-semibold text-[#1A1410] truncate leading-tight">
              {artifact.title}
            </span>
            {/* Version badge */}
            {artifact.iteration && (
              <span className="px-1.5 py-0.5 bg-[#EAE6DC] rounded text-[10px]
                               font-medium text-[#8A7F72] flex-shrink-0">
                v{artifact.iteration}
              </span>
            )}
            {/* Accepted badge */}
            {artifact.accepted && (
              <span className="flex items-center gap-1 px-1.5 py-0.5
                               bg-green-50 border border-green-200
                               rounded text-[10px] font-medium text-green-700 flex-shrink-0">
                <Check size={9} /> Accepted
              </span>
            )}
          </div>
          <div className="text-[10.5px] text-[#8A7F72] capitalize leading-tight">
            {artifact.type}
            {artifact.awaitingFeedback && (
              <span className="ml-1.5 text-[#C96A42]">· awaiting feedback</span>
            )}
          </div>
        </div>

        <div className="flex items-center gap-0.5">
          <Tooltip text={copied ? 'Copied!' : 'Copy code'}>
            <button onClick={handleCopy} className={iconBtn}>
              {copied ? <Check size={14} /> : <Copy size={14} />}
            </button>
          </Tooltip>
          <Tooltip text="Download">
            <button onClick={handleDownload} className={iconBtn}>
              <Download size={14} />
            </button>
          </Tooltip>
          <div className="w-px h-4 bg-[#E8E3D9] mx-0.5" />
          <Tooltip text="Close">
            <button onClick={onClose} className={iconBtn}>
              <X size={14} />
            </button>
          </Tooltip>
        </div>
      </div>

      {/* ── Tab bar ────────────────────────────────────────────────────── */}
      <div className="flex gap-1 px-4 border-b border-[#E8E3D9] bg-[#F9F7F3] flex-shrink-0">
        {TABS.map(t => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-3 py-2.5 text-[12px] font-medium capitalize
                        border-b-2 -mb-px transition-colors ${
                          t === tab
                            ? 'border-[#C96A42] text-[#C96A42]'
                            : 'border-transparent text-[#8A7F72] hover:text-[#1A1410]'
                        }`}
          >
            {t}
          </button>
        ))}
      </div>

      {/* ── Body ───────────────────────────────────────────────────────── */}
      <div className="flex-1 overflow-auto">
        {tab === 'code'
          ? <ArtifactCodeView content={artifact.content} language={artifact.language} />
          : <ArtifactPreviewView artifact={artifact} />}
      </div>

      {/* ── Feedback bar — shown while backend is waiting for response ── */}
      {artifact.awaitingFeedback && !artifact.accepted && onAccept && onRevise && (
        <ArtifactFeedbackBar
          artifactId={artifact.id}
          iteration={artifact.iteration  ?? 1}
          maxIter={artifact.maxIterations ?? 5}
          onAccept={onAccept}
          onRevise={onRevise}
        />
      )}
    </div>
  )
}