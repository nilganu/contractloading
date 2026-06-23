import { useEffect, useMemo, useState } from "react";
import { useMutation } from "@tanstack/react-query";

import { enrichMetadata } from "../../api/client";
import type { HotelRow, NormalizedExtractionResult } from "../../types";
import { ALLOWED_STAR_RATINGS, COUNTRY_CODES, RATE_TYPE_OPTIONS } from "../masterdata";
import { Field } from "../Field";
import { StepFooter, type StepKey } from "../StepNav";
import { fieldState, hotelNames, patchHotelField, rowsForHotel, useWizard } from "../WizardContext";

interface FieldDef {
  key: string;
  label: string;
  type?: "number" | "time" | "email" | "url";
  full?: boolean;
  options?: string[];
}

const IDENTITY: FieldDef[] = [
  { key: "Hotel Name", label: "Hotel name", full: true },
  { key: "Hotel Code", label: "Hotel code" },
  { key: "Supplier", label: "Supplier" },
  { key: "Star Rating", label: "Star rating", options: ALLOWED_STAR_RATINGS },
  { key: "Sell Channel", label: "Sell channel" },
  { key: "Short Description", label: "Short description", full: true },
];
const ADDRESS: FieldDef[] = [
  { key: "Address Line 1", label: "Address line 1", full: true },
  { key: "Address Line 2", label: "Address line 2" },
  { key: "Address Line 3", label: "Address line 3" },
  { key: "City / Area", label: "City / Area" },
  { key: "State / Province / Region", label: "County / State / Province" },
  { key: "Postal Code", label: "Postal code" },
  { key: "Country Code ", label: "Country code (ISO-2)", options: COUNTRY_CODES },
];
const CONTACT: FieldDef[] = [
  { key: "Phone Number", label: "Phone" },
  { key: "Email Address", label: "Email", type: "email" },
  { key: "Hotel Website", label: "Website", type: "url", full: true },
  { key: "Latitude", label: "Latitude", type: "number" },
  { key: "Longitude", label: "Longitude", type: "number" },
];
const STAY: FieldDef[] = [
  { key: "Check-In", label: "Check-in", type: "time" },
  { key: "Check-Out", label: "Check-out", type: "time" },
  { key: "Currency", label: "Currency" },
];

export function HotelStep({ onStep }: { onStep: (k: StepKey) => void }) {
  const { jobId, data, setData, replaceData, setActiveSourceRef } = useWizard();
  const names = useMemo(() => hotelNames(data.hotelRows as HotelRow[]), [data.hotelRows]);
  const [selected, setSelected] = useState(names[0] ?? "");
  const hotelRows = useMemo(
    () => rowsForHotel(data.hotelRows as HotelRow[], selected),
    [data.hotelRows, selected]
  );
  const rep = hotelRows[0];
  const format = ((data as unknown as Record<string, unknown>)._format as string) || "moonstride_auto";

  useEffect(() => {
    const refs = (rep as unknown as Record<string, unknown> | undefined)?._sourceRefs as
      | string[]
      | undefined;
    if (refs && refs.length) setActiveSourceRef(refs[0]);
  }, [rep, setActiveSourceRef]);

  const enrich = useMutation({
    mutationFn: () => enrichMetadata(jobId, false),
    onSuccess: (res) => replaceData(res.result),
  });

  if (!rep) return <p className="text-slate-500">No hotels found in this contract.</p>;

  function renderFields(defs: FieldDef[], cols: 2 | 3 = 2) {
    return (
      <section className={`grid gap-4 ${cols === 3 ? "grid-cols-3" : "grid-cols-2"}`}>
        {defs.map((f) => (
          <Field
            key={f.key}
            label={f.label}
            value={(rep as unknown as Record<string, unknown>)[f.key] as string | number | null}
            type={f.type === "number" ? "number" : f.type === "time" ? "time" : f.type === "email" ? "email" : f.type === "url" ? "url" : "text"}
            options={f.options}
            state={fieldState(rep, f.key)}
            className={f.full ? "col-span-2" : ""}
            onChange={(v) =>
              setData((prev) =>
                patchHotelField(prev, selected, f.key, f.type === "number" ? (v === "" ? null : Number(v)) : v)
              )
            }
          />
        ))}
      </section>
    );
  }

  return (
    <div>
      <header className="mb-6">
        <h2 className="text-xl font-semibold text-slate-900">Hotel information</h2>
        <p className="mt-1 text-sm text-slate-600">
          Verify the hotel metadata. Fields tagged{" "}
          <span className="rounded bg-cyan-100 px-1.5 py-0.5 text-[10px] font-semibold text-cyan-800">
            🌐 enriched
          </span>{" "}
          were filled by AI from the hotel name (not the contract) — verify them.
        </p>
        <div className="mt-3 flex items-center gap-3">
          {names.length > 1 && (
            <select
              value={selected}
              onChange={(e) => setSelected(e.target.value)}
              className="rounded-md border border-slate-300 px-3 py-1.5 text-sm"
            >
              {names.map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          )}
          <button
            onClick={() => enrich.mutate()}
            disabled={enrich.isPending}
            className="rounded-md border border-cyan-300 bg-cyan-50 px-3 py-1.5 text-sm font-medium text-cyan-800 hover:bg-cyan-100 disabled:opacity-60"
          >
            {enrich.isPending ? "Filling…" : "🌐 Fill missing info with GPT"}
          </button>
          {enrich.isError && <span className="text-xs text-red-600">Enrichment failed.</span>}
          {enrich.data && (
            <span className="text-xs text-slate-500">
              {enrich.data.summary.skipped
                ? enrich.data.summary.message
                : `Filled ${enrich.data.summary.fieldsFilled} field(s).`}
            </span>
          )}
        </div>
      </header>

      <div className="space-y-6 rounded-lg border border-slate-200 bg-white p-6">
        {renderFields(IDENTITY)}
        <hr className="border-slate-200" />
        {renderFields(ADDRESS)}
        <hr className="border-slate-200" />
        {renderFields(CONTACT)}
        <hr className="border-slate-200" />
        {renderFields(STAY, 3)}
        <hr className="border-slate-200" />
        <section>
          <label className="text-sm font-medium text-slate-700">Pricing format</label>
          <select
            value={format}
            onChange={(e) =>
              setData((prev) => ({ ...prev, _format: e.target.value }) as NormalizedExtractionResult)
            }
            className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
          >
            <option value="moonstride_auto">Auto-detect from contract</option>
            {RATE_TYPE_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
          <p className="mt-1 text-xs text-slate-500">
            Controls which Excel template is filled at the Preview step.
          </p>
        </section>
      </div>

      <StepFooter current="hotel" onStep={onStep} />
    </div>
  );
}
