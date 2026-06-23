import { useMemo, useState } from "react";

import type {
  HotelRow,
  NormalizedExtractionResult,
  TemplateMetadata,
} from "../types";

const FROZEN = new Set(["Hotel Name", "Room Name", "Start Date", "End Date"]);

const DROPDOWNS: Record<string, string[]> = {
  Currency: ["EUR", "USD", "GBP", "AED", "EGP", "Other"],
  "Rate Type": ["Per Person Per Night", "Per Person Per Day", "Per Room Per Night"],
  "Meal Plan": [
    "Room Only",
    "Bed & Breakfast",
    "Half Board",
    "Full Board",
    "All Inclusive",
    "Ultra All Inclusive",
    "Other",
  ],
  Status: ["Open", "On Request"],
};

// "Days" is a weekday-mask string (eg "0,1,2,3,4,5,6"), edited as text.
const NUMERIC = new Set([
  "Latitude",
  "Longitude",
  "Min Adult",
  "Max Adult",
  "Max Pax",
  "Min Stay",
  "Booking Limit",
  "Release Period",
  "Add Charge Value",
  "Charge",
  "SGL",
  "DBL",
  "TPL",
  "QDP",
  "Extra Bed",
  "SUPP-HB-ADULT",
  "SUPP-HB-CHILD",
  "SUPP-AI-ADULT",
  "SUPP-AI-CHILD",
]);
const DATES = new Set(["Start Date", "End Date"]);

export default function HotelRowsGrid(props: {
  result: NormalizedExtractionResult;
  template: TemplateMetadata;
  onPatch: (next: NormalizedExtractionResult) => void;
  patching: boolean;
}) {
  const { result, template, onPatch, patching } = props;

  const childKeys = useMemo(
    () => result.dynamicColumns.childColumns.map((c) => c.key),
    [result.dynamicColumns.childColumns]
  );

  const headers = useMemo(
    () => [
      ...template.fixedBaseHeaders,
      ...childKeys,
      ...template.fixedSupplementHeaders,
    ],
    [template, childKeys]
  );

  const [editing, setEditing] = useState<Record<string, HotelRow>>({});
  const [filterHotel, setFilterHotel] = useState<string>("");
  const [filterSheet, setFilterSheet] = useState<string>("");
  const [onlyWarnings, setOnlyWarnings] = useState(false);
  const [onlyErrors, setOnlyErrors] = useState(false);

  const issueByRow = useMemo(() => {
    const m: Record<string, { errors: number; warnings: number }> = {};
    for (const i of result.validationIssues) {
      const id = i.hotelRowId;
      if (!id) continue;
      m[id] = m[id] ?? { errors: 0, warnings: 0 };
      if (i.severity === "error") m[id].errors += 1;
      else if (i.severity === "warning") m[id].warnings += 1;
    }
    return m;
  }, [result.validationIssues]);

  const rows = useMemo(() => {
    let rs = result.hotelRows.map((r) => editing[r.id] ?? r);
    if (filterHotel) {
      rs = rs.filter((r) => (r["Hotel Name"] ?? "").includes(filterHotel));
    }
    if (filterSheet) {
      rs = rs.filter((r) => (r.sourceSheetOrPage ?? "").includes(filterSheet));
    }
    if (onlyErrors) rs = rs.filter((r) => (issueByRow[r.id]?.errors ?? 0) > 0);
    if (onlyWarnings) rs = rs.filter((r) => (issueByRow[r.id]?.warnings ?? 0) > 0);
    return rs;
  }, [result.hotelRows, editing, filterHotel, filterSheet, onlyErrors, onlyWarnings, issueByRow]);

  function commit(rowId: string) {
    const edited = editing[rowId];
    if (!edited) return;
    const next: NormalizedExtractionResult = {
      ...result,
      hotelRows: result.hotelRows.map((r) => (r.id === rowId ? edited : r)),
    };
    onPatch(next);
    setEditing(({ [rowId]: _, ...rest }) => rest);
  }

  function setField(rowId: string, header: string, value: unknown) {
    setEditing((cur) => {
      const base = cur[rowId] ?? result.hotelRows.find((r) => r.id === rowId)!;
      let v: unknown = value;
      if (NUMERIC.has(header)) {
        if (value === "" || value === null) v = null;
        else {
          const n = Number(value);
          v = Number.isFinite(n) ? n : value;
        }
      }
      if (childKeys.includes(header)) {
        const dyn = { ...base.dynamicChildValues, [header]: v as number | null };
        return { ...cur, [rowId]: { ...base, dynamicChildValues: dyn, _reviewState: "edited" } };
      }
      return { ...cur, [rowId]: { ...base, [header]: v, _reviewState: "edited" } as HotelRow };
    });
  }

  function valueFor(row: HotelRow, header: string): unknown {
    if (childKeys.includes(header)) {
      return row.dynamicChildValues?.[header] ?? null;
    }
    return (row as unknown as Record<string, unknown>)[header];
  }

  return (
    <>
      <div className="panel">
        <div className="row">
          <input
            placeholder="Filter by Hotel Name…"
            value={filterHotel}
            onChange={(e) => setFilterHotel(e.target.value)}
          />
          <input
            placeholder="Filter by Sheet/Page…"
            value={filterSheet}
            onChange={(e) => setFilterSheet(e.target.value)}
          />
          <label>
            <input
              type="checkbox"
              checked={onlyErrors}
              onChange={(e) => setOnlyErrors(e.target.checked)}
            />{" "}
            Only errors
          </label>
          <label>
            <input
              type="checkbox"
              checked={onlyWarnings}
              onChange={(e) => setOnlyWarnings(e.target.checked)}
            />{" "}
            Only warnings
          </label>
          <div className="spacer" />
          <span className="muted">
            {rows.length} of {result.hotelRows.length}
          </span>
          {patching && <span className="muted">Saving…</span>}
        </div>
      </div>

      <div className="scroll-grid">
        <table className="data">
          <thead>
            <tr>
              <th className="frozen" style={{ left: 0, minWidth: 60 }}>#</th>
              {headers.map((h) => (
                <th
                  key={h}
                  className={FROZEN.has(h) ? "frozen" : ""}
                  style={FROZEN.has(h) ? frozenStyleFor(h) : undefined}
                  title={h}
                >
                  {h}
                </th>
              ))}
              <th>Confidence</th>
              <th>Warnings</th>
              <th>Source refs</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row, idx) => {
              const issues = issueByRow[row.id];
              const rowCls = issues?.errors
                ? "error"
                : issues?.warnings
                ? "warning"
                : "";
              const reviewCls = row._reviewState
                ? row._reviewState === "verified"
                  ? "row-review-verified"
                  : row._reviewState === "edited"
                  ? "row-review-edited"
                  : ""
                : "";
              return (
                <tr key={row.id} className={`${rowCls} ${reviewCls}`.trim()}>
                  <td className="frozen muted" style={{ left: 0, minWidth: 60 }}>{idx + 1}</td>
                  {headers.map((h) => {
                    const cellMeta = row._cellMeta?.[h];
                    const lowConf =
                      typeof cellMeta?.confidence === "number" && cellMeta.confidence < 0.6;
                    const tdClass = [
                      FROZEN.has(h) ? "frozen" : "",
                      lowConf ? "low-confidence" : "",
                    ]
                      .filter(Boolean)
                      .join(" ");
                    const title = cellMeta?.sourceRef
                      ? `source: ${cellMeta.sourceRef}${
                          typeof cellMeta.confidence === "number"
                            ? `\nconfidence: ${cellMeta.confidence.toFixed(2)}`
                            : ""
                        }`
                      : undefined;
                    return (
                      <td
                        key={h}
                        className={tdClass}
                        style={FROZEN.has(h) ? frozenStyleFor(h) : undefined}
                        title={title}
                      >
                        <CellEditor
                          header={h}
                          value={valueFor(row, h)}
                          onChange={(v) => setField(row.id, h, v)}
                          onCommit={() => commit(row.id)}
                        />
                      </td>
                    );
                  })}
                  <td className="muted">{(row._confidence ?? 0).toFixed(2)}</td>
                  <td>
                    {(row._warnings ?? []).slice(0, 1).map((w) => (
                      <span key={w} className="badge warning" title={(row._warnings ?? []).join("\n")}>
                        {(row._warnings ?? []).length} ⚠
                      </span>
                    ))}
                  </td>
                  <td className="muted">{(row._sourceRefs ?? []).join("; ")}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </>
  );
}

function frozenStyleFor(header: string): React.CSSProperties {
  switch (header) {
    case "Hotel Name":
      return { left: 60, minWidth: 220 };
    case "Room Name":
      return { left: 280, minWidth: 200 };
    case "Start Date":
      return { left: 480, minWidth: 110 };
    case "End Date":
      return { left: 590, minWidth: 110 };
    default:
      return {};
  }
}

function CellEditor(props: {
  header: string;
  value: unknown;
  onChange: (v: unknown) => void;
  onCommit: () => void;
}) {
  const { header, value, onChange, onCommit } = props;
  const v = value as string | number | null | undefined;

  if (DROPDOWNS[header]) {
    return (
      <select
        className="cell-input"
        value={(v as string) ?? ""}
        onChange={(e) => onChange(e.target.value || null)}
        onBlur={onCommit}
      >
        <option value="">—</option>
        {DROPDOWNS[header].map((o) => (
          <option key={o} value={o}>
            {o}
          </option>
        ))}
      </select>
    );
  }

  if (DATES.has(header)) {
    return (
      <input
        type="date"
        className="cell-input"
        value={(v as string) ?? ""}
        onChange={(e) => onChange(e.target.value || null)}
        onBlur={onCommit}
      />
    );
  }

  if (NUMERIC.has(header) || header.startsWith("CHD")) {
    return (
      <input
        type="number"
        className="cell-input"
        value={v === null || v === undefined ? "" : String(v)}
        step="any"
        onChange={(e) => onChange(e.target.value)}
        onBlur={onCommit}
      />
    );
  }

  return (
    <input
      className="cell-input"
      value={v === null || v === undefined ? "" : String(v)}
      onChange={(e) => onChange(e.target.value)}
      onBlur={onCommit}
    />
  );
}
