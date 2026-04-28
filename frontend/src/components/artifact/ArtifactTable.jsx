export function ArtifactTable({ data, column, tableTitle }) {
  return (
    <>
      {tableTitle && (
        <div className="font-bold mt-1.5 ml-3.5">{tableTitle}</div>
      )}
      <div className="px-4 py-3 overflow-x-auto">
        <table className="w-full text-[12px] border-collapse min-w-[700px]">
          <thead>
            <tr className="text-left border-b border-[#E8E3D9]">
              {column.map((val, idx) => (
                <th
                  className={
                    val.titleStyle ??
                    `py-2 pr-2 font-semibold text-[#8A7F72] w-[80px] text-center`
                  }
                >
                  {val.title}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.map((item, idx) => {
              return (
                <tr
                  key={idx}
                  className="border-b border-[#F0ECE6] hover:bg-[#FAF8F4] group"
                >
                  {/* Rank */}
                  {column.map((col, idex) => (
                    <td
                      key={idex}
                      className={
                        col.rowStyle ?? `py-2.5 pr-2 text-center align-top`
                      }
                    >
                      {col.displayValue(item) ?? item}
                    </td>
                  ))}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </>
  );
}
