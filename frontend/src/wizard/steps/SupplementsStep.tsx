import { useMemo } from "react";

import type { ExtractionNote, NormalizedExtractionResult } from "../../types";
import { StepFooter, type StepKey } from "../StepNav";
import { useWizard } from "../WizardContext";

type Note = ExtractionNote & Record<string, unknown>;

const SUPPLEMENT_CATS = ["Room supplement", "Taxes/service", "Meal plan nuance"];

export function SupplementsStep({ onStep }: { onStep: (k: StepKey) => void }) {
  const { data, setData } = useWizard();
  const notes = data.extractionNotes as Note[];

  const supplements = useMemo(
    () => notes.filter((n) => SUPPLEMENT_CATS.includes(n.Category)),
    [notes]
  );
  const offers = useMemo(() => notes.filter((n) => n.Category === "Special offer"), [notes]);
  const cancellation = useMemo(
    () => notes.filter((n) => n.Category === "Cancellation"),
    [notes]
  );

  function updateNote(id: string, patch: Partial<Note>) {
    setData((prev: NormalizedExtractionResult) => ({
      ...prev,
      extractionNotes: prev.extractionNotes.map((n) =>
        (n as Note).id === id ? ({ ...n, ...patch } as ExtractionNote) : n
      ),
    }));
  }
  function addNote(category: string) {
    setData((prev) => ({
      ...prev,
      extractionNotes: [
        ...prev.extractionNotes,
        {
          id: `note_${Math.random().toString(36).slice(2, 10)}`,
          "Source File": prev.workbookSummary.sourceFile,
          Page: "—",
          Category: category,
          Note: "",
        } as ExtractionNote,
      ],
    }));
  }
  function removeNote(id: string) {
    setData((prev) => ({
      ...prev,
      extractionNotes: prev.extractionNotes.filter((n) => (n as Note).id !== id),
    }));
  }

  const txt = (n: Note, key: string) => (n[key] as string) ?? "";

  return (
    <div>
      <header className="mb-6">
        <h2 className="text-xl font-semibold text-slate-900">
          Supplements, offers &amp; cancellation
        </h2>
        <p className="mt-1 text-sm text-slate-600">
          Review supplements (single-room, sea-view, gala dinners), special
          offers (early-bird, long-stay), and cancellation terms.
        </p>
      </header>

      {/* Supplements */}
      <section className="rounded-lg border border-slate-200 bg-white p-4">
        <h3 className="text-sm font-medium text-slate-700">Supplements</h3>
        <table className="mt-3 w-full text-sm">
          <thead>
            <tr className="text-left text-xs uppercase text-slate-500">
              <th className="pb-2">Name</th>
              <th className="pb-2">Value</th>
              <th className="pb-2">Unit</th>
              <th className="pb-2">From</th>
              <th className="pb-2">To</th>
              <th className="pb-2">Notes</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {supplements.map((s) => (
              <tr key={s.id} className="border-t border-slate-100">
                <td className="py-1.5">
                  <input
                    value={s.Note ?? ""}
                    onChange={(e) => updateNote(s.id, { Note: e.target.value })}
                    className="w-full rounded border border-slate-300 px-2 py-1 text-sm"
                  />
                </td>
                <td className="py-1.5">
                  <input
                    type="number"
                    value={txt(s, "value")}
                    onChange={(e) => updateNote(s.id, { value: e.target.value })}
                    className="w-20 rounded border border-slate-300 px-2 py-1 text-sm"
                  />
                </td>
                <td className="py-1.5">
                  <input
                    value={txt(s, "unit")}
                    onChange={(e) => updateNote(s.id, { unit: e.target.value })}
                    placeholder="USD / %"
                    className="w-16 rounded border border-slate-300 px-2 py-1 text-sm"
                  />
                </td>
                <td className="py-1.5">
                  <input
                    type="date"
                    value={txt(s, "appliesFrom")}
                    onChange={(e) => updateNote(s.id, { appliesFrom: e.target.value })}
                    className="rounded border border-slate-300 px-2 py-1 text-sm"
                  />
                </td>
                <td className="py-1.5">
                  <input
                    type="date"
                    value={txt(s, "appliesTo")}
                    onChange={(e) => updateNote(s.id, { appliesTo: e.target.value })}
                    className="rounded border border-slate-300 px-2 py-1 text-sm"
                  />
                </td>
                <td className="py-1.5">
                  <input
                    value={txt(s, "extraNotes")}
                    onChange={(e) => updateNote(s.id, { extraNotes: e.target.value })}
                    className="w-full rounded border border-slate-300 px-2 py-1 text-sm"
                  />
                </td>
                <td className="py-1.5 text-right">
                  <button onClick={() => removeNote(s.id)} className="text-xs text-red-600 hover:underline">
                    Remove
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <button
          onClick={() => addNote("Room supplement")}
          className="mt-3 rounded-md border border-slate-300 bg-slate-50 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-100"
        >
          + Add supplement
        </button>
      </section>

      {/* Special offers */}
      <section className="mt-6 rounded-lg border border-slate-200 bg-white p-4">
        <h3 className="text-sm font-medium text-slate-700">Special offers</h3>
        <table className="mt-3 w-full text-sm">
          <thead>
            <tr className="text-left text-xs uppercase text-slate-500">
              <th className="pb-2">Name</th>
              <th className="pb-2">Type</th>
              <th className="pb-2">Discount %</th>
              <th className="pb-2">Book by</th>
              <th className="pb-2">Stay from</th>
              <th className="pb-2">Stay to</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {offers.map((o) => (
              <tr key={o.id} className="border-t border-slate-100">
                <td className="py-1.5">
                  <input
                    value={o.Note ?? ""}
                    onChange={(e) => updateNote(o.id, { Note: e.target.value })}
                    className="w-full rounded border border-slate-300 px-2 py-1 text-sm"
                  />
                </td>
                <td className="py-1.5">
                  <input
                    value={txt(o, "offerType")}
                    onChange={(e) => updateNote(o.id, { offerType: e.target.value })}
                    placeholder="Early bird / Long stay…"
                    className="w-full rounded border border-slate-300 px-2 py-1 text-sm"
                  />
                </td>
                <td className="py-1.5">
                  <input
                    type="number"
                    value={txt(o, "discountPct")}
                    onChange={(e) => updateNote(o.id, { discountPct: e.target.value })}
                    className="w-20 rounded border border-slate-300 px-2 py-1 text-sm"
                  />
                </td>
                <td className="py-1.5">
                  <input
                    type="date"
                    value={txt(o, "bookByDate")}
                    onChange={(e) => updateNote(o.id, { bookByDate: e.target.value })}
                    className="rounded border border-slate-300 px-2 py-1 text-sm"
                  />
                </td>
                <td className="py-1.5">
                  <input
                    type="date"
                    value={txt(o, "stayFrom")}
                    onChange={(e) => updateNote(o.id, { stayFrom: e.target.value })}
                    className="rounded border border-slate-300 px-2 py-1 text-sm"
                  />
                </td>
                <td className="py-1.5">
                  <input
                    type="date"
                    value={txt(o, "stayTo")}
                    onChange={(e) => updateNote(o.id, { stayTo: e.target.value })}
                    className="rounded border border-slate-300 px-2 py-1 text-sm"
                  />
                </td>
                <td className="py-1.5 text-right">
                  <button onClick={() => removeNote(o.id)} className="text-xs text-red-600 hover:underline">
                    Remove
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <button
          onClick={() => addNote("Special offer")}
          className="mt-3 rounded-md border border-slate-300 bg-slate-50 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-100"
        >
          + Add offer
        </button>
      </section>

      {/* Cancellation */}
      <section className="mt-6 rounded-lg border border-slate-200 bg-white p-4">
        <h3 className="text-sm font-medium text-slate-700">Cancellation terms</h3>
        <table className="mt-3 w-full text-sm">
          <thead>
            <tr className="text-left text-xs uppercase text-slate-500">
              <th className="pb-2">Days before</th>
              <th className="pb-2">Penalty</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {cancellation.map((c) => (
              <tr key={c.id} className="border-t border-slate-100">
                <td className="py-1.5">
                  <input
                    value={txt(c, "daysBefore")}
                    onChange={(e) => updateNote(c.id, { daysBefore: e.target.value })}
                    placeholder="14+, 13-7, 6-3…"
                    className="w-32 rounded border border-slate-300 px-2 py-1 text-sm"
                  />
                </td>
                <td className="py-1.5">
                  <input
                    value={c.Note ?? ""}
                    onChange={(e) => updateNote(c.id, { Note: e.target.value })}
                    placeholder="0% / 30% / Full stay…"
                    className="w-full rounded border border-slate-300 px-2 py-1 text-sm"
                  />
                </td>
                <td className="py-1.5 text-right">
                  <button onClick={() => removeNote(c.id)} className="text-xs text-red-600 hover:underline">
                    Remove
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <button
          onClick={() => addNote("Cancellation")}
          className="mt-3 rounded-md border border-slate-300 bg-slate-50 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-100"
        >
          + Add cancellation term
        </button>
      </section>

      <StepFooter current="supplements" onStep={onStep} />
    </div>
  );
}
