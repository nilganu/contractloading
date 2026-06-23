import type { NormalizedExtractionResult, ValidationIssue } from "../types";

export default function ValidationIssuesTab(props: {
  result: NormalizedExtractionResult;
  onJumpToRows: () => void;
  onPatch: (next: NormalizedExtractionResult) => void;
}) {
  const { result, onJumpToRows, onPatch } = props;
  const groups: Record<string, ValidationIssue[]> = {
    error: [],
    warning: [],
    info: [],
  };
  for (const i of result.validationIssues) {
    groups[i.severity]?.push(i);
  }

  function applyQuickFix(issue: ValidationIssue) {
    if (!issue.hotelRowId || !issue.quickFixType) return;
    const next = { ...result, hotelRows: [...result.hotelRows] };
    const idx = next.hotelRows.findIndex((r) => r.id === issue.hotelRowId);
    if (idx < 0) return;
    const row = { ...next.hotelRows[idx] };
    switch (issue.quickFixType) {
      case "set_all_weekdays":
        row.Days = "0,1,2,3,4,5,6";
        break;
      case "copy_currency_to_customer":
        row["Customer Price Currency"] = row.Currency;
        break;
      case "set_default_currency":
        row.Currency = row.Currency ?? "EUR";
        break;
      case "set_default_supplier":
        row.Supplier = row.Supplier ?? "Unknown Supplier";
        break;
      default:
        return;
    }
    next.hotelRows[idx] = row;
    onPatch(next);
  }

  return (
    <>
      {(["error", "warning", "info"] as const).map((sev) => (
        <div key={sev} className="panel">
          <h3 style={{ marginTop: 0, textTransform: "capitalize" }}>
            {sev} ({groups[sev].length})
          </h3>
          {groups[sev].length === 0 ? (
            <p className="muted">None.</p>
          ) : (
            <table className="data">
              <thead>
                <tr>
                  <th>Message</th>
                  <th>Hotel</th>
                  <th>Sheet/page</th>
                  <th>Field</th>
                  <th>Row</th>
                  <th>Quick fix</th>
                </tr>
              </thead>
              <tbody>
                {groups[sev].map((i) => (
                  <tr key={i.id} className={sev === "error" ? "error" : sev === "warning" ? "warning" : ""}>
                    <td>{i.message}</td>
                    <td>{i.hotelName ?? "—"}</td>
                    <td className="muted">{i.sheetOrPage ?? "—"}</td>
                    <td>{i.field ?? "—"}</td>
                    <td>
                      {i.hotelRowId ? (
                        <button onClick={onJumpToRows}>Open</button>
                      ) : (
                        "—"
                      )}
                    </td>
                    <td>
                      {i.quickFixType ? (
                        <button onClick={() => applyQuickFix(i)}>
                          {labelForFix(i.quickFixType)}
                        </button>
                      ) : (
                        "—"
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      ))}
    </>
  );
}

function labelForFix(t: string): string {
  switch (t) {
    case "set_all_weekdays":
      return "Set Days = all week";
    case "copy_currency_to_customer":
      return "Copy Currency";
    case "set_default_currency":
      return "Default EUR";
    case "set_default_supplier":
      return "Set Supplier";
    default:
      return t;
  }
}
