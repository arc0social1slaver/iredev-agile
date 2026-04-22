// src/components/artifact/ArtifactPanel.jsx
// =============================================================================
// Right-side panel with smart tabs based on artifact type.
//
// interview_record        → tabs: Transcript, Requirements
// reviewed_interview_record → tabs: Transcript, Requirements
// product_backlog         → tabs: Backlog
// product_backlog_approved → tabs: Backlog
// validated_product_backlog → tabs: Validated Backlog
// fallback                → tabs: JSON (raw view)
// =============================================================================
import { useState, useMemo } from 'react'
import { Copy, Check, Download, X, FileText, List, ClipboardList, CheckSquare, Code2 } from 'lucide-react'
import { Tooltip } from '../ui'
import { ArtifactFeedbackBar } from './ArtifactFeedbackBar'
import { TranscriptView, RequirementsView } from './views/InterviewRecordView'
import { ProductBacklogView } from './views/ProductBacklogView'
import { ValidatedBacklogView } from './views/ValidatedBacklogView'

// ── Detect artifact type from content ────────────────────────────────────────
function detectArtifactType(artifact) {
  if (!artifact?.content) return 'unknown'

  let data = null
  try {
    data = typeof artifact.content === 'string'
      ? JSON.parse(artifact.content)
      : artifact.content
  } catch {
    return 'text'
  }

  if (!data) return 'unknown'

  // interview_record or reviewed_interview_record
  if (data.requirements_identified !== undefined && data.conversation !== undefined) {
    return 'interview_record'
  }
  // reviewed_interview_record (has status: "approved")
  if (data.requirements_identified !== undefined && data.status === 'approved') {
    return 'interview_record'
  }
  // validated_product_backlog
  if (data.items && data.refinement_stats !== undefined) {
    return 'validated_product_backlog'
  }
  // product_backlog
  if (data.items && data.methodology !== undefined) {
    return 'product_backlog'
  }
  // product_backlog_approved sentinel (same shape as product_backlog)
  if (data.items) {
    return 'product_backlog'
  }

  return 'json'
}

// ── Tab definitions per artifact type ────────────────────────────────────────
function getTabsForType(artifactType) {
  switch (artifactType) {
    case 'interview_record':
      return [
        { id: 'transcript',    label: 'Transcript',    icon: FileText },
        { id: 'requirements',  label: 'Requirements',  icon: List },
      ]
    case 'product_backlog':
      return [
        { id: 'backlog',       label: 'Backlog',       icon: ClipboardList },
      ]
    case 'validated_product_backlog':
      return [
        { id: 'validated',     label: 'Validated Backlog', icon: CheckSquare },
      ]
    default:
      return [
        { id: 'json',          label: 'JSON',          icon: Code2 },
      ]
  }
}

// ── JSON fallback view ────────────────────────────────────────────────────────
function JsonView({ content }) {
  let pretty = content
  try {
    pretty = JSON.stringify(JSON.parse(content), null, 2)
  } catch {}

  const lines = (pretty || '').split('\n')
  return (
    <div className="h-full bg-[#F5F1EA] p-4 overflow-auto">
      <pre className="text-[11.5px] font-mono text-[#2D2820] leading-relaxed">
        {lines.map((line, i) => (
          <div key={i} className="flex gap-4 hover:bg-black/[0.025] px-1 rounded">
            <span className="select-none text-[#C0B8AE] text-right w-6 flex-shrink-0">{i + 1}</span>
            <span>{line || ' '}</span>
          </div>
        ))}
      </pre>
    </div>
  )
}

// ── Main ArtifactPanel ────────────────────────────────────────────────────────
export function ArtifactPanel({ artifact, onClose, onAccept, onRevise }) {
  const artifactType = useMemo(() => detectArtifactType(artifact), [artifact?.content])
  const tabs         = useMemo(() => getTabsForType(artifactType), [artifactType])

  const [activeTab, setActiveTab] = useState(() => tabs[0]?.id)
  const [copied, setCopied]       = useState(false)

  // When artifact changes, reset tab if current tab doesn't exist in new tabs
  useMemo(() => {
    if (!tabs.find(t => t.id === activeTab)) {
      setActiveTab(tabs[0]?.id)
    }
  }, [tabs, activeTab])

  // Parse the JSON content once
  const parsedData = useMemo(() => {
    if (!artifact?.content) return null
    try {
      return typeof artifact.content === 'string'
        ? JSON.parse(artifact.content)
        : artifact.content
    } catch {
      return null
    }
  }, [artifact?.content])

  function handleCopy() {
    navigator.clipboard?.writeText(artifact.content)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  function handleDownload() {
    const blob = new Blob([artifact.content], { type: 'application/json' })
    const url  = URL.createObjectURL(blob)
    const a    = Object.assign(document.createElement('a'), {
      href:     url,
      download: `${(artifact.title || 'artifact').replace(/\s+/g, '-').toLowerCase()}.json`,
    })
    a.click()
    URL.revokeObjectURL(url)
  }

  const iconBtn =
    'w-7 h-7 flex items-center justify-center rounded-md ' +
    'text-[#8A7F72] hover:text-[#1A1410] hover:bg-[#EAE6DC] transition-colors'

  // ── Render active tab content ───────────────────────────────────────────────
  function renderTabContent() {
    switch (activeTab) {
      case 'transcript':
        return <TranscriptView data={parsedData} />
      case 'requirements':
        return <RequirementsView data={parsedData} />
      case 'backlog':
        return <ProductBacklogView data={parsedData} />
      case 'validated':
        return <ValidatedBacklogView data={parsedData} />
      case 'json':
      default:
        return <JsonView content={artifact?.content || ''} />
    }
  }

  return (
    <div className="flex flex-col h-full bg-white panel-enter">
      {/* ── Header ──────────────────────────────────────────────────────── */}
      <div className="flex items-center gap-3 px-4 h-[52px]
                      border-b border-[#E8E3D9] bg-[#F9F7F3] flex-shrink-0">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-[13px] font-semibold text-[#1A1410] truncate leading-tight">
              {artifact.title || 'Artifact'}
            </span>
            {artifact.iteration && (
              <span className="px-1.5 py-0.5 bg-[#EAE6DC] rounded text-[10px] font-medium text-[#8A7F72] flex-shrink-0">
                v{artifact.iteration}
              </span>
            )}
            {artifact.accepted && (
              <span className="flex items-center gap-1 px-1.5 py-0.5
                               bg-green-50 border border-green-200
                               rounded text-[10px] font-medium text-green-700 flex-shrink-0">
                <Check size={9} /> Accepted
              </span>
            )}
          </div>
          <div className="text-[10.5px] text-[#8A7F72] capitalize leading-tight">
            {artifactType.replace(/_/g, ' ')}
            {artifact.awaitingFeedback && (
              <span className="ml-1.5 text-[#C96A42]">· awaiting feedback</span>
            )}
          </div>
        </div>

        <div className="flex items-center gap-0.5">
          <Tooltip text={copied ? 'Copied!' : 'Copy JSON'}>
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

      {/* ── Tab bar ─────────────────────────────────────────────────────── */}
      {tabs.length > 1 && (
        <div className="flex gap-1 px-4 border-b border-[#E8E3D9] bg-[#F9F7F3] flex-shrink-0">
          {tabs.map((tab) => {
            const Icon = tab.icon
            return (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`flex items-center gap-1.5 px-3 py-2.5 text-[12px] font-medium
                            border-b-2 -mb-px transition-colors ${
                              tab.id === activeTab
                                ? 'border-[#C96A42] text-[#C96A42]'
                                : 'border-transparent text-[#8A7F72] hover:text-[#1A1410]'
                            }`}
              >
                <Icon size={12} />
                {tab.label}
              </button>
            )
          })}
        </div>
      )}

      {/* ── Body ────────────────────────────────────────────────────────── */}
      <div className="flex-1 overflow-hidden">
        {renderTabContent()}
      </div>

      {/* ── Feedback bar ────────────────────────────────────────────────── */}
      {artifact.awaitingFeedback &&
        !artifact.accepted &&
        onAccept &&
        onRevise && (
          <ArtifactFeedbackBar
            artifact={artifact}
            iteration={artifact.iteration ?? 1}
            maxIter={artifact.maxIterations ?? 5}
            onAccept={onAccept}
            onRevise={onRevise}
          />
        )}
    </div>
  )
}