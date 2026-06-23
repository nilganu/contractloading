import { useMemo } from "react";

import type { HotelRow, NormalizedExtractionResult } from "../../types";
import { ALLOWED_BED_TYPES, ALLOWED_MEAL_PLANS } from "../masterdata";
import { StepFooter, type StepKey } from "../StepNav";
import { useWizard } from "../WizardContext";

interface RoomAgg {
  room: string;
  hotel: string;
  bedType: string;
  minAdult: number | null;
  maxAdult: number | null;
  maxPax: number | null;
  rollaways: number | null;
  cribs: number | null;
}

function get(r: HotelRow, k: string): unknown {
  return (r as unknown as Record<string, unknown>)[k];
}

export function RoomsStep({ onStep }: { onStep: (k: StepKey) => void }) {
  const { data, setData } = useWizard();

  const rooms = useMemo<RoomAgg[]>(() => {
    const map = new Map<string, RoomAgg>();
    for (const r of data.hotelRows as HotelRow[]) {
      const room = (r["Room Name"] as string) || "(unnamed room)";
      if (map.has(room)) continue;
      map.set(room, {
        room,
        hotel: (r["Hotel Name"] as string) || "",
        bedType: (get(r, "Bed Type") as string) || "",
        minAdult: r["Min Adult"] as number | null,
        maxAdult: r["Max Adult"] as number | null,
        maxPax: r["Max Pax"] as number | null,
        rollaways: (get(r, "Max Rollaways") as number | null) ?? null,
        cribs: (get(r, "Max Cribs (Cots)") as number | null) ?? null,
      });
    }
    return [...map.values()];
  }, [data.hotelRows]);

  const presentMealPlans = useMemo(() => {
    const s = new Set<string>();
    for (const r of data.hotelRows as HotelRow[]) {
      const mp = r["Meal Plan"] as string | null;
      if (mp) s.add(mp);
    }
    return s;
  }, [data.hotelRows]);

  function updateRoom(roomName: string, field: string, value: string | number | null) {
    setData((prev: NormalizedExtractionResult) => ({
      ...prev,
      hotelRows: prev.hotelRows.map((r) =>
        ((r as HotelRow)["Room Name"] as string) === roomName
          ? { ...r, [field]: value, _reviewState: "edited" }
          : r
      ),
    }));
  }

  function removeRoom(roomName: string) {
    setData((prev) => ({
      ...prev,
      hotelRows: prev.hotelRows.filter(
        (r) => ((r as HotelRow)["Room Name"] as string) !== roomName
      ),
    }));
  }

  function addRoom() {
    setData((prev) => {
      const template = (prev.hotelRows[0] as HotelRow) ?? null;
      const base: Record<string, unknown> = template
        ? { ...(template as unknown as Record<string, unknown>) }
        : { sourceSheetOrPage: "" };
      const fresh: Record<string, unknown> = {
        ...base,
        id: `row_${Math.random().toString(36).slice(2, 10)}`,
        "Room Name": "New Room",
        "Bed Type": "",
        SGL: null,
        DBL: null,
        TPL: null,
        QDP: null,
        "Extra Bed": null,
        dynamicChildValues: {},
        _reviewState: "edited",
      };
      return { ...prev, hotelRows: [...prev.hotelRows, fresh as unknown as HotelRow] };
    });
  }

  function toggleMealPlan(mp: string) {
    if (!presentMealPlans.has(mp)) return; // can't fabricate rates for a new board
    setData((prev) => ({
      ...prev,
      hotelRows: prev.hotelRows.filter((r) => (r as HotelRow)["Meal Plan"] !== mp),
    }));
  }

  const numInput = (room: string, field: string, value: number | null, w = "w-16") => (
    <input
      type="number"
      value={value ?? ""}
      onChange={(e) => updateRoom(room, field, e.target.value === "" ? null : Number(e.target.value))}
      className={`${w} rounded border border-slate-300 px-2 py-1 text-sm`}
    />
  );

  return (
    <div>
      <header className="mb-6">
        <h2 className="text-xl font-semibold text-slate-900">Rooms &amp; meal plans</h2>
        <p className="mt-1 text-sm text-slate-600">
          Review the room categories and the meal plans available across the contract.
        </p>
      </header>

      <div className="rounded-lg border border-slate-200 bg-white p-4">
        <h3 className="text-sm font-medium text-slate-700">Rooms</h3>
        <table className="mt-3 w-full text-sm">
          <thead>
            <tr className="text-left text-xs uppercase text-slate-500">
              <th className="pb-2">Name</th>
              <th className="pb-2">Bed type</th>
              <th className="pb-2">Min adult</th>
              <th className="pb-2">Max adult</th>
              <th className="pb-2">Max pax</th>
              <th className="pb-2">Rollaways</th>
              <th className="pb-2">Cribs</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {rooms.map((room) => (
              <tr key={room.room} className="border-t border-slate-100">
                <td className="py-1.5">
                  <input
                    value={room.room}
                    onChange={(e) => updateRoom(room.room, "Room Name", e.target.value)}
                    className="w-full rounded border border-slate-300 px-2 py-1 text-sm"
                  />
                </td>
                <td className="py-1.5">
                  <select
                    value={room.bedType}
                    onChange={(e) => updateRoom(room.room, "Bed Type", e.target.value)}
                    className="w-full rounded border border-slate-300 px-2 py-1 text-sm"
                  >
                    <option value="">—</option>
                    {ALLOWED_BED_TYPES.map((b) => (
                      <option key={b} value={b}>
                        {b}
                      </option>
                    ))}
                  </select>
                </td>
                <td className="py-1.5">{numInput(room.room, "Min Adult", room.minAdult)}</td>
                <td className="py-1.5">{numInput(room.room, "Max Adult", room.maxAdult)}</td>
                <td className="py-1.5">{numInput(room.room, "Max Pax", room.maxPax)}</td>
                <td className="py-1.5">{numInput(room.room, "Max Rollaways", room.rollaways)}</td>
                <td className="py-1.5">{numInput(room.room, "Max Cribs (Cots)", room.cribs)}</td>
                <td className="py-1.5 text-right">
                  <button
                    onClick={() => removeRoom(room.room)}
                    className="text-xs text-red-600 hover:underline"
                  >
                    Remove
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <button
          onClick={addRoom}
          className="mt-3 rounded-md border border-slate-300 bg-slate-50 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-100"
        >
          + Add room
        </button>
      </div>

      <div className="mt-6 rounded-lg border border-slate-200 bg-white p-4">
        <h3 className="text-sm font-medium text-slate-700">Meal plans</h3>
        <p className="mt-1 text-xs text-slate-500">
          Checked = present in the contract. Unchecking removes all rate rows for that board.
        </p>
        <div className="mt-3 flex flex-wrap gap-2">
          {ALLOWED_MEAL_PLANS.map((mp) => (
            <label
              key={mp}
              className="flex items-center gap-1.5 rounded-md border border-slate-200 bg-slate-50 px-2.5 py-1 text-xs"
            >
              <input
                type="checkbox"
                checked={presentMealPlans.has(mp)}
                onChange={() => toggleMealPlan(mp)}
              />
              {mp}
            </label>
          ))}
        </div>
      </div>

      <StepFooter current="rooms" onStep={onStep} />
    </div>
  );
}
