// src/components/artifact/views/ProductBacklogView.jsx
// Hiển thị product backlog dạng bảng

export function ProductBacklogView({ data }) {
  const items = data?.items || []

  const INVEST_SHORT = ['I', 'N', 'V', 'E', 'S', 'T']
  const INVEST_FULL  = ['Independent', 'Negotiable', 'Valuable', 'Estimable', 'Small', 'Testable']
  const INVEST_KEYS  = ['independent', 'negotiable', 'valuable', 'estimable', 'small', 'testable']

  const TYPE_COLORS = {
    functional:     'bg-[#F5EDE8] text-[#C96A42] border-[#EDD9CE]',
    non_functional: 'bg-blue-50 text-blue-600 border-blue-200',
    constraint:     'bg-purple-50 text-purple-600 border-purple-200',
  }

  const POINTS_COLOR = (pts) => {
    if (pts <= 3) return 'text-green-600 bg-green-50'
    if (pts <= 8) return 'text-amber-600 bg-amber-50'
    return 'text-red-600 bg-red-50'
  }

  if (!items.length) {
    return (
      <div className="flex items-center justify-center h-full text-[#B5ADA4] text-[13px]">
        No backlog items found.
      </div>
    )
  }

  const totalPoints = items.reduce((sum, item) => sum + (item.story_points || 0), 0)

  return (
    <div className="h-full overflow-auto">
      {/* Stats bar */}
      <div className="sticky top-0 bg-[#FAF7F3] border-b border-[#E8E3D9] px-4 py-2.5 flex items-center gap-4 z-10">
        <span className="text-[11px] text-[#8A7F72]">
          <span className="font-semibold text-[#1A1410]">{items.length}</span> stories
        </span>
        <span className="text-[11px] text-[#8A7F72]">
          <span className="font-semibold text-[#1A1410]">{totalPoints}</span> total pts
        </span>
        <span className="text-[11px] text-[#8A7F72] ml-auto font-mono">
          WSJF = (BV + TC + RR) / SP
        </span>
      </div>

      {/* Table */}
      <div className="px-4 py-3 overflow-x-auto">
        <table className="w-full text-[12px] border-collapse min-w-[700px]">
          <thead>
            <tr className="text-left border-b border-[#E8E3D9]">
              <th className="py-2 pr-2 font-semibold text-[#8A7F72] w-[44px]">#</th>
              <th className="py-2 pr-2 font-semibold text-[#8A7F72] w-[60px]">ID</th>
              <th className="py-2 pr-3 font-semibold text-[#8A7F72]">User Story</th>
              <th className="py-2 pr-2 font-semibold text-[#8A7F72] w-[44px] text-center">SP</th>
              <th className="py-2 pr-2 font-semibold text-[#8A7F72] w-[60px] text-center">WSJF</th>
              <th className="py-2 pr-2 font-semibold text-[#8A7F72] w-[80px]">Type</th>
              <th className="py-2 font-semibold text-[#8A7F72] w-[70px] text-center">INVEST</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => {
              const invest = item.invest || {}
              const failed = INVEST_KEYS.filter(k => !invest[k])

              return (
                <tr key={item.id} className="border-b border-[#F0ECE6] hover:bg-[#FAF8F4] group">
                  {/* Rank */}
                  <td className="py-2.5 pr-2 text-center align-top">
                    <span className="inline-flex w-5 h-5 rounded-full bg-[#EAE6DC] text-[#8A7F72] text-[10px] font-semibold items-center justify-center">
                      {item.priority_rank || '—'}
                    </span>
                  </td>

                  {/* ID */}
                  <td className="py-2.5 pr-2 font-mono text-[10.5px] text-[#8A7F72] align-top">
                    {item.id}
                  </td>

                  {/* User Story */}
                  <td className="py-2.5 pr-3 align-top">
                    <div className="font-medium text-[#1A1410] leading-snug mb-0.5">
                      {item.title}
                    </div>
                    <div className="text-[11px] text-[#8A7F72] leading-relaxed hidden group-hover:block">
                      {item.description}
                    </div>
                  </td>

                  {/* Story Points */}
                  <td className="py-2.5 pr-2 text-center align-top">
                    <span className={`inline-flex w-7 h-7 rounded-lg text-[11px] font-bold items-center justify-center ${POINTS_COLOR(item.story_points)}`}>
                      {item.story_points}
                    </span>
                  </td>

                  {/* WSJF */}
                  <td className="py-2.5 pr-2 text-center align-top">
                    <span className="font-mono text-[11px] text-[#3D3530] font-semibold">
                      {item.wsjf_score?.toFixed(1) || '—'}
                    </span>
                  </td>

                  {/* Type */}
                  <td className="py-2.5 pr-2 align-top">
                    <span className={`inline-flex px-1.5 py-0.5 rounded text-[9.5px] font-medium border ${TYPE_COLORS[item.type] || 'bg-gray-50 text-gray-500 border-gray-200'}`}>
                      {item.type === 'non_functional' ? 'NFR' : item.type === 'functional' ? 'FR' : 'CON'}
                    </span>
                  </td>

                  {/* INVEST */}
                  <td className="py-2.5 text-center align-top">
                    <div className="flex gap-[2px] justify-center" title={INVEST_FULL.join(', ')}>
                      {INVEST_KEYS.map((k, i) => (
                        <span
                          key={k}
                          title={`${INVEST_FULL[i]}: ${invest[k] ? 'Pass' : 'Fail'}`}
                          className={`inline-flex w-4 h-4 rounded text-[8px] font-bold items-center justify-center
                            ${invest[k]
                              ? 'bg-green-100 text-green-600'
                              : 'bg-red-100 text-red-500'
                            }`}
                        >
                          {INVEST_SHORT[i]}
                        </span>
                      ))}
                    </div>
                    {failed.length > 0 && (
                      <div className="text-[9px] text-red-400 mt-0.5 text-center hidden group-hover:block">
                        Fail: {failed.join(', ')}
                      </div>
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      {/* Methodology footer */}
      {data?.methodology && (
        <div className="px-4 pb-4">
          <div className="bg-[#F5F1EA] border border-[#E8E3D9] rounded-xl p-3">
            <div className="text-[10.5px] font-semibold text-[#8A7F72] mb-1.5">Methodology</div>
            <div className="grid grid-cols-2 gap-x-4 gap-y-1">
              {Object.entries(data.methodology).map(([k, v]) => (
                <div key={k} className="text-[10px] text-[#8A7F72]">
                  <span className="font-medium capitalize">{k.replace(/_/g, ' ')}: </span>
                  <span>{v}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}