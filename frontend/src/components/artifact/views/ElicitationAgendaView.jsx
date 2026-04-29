import { ArtifactTable } from "../ArtifactTable";

export function ElicitationAgendaView({ data }) {
  const elicitationAgendaCol = [
    {
      title: "Item ID",
      displayValue: (dat) => dat.item_id,
    },
    {
      title: "Source Field",
      displayValue: (dat) => dat.source_field,
    },
    {
      title: "Source Reference",
      displayValue: (dat) => dat.source_ref,
    },
    {
      title: "Elicitation Goal",
      displayValue: (dat) => dat.elicitation_goal,
    },
    {
      title: "Priority",
      displayValue: (dat) => dat.priority,
    },
  ];

  return (
    <div className="h-full overflow-auto">
      <ArtifactTable column={elicitationAgendaCol} data={data.items ?? []} />
    </div>
  );
}
