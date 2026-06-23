import { useMemo, useState } from "react";

import { exportXlsx } from "../../api/client";
import type { DynamicChildColumn, HotelRow } from "../../types";
import { RATE_TYPE_OPTIONS } from "../masterdata";
import { StepFooter, type StepKey } from "../StepNav";
import { useWizard } from "../WizardContext";

const FORMAT_LABEL: Record<string, string> = {
  moonstride_auto: "Auto-detect",
  moonstride_ppn: "Per Person Per Night",
  moonstride_prn_ac: "Per Room Per Night (Adult / Child count)",
  moonstride_prn_pax: "Per Room Per Night (Pax count)",
};

export function PreviewStep({ onStep }: { onStep: (k: StepKey) => void }) {
  const { jobId, data, flushNow } = useWizard();
  const [error, setError] = useState<string | null>(null);
  const [generating, setGenerating] = useState(false);

  const format = ((data as unknown as Record<string, unknown>)._format as string) || "moonstride_auto";
  const rep = data.hotelRows[0] as HotelRow | undefined;
  const tiers = data.dynamicColumns.childColumns as (DynamicChildColumn & { discountPct?: number })[];

  const issues = data.validationIssues ?? [];
  const blocking = issues.filter((i) => i.severity === "error");

  const rows = useMemo(() => data.hotelRows as HotelRow[], [data.hotelRows]);

  async function generate() {
    setError(null);
    setGenerating(true);
    try {
      await flushNow();
      const blob = await exportXlsx(jobId, format, false);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${jobId}-${format}.xlsx`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Generation failed");
    } finally {
      setGenerating(false);
    }
  }

  const seasonLabel = (r: HotelRow) =>
    (r["Season"] as string) || `${r["Start Date"] ?? "?"} → ${r["End Date"] ?? "?"}`;
  const childVals = (r: HotelRow) => Object.values(r.dynamicChildValues ?? {});

  return (
    <div>
      <header className="mb-6">
        <h2 className="text-xl font-semibold text-slate-900">Final preview</h2>
        <p className="mt-1 text-sm text-slate-600">Review everything below, then generate the Excel.</p>
      </header>

      <section className="rounded-lg border border-slate-200 bg-white p-4">
        <h3 className="text-sm font-medium text-slate-700">Hotel</h3>
        <dl className="mt-2 grid grid-cols-3 gap-x-4 gap-y-1 text-xs">
          <dt className="text-slate-500">Name</dt>
          <dd className="col-span-2">{(rep?.["Hotel Name"] as string) || "—"}</dd>
          <dt className="text-slate-500">Country</dt>
          <dd className="col-span-2">{(rep?.["Country Code "] as string) || "—"}</dd>
          <dt className="text-slate-500">City</dt>
          <dd className="col-span-2">{(rep?.["City / Area"] as string) || "—"}</dd>
          <dt className="text-slate-500">Currency</dt>
          <dd className="col-span-2">{(rep?.["Currency"] as string) || "EUR"}</dd>
          <dt className="text-slate-500">Format</dt>
          <dd className="col-span-2 font-medium">{FORMAT_LABEL[format] ?? format}</dd>
        </dl>
      </section>

      <section className="mt-4 rounded-lg border border-slate-200 bg-white p-4">
        <h3 className="text-sm font-medium text-slate-700">Child tiers</h3>
        <table className="mt-2 w-full text-xs">
          <thead>
            <tr className="text-left text-[10px] uppercase text-slate-500">
              <th>Name</th>
              <th>Min</th>
              <th>Max</th>
              <th>Discount %</th>
            </tr>
          </thead>
          <tbody>
            {tiers.map((t, i) => (
              <tr key={i} className="border-t border-slate-100">
                <td className="py-1">{t.label || t.key}</td>
                <td className="py-1">{t.ageFrom ?? ""}</td>
                <td className="py-1">{t.ageTo ?? ""}</td>
                <td className="py-1">{t.discountPct ?? ""}</td>
              </tr>
            ))}
            {tiers.length === 0 && (
              <tr>
                <td colSpan={4} className="py-2 text-slate-400">No child tiers defined.</td>
              </tr>
            )}
          </tbody>
        </table>
      </section>

      <section className="mt-4 rounded-lg border border-slate-200 bg-white p-4">
        <h3 className="text-sm font-medium text-slate-700">Rate rows ({rows.length})</h3>
        <div className="mt-2 max-h-80 overflow-auto">
          <table className="w-full text-xs">
            <thead className="sticky top-0 bg-white">
              <tr className="text-left text-[10px] uppercase text-slate-500">
                <th className="pb-1">Room</th>
                <th className="pb-1">Season</th>
                <th className="pb-1">Meal</th>
                <th className="pb-1">A1</th>
                <th className="pb-1">A2</th>
                <th className="pb-1">A3</th>
                <th className="pb-1">A4</th>
                <th className="pb-1">Child</th>
                <th className="pb-1">Teen</th>
              </tr>
            </thead>
            <tbody>
              {rows.slice(0, 200).map((r, i) => {
                const cv = childVals(r);
                return (
                  <tr key={i} className="border-t border-slate-100">
                    <td className="py-0.5">{(r["Room Name"] as string) ?? ""}</td>
                    <td className="py-0.5">{seasonLabel(r)}</td>
                    <td className="py-0.5">{(r["Meal Plan"] as string) ?? ""}</td>
                    <td className="py-0.5">{(r["SGL"] as number) ?? ""}</td>
                    <td className="py-0.5">{(r["DBL"] as number) ?? ""}</td>
                    <td className="py-0.5">{(r["TPL"] as number) ?? ""}</td>
                    <td className="py-0.5">{(r["QDP"] as number) ?? ""}</td>
                    <td className="py-0.5">{cv[0] ?? ""}</td>
                    <td className="py-0.5">{cv[1] ?? ""}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {rows.length > 200 && (
            <p className="mt-2 text-[11px] text-slate-500">
              Showing first 200 of {rows.length} rows. All rows are written to Excel.
            </p>
          )}
        </div>
      </section>

      {error && (
        <div className="mt-4 rounded border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-700">
          {error}
        </div>
      )}
      {blocking.length > 0 && (
        <div className="mt-4 rounded border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-800">
          {blocking.length} blocking validation error(s) must be resolved before export.
        </div>
      )}

      <div className="mt-6 flex items-center justify-between">
        <StepFooter current="preview" onStep={onStep} />
        <div className="flex items-center gap-2">
          <select
            value={format}
            disabled
            className="rounded-md border border-slate-300 px-3 py-2 text-sm text-slate-500"
            title="Set the format on the Hotel step"
          >
            {[{ value: "moonstride_auto", label: "Auto-detect" }, ...RATE_TYPE_OPTIONS].map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
          <button
            onClick={generate}
            disabled={generating || blocking.length > 0}
            className="rounded-md bg-emerald-600 px-5 py-2.5 text-sm font-semibold text-white hover:bg-emerald-700 disabled:bg-slate-400"
          >
            {generating ? "Generating…" : "Generate Excel"}
          </button>
        </div>
      </div>
    </div>
  );
}
