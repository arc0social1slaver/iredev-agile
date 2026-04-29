// src/components/artifact/views/InterviewRecordView.jsx
// Hiển thị interview record với 2 tab: Transcript và Requirements

import { FormattedText } from "../../chat/FormattedText";
import { ArtifactTable } from "../ArtifactTable";

// ── Tab: Transcript ──────────────────────────────────────────────────────────
export function TranscriptView({ data }) {
  const conversation = data?.conversation || [];

  if (!conversation.length) {
    return (
      <div className="flex items-center justify-center h-full text-[#B5ADA4] text-[13px]">
        No conversation recorded.
      </div>
    );
  }

  return (
    <div className="h-full overflow-auto p-5 space-y-4">
      {/* Header */}
      <div className="pb-3 border-b border-[#E8E3D9]">
        <h3 className="text-[13px] font-semibold text-[#1A1410]">
          Interview Transcript
        </h3>
        <p className="text-[11px] text-[#8A7F72] mt-0.5">
          {conversation.length} turns · Completeness:{" "}
          {((data?.completeness_score || 0) * 100).toFixed(0)}%
        </p>
      </div>

      {/* Messages */}
      {conversation.map((turn, i) => {
        const isInterviewer = turn.role === "interviewer";
        return (
          <div
            key={i}
            className={`flex gap-3 ${isInterviewer ? "" : "justify-end"}`}
          >
            {isInterviewer && (
              <div className="w-7 h-7 rounded-full bg-[#C96A42] flex items-center justify-center flex-shrink-0 mt-0.5">
                <span className="text-white text-[9px] font-bold">AI</span>
              </div>
            )}
            <div
              className={`max-w-[80%] rounded-xl px-3.5 py-2.5 text-[12.5px] leading-relaxed ${
                isInterviewer
                  ? "bg-[#F5F1EA] text-[#1A1410] border border-[#E8E3D9]"
                  : "bg-[#EAE6DC] text-[#1A1410]"
              }`}
            >
              <div className="font-semibold text-[10px] uppercase tracking-wide mb-1 opacity-60">
                {isInterviewer ? "Interviewer" : "Stakeholder"}
              </div>
              {turn.content}
            </div>
            {!isInterviewer && (
              <div className="w-7 h-7 rounded-full bg-[#8A7F72] flex items-center justify-center flex-shrink-0 mt-0.5">
                <span className="text-white text-[9px] font-bold">S</span>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ── Tab: Requirements ────────────────────────────────────────────────────────
export function RequirementsView({ data }) {
  const requirements = data?.requirements || [];

  const byType = {
    functional: requirements.filter((r) => r.req_type === "functional"),
    non_functional: requirements.filter((r) => r.req_type === "non_functional"),
    constraint: requirements.filter((r) => r.req_type === "constraint"),
  };

  const PRIORITY_COLORS = {
    high: "bg-red-50 text-red-600 border-red-200",
    medium: "bg-amber-50 text-amber-600 border-amber-200",
    low: "bg-green-50 text-green-600 border-green-200",
  };

  const TYPE_LABELS = {
    functional: {
      label: "Functional",
      color: "bg-[#F5EDE8] text-[#C96A42] border-[#EDD9CE]",
    },
    non_functional: {
      label: "Non-Functional",
      color: "bg-blue-50 text-blue-600 border-blue-200",
    },
    constraint: {
      label: "Constraint",
      color: "bg-purple-50 text-purple-600 border-purple-200",
    },
    out_of_scope: {
      label: "Out of Scope",
      color: "bg-purple-50 text-purple-600 border-purple-200",
    },
  };

  if (!requirements.length) {
    return (
      <div className="flex items-center justify-center h-full text-[#B5ADA4] text-[13px]">
        No requirements extracted yet.
      </div>
    );
  }

  return (
    <div className="h-full overflow-auto">
      {/* Stats bar */}
      <div className="sticky top-0 bg-[#FAF7F3] border-b border-[#E8E3D9] px-4 py-2.5 flex items-center gap-4 z-10">
        <span className="text-[11px] text-[#8A7F72]">
          <span className="font-semibold text-[#1A1410]">
            {requirements.length}
          </span>{" "}
          total
        </span>
        {Object.entries(byType).map(
          ([type, reqs]) =>
            reqs.length > 0 && (
              <span key={type} className="text-[11px] text-[#8A7F72]">
                <span className="font-semibold text-[#1A1410]">
                  {reqs.length}
                </span>{" "}
                {TYPE_LABELS[type]?.label}
              </span>
            ),
        )}
        <span className="ml-auto text-[11px] text-[#8A7F72]">
          Completeness:{" "}
          <span className="font-semibold text-[#C96A42]">
            {((data?.completeness_score || 0) * 100).toFixed(0)}%
          </span>
        </span>
      </div>

      {/* Requirements table */}
      <div className="px-4 py-3">
        <table className="w-full text-[12px] border-collapse">
          <thead>
            <tr className="text-left border-b border-[#E8E3D9]">
              <th className="py-2 pr-3 font-semibold text-[#8A7F72] w-[72px]">
                ID
              </th>
              <th className="py-2 pr-3 font-semibold text-[#8A7F72] w-[100px]">
                Type
              </th>
              <th className="py-2 pr-3 font-semibold text-[#8A7F72]">
                Description
              </th>
              <th className="py-2 pr-3 font-semibold text-[#8A7F72] w-[72px]">
                Priority
              </th>
              <th className="py-2 font-semibold text-[#8A7F72] w-[80px]">
                Status
              </th>
            </tr>
          </thead>
          <tbody>
            {requirements.map((req) => (
              <tr
                key={req.req_id}
                className="border-b border-[#F0ECE6] hover:bg-[#FAF8F4] group"
              >
                <td className="py-2.5 pr-3 font-mono text-[11px] text-[#8A7F72] align-top">
                  {req.req_id}
                </td>
                <td className="py-2.5 pr-3 align-top">
                  <span
                    className={`inline-flex px-1.5 py-0.5 rounded text-[10px] font-medium border ${TYPE_LABELS[req.type]?.color}`}
                  >
                    {TYPE_LABELS[req.req_type]?.label || req.req_type}
                  </span>
                </td>
                <td className="py-2.5 pr-3 text-[#1A1410] leading-relaxed align-top">
                  <div>{req.statement}</div>
                  {req.rationale && (
                    <div className="mt-1 text-[11px] text-[#8A7F72] italic leading-relaxed hidden group-hover:block">
                      ↳ {req.rationale.slice(0, 200)}
                      {req.rationale.length > 200 ? "…" : ""}
                    </div>
                  )}
                </td>
                <td className="py-2.5 pr-3 align-top">
                  <span
                    className={`inline-flex px-1.5 py-0.5 rounded text-[10px] font-medium border ${PRIORITY_COLORS[req.priority] || "bg-gray-50 text-gray-500 border-gray-200"}`}
                  >
                    {req.priority}
                  </span>
                </td>
                <td className="py-2.5 align-top">
                  <span
                    className={`text-[10px] font-medium ${
                      req.status === "confirmed"
                        ? "text-green-600"
                        : req.status === "ambiguous"
                          ? "text-amber-600"
                          : "text-[#8A7F72]"
                    }`}
                  >
                    {req.status}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Gaps */}
      {data?.gaps_identified?.length > 0 && (
        <div className="px-4 pb-4">
          <div className="bg-amber-50 border border-amber-200 rounded-xl p-3">
            <div className="text-[11px] font-semibold text-amber-700 mb-1.5">
              ⚠ Identified Gaps
            </div>
            {data.gaps_identified.map((gap, i) => (
              <div key={i} className="text-[11px] text-amber-600 flex gap-2">
                <span>•</span>
                <span>{gap}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export function InterviewRecordRequirementsView({ data }) {
  const requirements = data?.requirements_identified || [];
  console.log(requirements);

  const PRIORITY_COLORS = {
    high: "bg-red-50 text-red-600 border-red-200",
    medium: "bg-amber-50 text-amber-600 border-amber-200",
    low: "bg-green-50 text-green-600 border-green-200",
  };
  const reqColums = [
    {
      title: "ID",
      displayValue: (dat) => dat.id,
      rowStyle: "py-2.5 pr-3 font-mono text-[11px] text-[#8A7F72] align-top",
    },
    {
      title: "Question",
      displayValue: (dat) => dat.question,
    },
    {
      title: "Answer",
      displayValue: (dat) => dat.answer,
    },
    {
      title: "Priority",
      displayValue: (dat) => (
        <span
          className={`inline-flex px-1.5 py-0.5 rounded text-[10px] font-medium border ${PRIORITY_COLORS[dat.priority] || "bg-gray-50 text-gray-500 border-gray-200"}`}
        >
          {dat.priority}
        </span>
      ),
    },
  ];

  if (!requirements.length) {
    return (
      <div className="flex items-center justify-center h-full text-[#B5ADA4] text-[13px]">
        No requirements extracted yet.
      </div>
    );
  }

  return (
    <div className="h-full overflow-auto">
      {/* Stats bar */}
      <div className="sticky top-0 bg-[#FAF7F3] border-b border-[#E8E3D9] px-4 py-2.5 flex items-center gap-4 z-10">
        <span className="text-[11px] text-[#8A7F72]">
          <span className="font-semibold text-[#1A1410]">
            {requirements.length}
          </span>{" "}
          total
        </span>
      </div>

      {/* Requirements table */}
      <ArtifactTable column={reqColums} data={requirements} />

      {data?.elicitation_notes && (
        <div className="px-4 pb-4">
          <div className="bg-[#F5F1EA] border border-[#E8E3D9] rounded-xl p-3">
            <div className="text-[10.5px] font-semibold text-[#8A7F72] mb-1">
              📝 Elicitation Notes
            </div>
            <div className="text-[10.5px] text-[#8A7F72] leading-relaxed">
              {data.elicitation_notes}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
