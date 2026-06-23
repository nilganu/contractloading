import { useMemo } from "react";

import type { DynamicChildColumn, NormalizedExtractionResult } from "../../types";
import { StepFooter, type StepKey } from "../StepNav";
import { useWizard } from "../WizardContext";

type Col = DynamicChildColumn & { discountPct?: number; appliesWhen?: string };

export function ChildPolicyStep({ onStep }: { onStep: (k: StepKey) => void }) {
  const { data, setData } = useWizard();
  const tiers = data.dynamicColumns.childColumns as Col[];

  const infantAge = (data as unknown as Record<string, unknown>)._childInfantAge as string | undefined;
  const notes = (data as unknown as Record<string, unknown>)._childNotes as string | undefined;

  function updateTier(index: number, patch: Partial<Col>) {
    setData((prev: NormalizedExtractionResult) => ({
      ...prev,
      dynamicColumns: {
        ...prev.dynamicColumns,
        childColumns: prev.dynamicColumns.childColumns.map((c, i) =>
          i === index ? ({ ...c, ...patch } as DynamicChildColumn) : c
        ),
      },
    }));
  }

  function addTier() {
    setData((prev) => {
      const n = prev.dynamicColumns.childColumns.length + 1;
      const fresh = {
        key: `CHD${n}`,
        label: "",
        ageFrom: 0,
        ageTo: 0,
        ageLabel: null,
        childPosition: null,
        valueType: "discount_percentage",
        discountPct: 0,
      } as unknown as DynamicChildColumn;
      return {
        ...prev,
        dynamicColumns: {
          ...prev.dynamicColumns,
          childColumns: [...prev.dynamicColumns.childColumns, fresh],
        },
      };
    });
  }

  function removeTier(index: number) {
    setData((prev) => ({
      ...prev,
      dynamicColumns: {
        ...prev.dynamicColumns,
        childColumns: prev.dynamicColumns.childColumns.filter((_, i) => i !== index),
      },
    }));
  }

  function setMeta(key: string, value: string) {
    setData((prev) => ({ ...prev, [key]: value }) as NormalizedExtractionResult);
  }

  return (
    <div>
      <header className="mb-6">
        <h2 className="text-xl font-semibold text-slate-900">Child age policy</h2>
        <p className="mt-1 text-sm text-slate-600">
          Each tier needs a min age, max age, and discount % (100 = free, 50 =
          half-price, 0 = no discount). Decimals are allowed (e.g. 2.99). The min
          and max age drive the export's 1st / 2nd / 3rd Child Age columns.
        </p>
      </header>

      <div className="rounded-lg border border-slate-200 bg-white p-4">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs uppercase text-slate-500">
              <th className="pb-2">Tier name</th>
              <th className="pb-2">Min age</th>
              <th className="pb-2">Max age</th>
              <th className="pb-2">Discount %</th>
              <th className="pb-2">Applies when</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {tiers.map((t, i) => {
              const invalid = (t.ageFrom ?? 0) >= (t.ageTo ?? 0);
              return (
                <tr key={t.key + i} className="border-t border-slate-100">
                  <td className="py-1.5">
                    <input
                      value={t.label ?? ""}
                      onChange={(e) => updateTier(i, { label: e.target.value })}
                      placeholder="Infant / 1st Child / Teen…"
                      className="w-full rounded border border-slate-300 px-2 py-1 text-sm"
                    />
                  </td>
                  <td className="py-1.5">
                    <input
                      type="number"
                      step="0.01"
                      value={t.ageFrom ?? ""}
                      onChange={(e) =>
                        updateTier(i, { ageFrom: e.target.value === "" ? null : Number(e.target.value) })
                      }
                      className={`w-20 rounded border px-2 py-1 text-sm ${invalid ? "border-red-400 bg-red-50" : "border-slate-300"}`}
                    />
                  </td>
                  <td className="py-1.5">
                    <input
                      type="number"
                      step="0.01"
                      value={t.ageTo ?? ""}
                      onChange={(e) =>
                        updateTier(i, { ageTo: e.target.value === "" ? null : Number(e.target.value) })
                      }
                      className={`w-20 rounded border px-2 py-1 text-sm ${invalid ? "border-red-400 bg-red-50" : "border-slate-300"}`}
                    />
                  </td>
                  <td className="py-1.5">
                    <input
                      type="number"
                      value={t.discountPct ?? ""}
                      onChange={(e) => updateTier(i, { discountPct: Number(e.target.value) })}
                      className="w-20 rounded border border-slate-300 px-2 py-1 text-sm"
                    />
                  </td>
                  <td className="py-1.5">
                    <input
                      value={t.appliesWhen ?? ""}
                      onChange={(e) => updateTier(i, { appliesWhen: e.target.value })}
                      placeholder="e.g. in family rooms only"
                      className="w-full rounded border border-slate-300 px-2 py-1 text-sm"
                    />
                  </td>
                  <td className="py-1.5 text-right">
                    <button
                      onClick={() => removeTier(i)}
                      className="text-xs text-red-600 hover:underline"
                    >
                      Remove
                    </button>
                  </td>
                </tr>
              );
            })}
            {tiers.length === 0 && (
              <tr>
                <td colSpan={6} className="py-2 text-slate-400">
                  No child tiers detected.
                </td>
              </tr>
            )}
          </tbody>
        </table>
        <button
          onClick={addTier}
          className="mt-3 rounded-md border border-slate-300 bg-slate-50 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-100"
        >
          + Add tier
        </button>
      </div>

      <div className="mt-6 grid grid-cols-2 gap-4 rounded-lg border border-slate-200 bg-white p-4">
        <label className="block">
          <span className="text-xs font-medium text-slate-700">
            Infant age field (for non-tiered formats)
          </span>
          <input
            value={infantAge ?? ""}
            onChange={(e) => setMeta("_childInfantAge", e.target.value)}
            placeholder="0-1"
            className="mt-1 block w-full rounded border border-slate-300 px-2 py-1 text-sm"
          />
        </label>
        <label className="block">
          <span className="text-xs font-medium text-slate-700">Child policy notes</span>
          <input
            value={notes ?? ""}
            onChange={(e) => setMeta("_childNotes", e.target.value)}
            placeholder="Any nuances from the contract"
            className="mt-1 block w-full rounded border border-slate-300 px-2 py-1 text-sm"
          />
        </label>
      </div>

      <StepFooter current="child" onStep={onStep} />
    </div>
  );
}
