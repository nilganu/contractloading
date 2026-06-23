import type { NormalizedExtractionResult } from "../types";

export default function ChildPoliciesTab(props: {
  result: NormalizedExtractionResult;
}) {
  const { result } = props;
  type ChildPolicyRow = Record<string, unknown> & { hotelName: string };
  const policies: ChildPolicyRow[] = (result.hotels as Array<{
    hotelName: string;
    childPolicies?: Array<Record<string, unknown>>;
  }>).flatMap((h) =>
    (h.childPolicies ?? []).map((p) => ({ ...p, hotelName: h.hotelName }))
  );

  if (policies.length === 0) {
    return (
      <div className="panel">
        <h3 style={{ marginTop: 0 }}>Child policies</h3>
        <p className="muted">
          No structured child policies were extracted. The Hotel Rows grid
          still contains dynamic CHD(...) columns for per-row child rates.
        </p>
        <p className="muted">
          Detected dynamic child columns:{" "}
          {result.dynamicColumns.childColumns.map((c) => c.key).join(", ") ||
            "(none)"}
        </p>
      </div>
    );
  }

  return (
    <div className="panel">
      <h3 style={{ marginTop: 0 }}>Child policies</h3>
      <table className="data">
        <thead>
          <tr>
            <th>Hotel</th>
            <th>Column</th>
            <th>Age from</th>
            <th>Age to</th>
            <th>Label</th>
            <th>Position</th>
            <th>Room condition</th>
            <th>Meal condition</th>
            <th>Value</th>
            <th>Meaning</th>
            <th>Confidence</th>
            <th>Warnings</th>
          </tr>
        </thead>
        <tbody>
          {policies.map((p, idx) => (
            <tr key={idx}>
              <td>{String(p.hotelName ?? "")}</td>
              <td>{String(p.dynamicColumnName ?? "")}</td>
              <td>{String(p.ageFrom ?? "—")}</td>
              <td>{String(p.ageTo ?? "—")}</td>
              <td>{String(p.ageLabel ?? "—")}</td>
              <td>{String(p.childPosition ?? "—")}</td>
              <td>{String(p.roomCondition ?? "—")}</td>
              <td>{String(p.mealPlanCondition ?? "—")}</td>
              <td>{String(p.value ?? "—")}</td>
              <td>{String(p.meaning ?? "—")}</td>
              <td>{String(p.confidence ?? "—")}</td>
              <td className="muted">
                {Array.isArray(p.warnings) ? (p.warnings as string[]).join("; ") : "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
