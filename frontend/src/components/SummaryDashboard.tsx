import type { NormalizedExtractionResult } from "../types";

export default function SummaryDashboard(props: {
  result: NormalizedExtractionResult;
  sheetSummary: unknown;
}) {
  const { result } = props;
  const errors = result.validationIssues.filter((i) => i.severity === "error").length;
  const warnings = result.validationIssues.filter((i) => i.severity === "warning").length;
  const avgConfidence =
    result.hotelRows.length > 0
      ? (
          result.hotelRows.reduce((acc, r) => acc + (r._confidence ?? 0), 0) /
          result.hotelRows.length
        ).toFixed(2)
      : "—";

  const sheets = result.workbookSummary.sheetsOrPagesProcessed;
  const hotels = result.workbookSummary.hotelSheets;
  const indices = result.workbookSummary.indexSheets;

  return (
    <>
      <div className="cards">
        <Card label="Hotels found" value={hotels.length} />
        <Card label="Hotel sheets" value={hotels.length} />
        <Card label="Index sheets" value={indices.length} />
        <Card label="Hotel rows" value={result.hotelRows.length} />
        <Card
          label="Dynamic child columns"
          value={result.dynamicColumns.childColumns.length}
        />
        <Card label="Extraction notes" value={result.extractionNotes.length} />
        <Card
          label="Validation errors"
          value={errors}
          tone={errors > 0 ? "error" : undefined}
        />
        <Card
          label="Validation warnings"
          value={warnings}
          tone={warnings > 0 ? "warning" : undefined}
        />
        <Card label="Avg confidence" value={avgConfidence} />
      </div>

      <div className="panel">
        <h3 style={{ marginTop: 0 }}>Sheet / page classification</h3>
        {sheets.length === 0 ? (
          <p className="muted">No sheets/pages classified.</p>
        ) : (
          <table className="data">
            <thead>
              <tr>
                <th>Name</th>
                <th>Classification</th>
                <th>Hotel</th>
                <th>Rows</th>
                <th>Notes</th>
              </tr>
            </thead>
            <tbody>
              {sheets.map((id) => {
                const isHotel = hotels.includes(id);
                const isIndex = indices.includes(id);
                const rowsHere = result.hotelRows.filter(
                  (r) => r.sourceSheetOrPage === id
                ).length;
                const notesHere = result.extractionNotes.filter(
                  (n) => n.Page === id
                ).length;
                return (
                  <tr key={id}>
                    <td>{id}</td>
                    <td>
                      <span
                        className={
                          "badge " +
                          (isHotel ? "success" : isIndex ? "info" : "warning")
                        }
                      >
                        {isHotel
                          ? "hotel_contract"
                          : isIndex
                          ? "index_reference"
                          : "other"}
                      </span>
                    </td>
                    <td>
                      {result.hotelRows.find((r) => r.sourceSheetOrPage === id)
                        ?.["Hotel Name"] ?? "—"}
                    </td>
                    <td>{rowsHere}</td>
                    <td>{notesHere}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      <div className="panel">
        <h3 style={{ marginTop: 0 }}>Dynamic child columns</h3>
        {result.dynamicColumns.childColumns.length === 0 ? (
          <p className="muted">No dynamic child columns detected.</p>
        ) : (
          <table className="data">
            <thead>
              <tr>
                <th>Key</th>
                <th>Age from</th>
                <th>Age to</th>
                <th>Position</th>
                <th>Value type</th>
              </tr>
            </thead>
            <tbody>
              {result.dynamicColumns.childColumns.map((c) => (
                <tr key={c.key}>
                  <td>
                    <strong>{c.key}</strong>
                  </td>
                  <td>{c.ageFrom ?? "—"}</td>
                  <td>{c.ageTo ?? "—"}</td>
                  <td>{c.childPosition ?? "—"}</td>
                  <td>{c.valueType}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}

function Card({
  label,
  value,
  tone,
}: {
  label: string;
  value: number | string;
  tone?: "error" | "warning" | "success";
}) {
  return (
    <div className="card">
      <div className="label">{label}</div>
      <div
        className={
          "value " +
          (tone === "error"
            ? "error-text"
            : tone === "warning"
            ? "warning-text"
            : tone === "success"
            ? "success-text"
            : "")
        }
      >
        {value}
      </div>
    </div>
  );
}
