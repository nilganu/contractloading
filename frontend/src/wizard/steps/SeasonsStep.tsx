import { useMemo } from "react";

import type { HotelRow, NormalizedExtractionResult } from "../../types";
import { StepFooter, type StepKey } from "../StepNav";
import { patchSeasonField, useWizard } from "../WizardContext";

interface SeasonAgg {
  key: string;
  name: string;
  startDate: string;
  endDate: string;
  days: string;
  minStay: number | null;
  release: number | null;
}

export function SeasonsStep({ onStep }: { onStep: (k: StepKey) => void }) {
  const { data, setData } = useWizard();

  const seasons = useMemo<SeasonAgg[]>(() => {
    const map = new Map<string, SeasonAgg>();
    for (const r of data.hotelRows as HotelRow[]) {
      const start = (r["Start Date"] as string) || "";
      const end = (r["End Date"] as string) || "";
      const key = `${start}||${end}`;
      if (map.has(key)) continue;
      map.set(key, {
        key,
        name: (r["Season"] as string) || (r["Rate Plan"] as string) || "",
        startDate: start,
        endDate: end,
        days: (r["Days"] as string) || "",
        minStay: r["Min Stay"] as number | null,
        release: r["Release Period"] as number | null,
      });
    }
    return [...map.values()];
  }, [data.hotelRows]);

  const roomCount = useMemo(
    () => new Set((data.hotelRows as HotelRow[]).map((r) => r["Room Name"])).size,
    [data.hotelRows]
  );
  const mealCount = useMemo(
    () => new Set((data.hotelRows as HotelRow[]).map((r) => r["Meal Plan"]).filter(Boolean)).size,
    [data.hotelRows]
  );

  function update(s: SeasonAgg, field: string, value: string | number | null) {
    setData((prev: NormalizedExtractionResult) =>
      patchSeasonField(prev, s.startDate, s.endDate, field, value)
    );
  }

  function removeSeason(s: SeasonAgg) {
    setData((prev) => ({
      ...prev,
      hotelRows: prev.hotelRows.filter(
        (r) =>
          !(
            (r as HotelRow)["Start Date"] === s.startDate &&
            (r as HotelRow)["End Date"] === s.endDate
          )
      ),
    }));
  }

  return (
    <div>
      <header className="mb-6">
        <h2 className="text-xl font-semibold text-slate-900">Seasons</h2>
        <p className="mt-1 text-sm text-slate-600">
          Confirm the season date ranges. Use ISO dates (YYYY-MM-DD). Days mask
          uses 1=Mon … 7=Sun.
        </p>
      </header>

      <div className="rounded-lg border border-slate-200 bg-white p-4">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs uppercase text-slate-500">
              <th className="pb-2">Name</th>
              <th className="pb-2">Start</th>
              <th className="pb-2">End</th>
              <th className="pb-2">Days</th>
              <th className="pb-2">Min stay</th>
              <th className="pb-2">Release</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {seasons.map((s) => (
              <tr key={s.key} className="border-t border-slate-100">
                <td className="py-1.5">
                  <input
                    value={s.name}
                    onChange={(e) => update(s, "Season", e.target.value)}
                    className="w-full rounded border border-slate-300 px-2 py-1 text-sm"
                  />
                </td>
                <td className="py-1.5">
                  <input
                    type="date"
                    value={s.startDate}
                    onChange={(e) => update(s, "Start Date", e.target.value)}
                    className="rounded border border-slate-300 px-2 py-1 text-sm"
                  />
                </td>
                <td className="py-1.5">
                  <input
                    type="date"
                    value={s.endDate}
                    onChange={(e) => update(s, "End Date", e.target.value)}
                    className="rounded border border-slate-300 px-2 py-1 text-sm"
                  />
                </td>
                <td className="py-1.5">
                  <input
                    value={s.days}
                    onChange={(e) => update(s, "Days", e.target.value)}
                    className="w-24 rounded border border-slate-300 px-2 py-1 text-sm font-mono"
                  />
                </td>
                <td className="py-1.5">
                  <input
                    type="number"
                    value={s.minStay ?? ""}
                    onChange={(e) =>
                      update(s, "Min Stay", e.target.value === "" ? null : Number(e.target.value))
                    }
                    className="w-16 rounded border border-slate-300 px-2 py-1 text-sm"
                  />
                </td>
                <td className="py-1.5">
                  <input
                    type="number"
                    value={s.release ?? ""}
                    onChange={(e) =>
                      update(s, "Release Period", e.target.value === "" ? null : Number(e.target.value))
                    }
                    className="w-16 rounded border border-slate-300 px-2 py-1 text-sm"
                  />
                </td>
                <td className="py-1.5 text-right">
                  <button
                    onClick={() => removeSeason(s)}
                    className="text-xs text-red-600 hover:underline"
                  >
                    Remove
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="mt-6 rounded-lg border border-slate-200 bg-white p-4">
        <h3 className="text-sm font-medium text-slate-700">Rate matrix preview</h3>
        <p className="mt-1 text-xs text-slate-500">
          {data.hotelRows.length} rate rows across {roomCount} room(s) ×{" "}
          {seasons.length} season(s) × {mealCount || 1} meal plan(s). Detailed
          rates are reviewed at the Preview step before generating the Excel.
        </p>
      </div>

      <StepFooter current="seasons" onStep={onStep} />
    </div>
  );
}
