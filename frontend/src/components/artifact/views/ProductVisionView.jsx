import { ArtifactTable } from "../ArtifactTable";

export default function ProductVisionView({ data }) {
  const targetAudienceCol = [
    {
      title: "Role",
      displayValue: (dat) => dat.role,
    },
    {
      title: "Type",
      displayValue: (dat) => dat.type,
    },
    {
      title: "Key Concern",
      displayValue: (dat) => dat.key_concern,
    },
    {
      title: "Influence Level",
      displayValue: (dat) => dat.influence_level,
    },
  ];

  const assumptionsCol = [
    {
      title: "Statement",
      displayValue: (dat) => dat.statement,
    },
    {
      title: "Risk If Wrong",
      displayValue: (dat) => dat.risk_if_wrong,
    },
    {
      title: "Needs validation",
      displayValue: (dat) => (dat.needs_validation ? "Yes" : "No"),
    },
  ];

  return (
    <div className="h-full overflow-auto">
      <ArtifactTable
        column={targetAudienceCol}
        data={data.target_audiences ?? []}
        tableTitle="Target Audiences"
      />

      {data?.core_problem && (
        <div className="px-4 pb-4">
          <div className="bg-[#F5F1EA] border border-[#E8E3D9] rounded-xl p-3">
            <div className="text-[10.5px] font-semibold text-[#8A7F72] mb-1">
              📝 Core Problem
            </div>
            <div className="text-[10.5px] text-[#8A7F72] leading-relaxed">
              {data.core_problem}
            </div>
          </div>
        </div>
      )}

      {data?.value_proposition && (
        <div className="px-4 pb-4">
          <div className="bg-[#F5F1EA] border border-[#E8E3D9] rounded-xl p-3">
            <div className="text-[10.5px] font-semibold text-[#8A7F72] mb-1">
              📝 Value Proposition
            </div>
            <div className="text-[10.5px] text-[#8A7F72] leading-relaxed">
              {data.value_proposition}
            </div>
          </div>
        </div>
      )}

      {data?.hard_constraints && (
        <div className="px-4 pb-3">
          {data.hard_constraints?.length > 0 && (
            <div className="bg-amber-50 border border-amber-200 rounded-xl p-3 mb-2">
              <div className="text-[10.5px] font-semibold text-amber-700 mb-1.5">
                ⚠ Hard Constraints
              </div>
              {data.hard_constraints.map((w, i) => (
                <div
                  key={i}
                  className="text-[10.5px] text-amber-600 flex gap-2"
                >
                  <span>•</span>
                  <span>{w}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      <ArtifactTable
        column={assumptionsCol}
        data={data.assumptions ?? []}
        tableTitle="Assumptions"
      />

      {data?.core_workflows && (
        <div className="px-4 pb-3">
          {data.core_workflows?.length > 0 && (
            <div className="bg-amber-50 border border-amber-200 rounded-xl p-3 mb-2">
              <div className="text-[10.5px] font-semibold text-amber-700 mb-1.5">
                ⚠ Core Workflows
              </div>
              {data.core_workflows.map((w, i) => (
                <div
                  key={i}
                  className="text-[10.5px] text-amber-600 flex gap-2"
                >
                  <span>•</span>
                  <span>{w}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {data?.out_of_scope && (
        <div className="px-4 pb-3">
          {data.out_of_scope?.length > 0 && (
            <div className="bg-amber-50 border border-amber-200 rounded-xl p-3 mb-2">
              <div className="text-[10.5px] font-semibold text-amber-700 mb-1.5">
                ⚠ Out Of Scope
              </div>
              {data.out_of_scope.map((w, i) => (
                <div
                  key={i}
                  className="text-[10.5px] text-amber-600 flex gap-2"
                >
                  <span>•</span>
                  <span>{w}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
