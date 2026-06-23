import { useQuery } from "@tanstack/react-query";

import { getExportPreview } from "../api/client";

// Columns worth visually emphasizing — the ones reviewers most often verify.
const HIGHLIGHT = new Set<string>([
  "Hotel Name",
  "Room Name",
  "Rate Type",
  "Start Date",
  "End Date",
  "Days",
  "Meal Plan",
  "Adult 1 (SGL)",
  "Adult 2 (DBL)",
  "Adult 3 (TPL)",
  "Adult 4 (QUD)",
  "1 Pax",
  "2 Pax",
  "3 Pax",
  "4 Pax",
  "1st Child Price",
  "2nd Child Price",
  "3rd Child Price",
]);

export default function ExportPreviewTab(props: {
  jobId: string;
  exportMode: string;
}) {
  const { jobId, exportMode } = props;
  const { data, isLoading, error, refetch, isFetching } = useQuery({
    queryKey: ["export-preview", jobId, exportMode],
    queryFn: () => getExportPreview(jobId, exportMode),
  });

  return (
    <>
      <div className="panel">
        <div className="row">
          <span className="muted">
            This is exactly what the generated Excel will contain. Edit values
            in the <strong>Hotel rows</strong> tab, then refresh here to verify.
          </span>
          <div className="spacer" />
          {data && (
            <>
              <span className="badge">{data.rateType}</span>
              <span className="badge success">
                {data.rows.length} rows · {data.headers.length} cols
              </span>
            </>
          )}
          <button onClick={() => refetch()} disabled={isFetching}>
            {isFetching ? "Refreshing…" : "Refresh"}
          </button>
        </div>
      </div>

      {isLoading && <div className="panel muted">Building preview…</div>}
      {error && (
        <div className="panel" style={{ color: "var(--danger, #b00)" }}>
          Failed to build preview: {(error as Error).message}
        </div>
      )}

      {data && (
        <div className="scroll-grid">
          <table className="data">
            <thead>
              <tr>
                <th style={{ position: "sticky", left: 0 }}>#</th>
                {data.headers.map((h) => (
                  <th
                    key={h}
                    style={HIGHLIGHT.has(h) ? { background: "#eef6ff" } : undefined}
                    title={h}
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.rows.map((row, i) => (
                <tr key={i}>
                  <td style={{ position: "sticky", left: 0, background: "#fafafa" }}>
                    {i + 1}
                  </td>
                  {data.headers.map((h) => {
                    const v = row[h];
                    return (
                      <td
                        key={h}
                        style={HIGHLIGHT.has(h) ? { background: "#f5faff" } : undefined}
                      >
                        {v === null || v === undefined || v === "" ? (
                          <span className="muted">—</span>
                        ) : (
                          String(v)
                        )}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
