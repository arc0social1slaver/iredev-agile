// src/components/artifact/views/ValidatedBacklogView.jsx
// Hiển thị validated product backlog với Acceptance Criteria (Given-When-Then)
// Aligned with nested PBI schema: estimation, prioritization, planning, quality

export function ValidatedBacklogView({ data }) {
  const items = data?.items || []

  // Stats can come from top-level refinement_stats or be computed from items
  const stats = data?.refinement_stats || {}
  const computedStats = {
    total_pbis: stats.total_pbis || items.length,
    ready_pbis: stats.ready_pbis || items.filter(i =>
      (i.planning?.status ?? i.status) === 'ready'
    ).length,
    total_ac: stats.total_ac || items.reduce((sum, i) => {
      const ac = i.quality?.acceptance_criteria ?? i.acceptance_criteria ?? []
      return sum + ac.length
    }, 0),
    invest_issues: stats.invest_issues || 0,
    blockers: stats.blockers || 0,
  }

  if (!items.length) {
    return (
      <div className="flex items-center justify-center h-full text-[#B5ADA4] text-[13px]">
        No validated backlog items found.
      </div>
    )
  }

  const INVEST_KEYS  = ['independent', 'negotiable', 'valuable', 'estimable', 'small', 'testable']
  const INVEST_SHORT = ['I', 'N', 'V', 'E', 'S', 'T']

  const AC_TYPE_COLORS = {
    happy_path: 'bg-green-50 text-green-700 border-green-200',
    edge_case:  'bg-amber-50 text-amber-700 border-amber-200',
    error_case: 'bg-red-50 text-red-600 border-red-200',
  }

  return (
    <div className="h-full overflow-auto">
      {/* Stats bar */}
      <div className="sticky top-0 bg-[#FAF7F3] border-b border-[#E8E3D9] px-4 py-2.5 flex items-center gap-4 z-10 flex-wrap">
        <span className="text-[11px] text-[#8A7F72]">
          <span className="font-semibold text-[#1A1410]">{computedStats.ready_pbis}</span>/{computedStats.total_pbis} ready
        </span>
        <span className="text-[11px] text-[#8A7F72]">
          <span className="font-semibold text-[#1A1410]">{computedStats.total_ac}</span> acceptance criteria
        </span>
        {computedStats.invest_issues > 0 && (
          <span className="text-[11px] text-amber-600">
            ⚠ <span className="font-semibold">{computedStats.invest_issues}</span> INVEST issues
            {computedStats.blockers > 0 && <span className="text-red-500"> ({computedStats.blockers} blockers)</span>}
          </span>
        )}
      </div>

      {/* Per-item cards */}
      <div className="p-4 space-y-4">
        {items.map((item) => {
          // Support both nested (actual artifact) and flat (review payload) schemas
          const estimation    = item.estimation || {}
          const prioritization = item.prioritization || {}
          const planning      = item.planning || {}
          const quality       = item.quality || {}

          const storyPoints  = estimation.story_points ?? item.story_points ?? 0
          const priorityRank = prioritization.priority_rank ?? item.priority_rank
          const status       = planning.status ?? item.status ?? '—'
          const investPass   = quality.invest_pass ?? item.invest_pass
          const investFlags  = quality.invest_flags ?? item.invest_flags ?? []

          // Acceptance criteria: nested in quality or at top-level
          const ac = quality.acceptance_criteria ?? item.acceptance_criteria ?? []

          // Build INVEST map from invest_flags (list of failed criteria names)
          const investMap = {}
          INVEST_KEYS.forEach(k => {
            investMap[k] = !investFlags.includes(k)
          })

          // Also support invest_validation shape from review payload
          const iv = item.invest_validation || {}
          const ivCriteria = iv.criteria || {}
          const ivIssues = iv.issues || []
          const failed = iv.failed_criteria || investFlags

          return (
            <div key={item.id} className="border border-[#E8E3D9] rounded-xl bg-white overflow-hidden">
              {/* Item header */}
              <div className="px-4 py-3 bg-[#FAF8F4] border-b border-[#E8E3D9]">
                <div className="flex items-start gap-2">
                  <span className="font-mono text-[10.5px] text-[#8A7F72] mt-0.5 flex-shrink-0">{item.id}</span>
                  <div className="flex-1 min-w-0">
                    <div className="font-semibold text-[12.5px] text-[#1A1410] leading-snug">{item.title}</div>
                    <div className="text-[11px] text-[#8A7F72] mt-0.5 leading-relaxed">{item.description}</div>
                    {item.domain && (
                      <div className="text-[10px] text-[#B5ADA4] mt-0.5">
                        Domain: {item.domain}
                      </div>
                    )}
                  </div>
                  <div className="flex items-center gap-2 flex-shrink-0">
                    {priorityRank && (
                      <span className="inline-flex w-5 h-5 rounded-full bg-[#EAE6DC] text-[#8A7F72] text-[10px] font-semibold items-center justify-center">
                        {priorityRank}
                      </span>
                    )}
                    <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${
                      storyPoints <= 3 ? 'bg-green-100 text-green-700' :
                      storyPoints <= 8 ? 'bg-amber-100 text-amber-700' :
                      'bg-red-100 text-red-700'
                    }`}>
                      {storyPoints} pts
                    </span>
                    <span className={`text-[10px] font-medium px-2 py-0.5 rounded-full border ${
                      status === 'ready' ? 'bg-green-50 text-green-600 border-green-200' :
                      'bg-[#EAE6DC] text-[#8A7F72] border-[#E2DCCF]'
                    }`}>
                      {status.replace(/_/g, ' ')}
                    </span>
                  </div>
                </div>

                {/* INVEST chips */}
                <div className="flex items-center gap-1 mt-2">
                  <span className="text-[9.5px] text-[#B5ADA4] mr-1">INVEST:</span>
                  {INVEST_KEYS.map((k, i) => {
                    // Use invest_validation.criteria if available, else derive from invest_flags
                    const crit = ivCriteria[k] || {}
                    const pass = Object.keys(ivCriteria).length > 0
                      ? crit.pass !== false
                      : investMap[k]
                    return (
                      <span
                        key={k}
                        title={`${k}: ${crit.note || (pass ? 'Pass' : 'Fail')}`}
                        className={`inline-flex px-1.5 py-0.5 rounded text-[9px] font-semibold cursor-help ${
                          pass ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-600'
                        }`}
                      >
                        {INVEST_SHORT[i]}
                      </span>
                    )
                  })}
                  {failed.length > 0 && (
                    <span className="text-[10px] text-red-500 ml-1">({failed.length} failed)</span>
                  )}
                </div>
              </div>

              {/* INVEST issues (from invest_validation payload shape) */}
              {ivIssues.length > 0 && (
                <div className="px-4 py-2.5 bg-amber-50 border-b border-amber-100">
                  {ivIssues.map((iss, i) => (
                    <div key={i} className="flex gap-2 text-[11px] text-amber-700 py-0.5">
                      <span className={`flex-shrink-0 font-semibold ${iss.severity === 'blocker' ? 'text-red-600' : 'text-amber-600'}`}>
                        {iss.severity === 'blocker' ? '🚫' : '⚠'} {iss.criterion}:
                      </span>
                      <span>{iss.message}</span>
                      {iss.suggestion && (
                        <span className="text-amber-500 italic">→ {iss.suggestion}</span>
                      )}
                    </div>
                  ))}
                </div>
              )}

              {/* Acceptance Criteria */}
              {ac.length > 0 && (
                <div className="px-4 py-3">
                  <div className="text-[10.5px] font-semibold text-[#8A7F72] mb-2 uppercase tracking-wide">
                    Acceptance Criteria ({ac.length})
                  </div>
                  <div className="space-y-2">
                    {ac.map((criterion) => (
                      <div key={criterion.id} className="text-[11px] leading-relaxed">
                        <div className="flex items-center gap-2 mb-1">
                          <span className="font-mono text-[9.5px] text-[#B5ADA4]">{criterion.id}</span>
                          <span className={`px-1.5 py-0.5 rounded text-[9px] font-medium border ${AC_TYPE_COLORS[criterion.type] || 'bg-gray-50 text-gray-500 border-gray-200'}`}>
                            {criterion.type?.replace('_', ' ')}
                          </span>
                        </div>
                        <div className="pl-2 border-l-2 border-[#E8E3D9] space-y-0.5">
                          <div><span className="font-semibold text-[#8A7F72]">Given</span> {criterion.given}</div>
                          <div><span className="font-semibold text-[#8A7F72]">When</span> {criterion.when}</div>
                          <div><span className="font-semibold text-[#8A7F72]">Then</span> {criterion.then}</div>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* No AC warning */}
              {ac.length === 0 && (
                <div className="px-4 py-2.5 bg-gray-50 border-t border-gray-100">
                  <span className="text-[10.5px] text-[#B5ADA4] italic">No acceptance criteria defined</span>
                </div>
              )}
            </div>
          )
        })}
      </div>

      {/* Refinement summary */}
      {data?.refinement_summary && (
        <div className="px-4 pb-4">
          <div className="bg-[#F5F1EA] border border-[#E8E3D9] rounded-xl p-3">
            <div className="text-[10.5px] font-semibold text-[#8A7F72] mb-1">📝 Refinement Summary</div>
            <div className="text-[10.5px] text-[#8A7F72] leading-relaxed">{data.refinement_summary}</div>
          </div>
        </div>
      )}
    </div>
  )
}