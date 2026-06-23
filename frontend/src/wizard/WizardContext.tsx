import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { patchResult } from "../api/client";
import type { HotelRow, NormalizedExtractionResult } from "../types";

type Updater = (prev: NormalizedExtractionResult) => NormalizedExtractionResult;

interface WizardContextValue {
  jobId: string;
  data: NormalizedExtractionResult;
  setData: (updater: Updater) => void;
  /** Replace the whole result (used after server actions like enrichment). */
  replaceData: (next: NormalizedExtractionResult) => void;
  /** Force-persist pending edits immediately (eg before previewing/exporting). */
  flushNow: () => Promise<void>;
  saving: boolean;
  saveError: string | null;
  /** The source ref currently shown in the SourcePane (if any). */
  activeSourceRef: string | null;
  setActiveSourceRef: (ref: string | null) => void;
}

const Ctx = createContext<WizardContextValue | null>(null);

export function useWizard(): WizardContextValue {
  const v = useContext(Ctx);
  if (!v) throw new Error("useWizard must be used inside <WizardProvider>");
  return v;
}

export function WizardProvider({
  jobId,
  initial,
  children,
}: {
  jobId: string;
  initial: NormalizedExtractionResult;
  children: ReactNode;
}) {
  const [data, setLocal] = useState<NormalizedExtractionResult>(initial);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [activeSourceRef, setActiveSourceRef] = useState<string | null>(null);

  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const latest = useRef(data);
  latest.current = data;

  const flush = useCallback(async () => {
    const snapshot = latest.current;
    setSaving(true);
    setSaveError(null);
    try {
      await patchResult(jobId, snapshot);
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }, [jobId]);

  const scheduleSave = useCallback(() => {
    if (saveTimer.current) clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(() => void flush(), 900);
  }, [flush]);

  const setData = useCallback(
    (updater: Updater) => {
      setLocal((prev) => updater(prev));
      scheduleSave();
    },
    [scheduleSave]
  );

  const replaceData = useCallback((next: NormalizedExtractionResult) => {
    if (saveTimer.current) clearTimeout(saveTimer.current);
    setLocal(next);
  }, []);

  // Persist any pending edit when the component unmounts.
  useEffect(() => {
    return () => {
      if (saveTimer.current) {
        clearTimeout(saveTimer.current);
        void flush();
      }
    };
  }, [flush]);

  return (
    <Ctx.Provider
      value={{
        jobId,
        data,
        setData,
        replaceData,
        flushNow: flush,
        saving,
        saveError,
        activeSourceRef,
        setActiveSourceRef,
      }}
    >
      {children}
    </Ctx.Provider>
  );
}

// ---- Row-derivation helpers shared by the steps --------------------------

export function hotelNames(rows: HotelRow[]): string[] {
  const seen: string[] = [];
  for (const r of rows) {
    const n = (r["Hotel Name"] as string) || "Unknown Hotel";
    if (!seen.includes(n)) seen.push(n);
  }
  return seen;
}

export function rowsForHotel(
  rows: HotelRow[],
  hotelName: string
): HotelRow[] {
  return rows.filter(
    (r) => ((r["Hotel Name"] as string) || "Unknown Hotel") === hotelName
  );
}

/** Update one hotel-level field across every row of a hotel. */
export function patchHotelField(
  result: NormalizedExtractionResult,
  hotelName: string,
  field: string,
  value: string | number | null
): NormalizedExtractionResult {
  return {
    ...result,
    hotelRows: result.hotelRows.map((r) => {
      const name = ((r as HotelRow)["Hotel Name"] as string) || "Unknown Hotel";
      if (name !== hotelName) return r;
      const meta: Record<string, unknown> = {
        ...((r as unknown as Record<string, unknown>)._cellMeta as
          | Record<string, unknown>
          | undefined),
      };
      // A manual edit overrides any AI-inferred flag for that specific field.
      meta[field] = { userEdited: true };
      return {
        ...r,
        [field]: value,
        _cellMeta: meta,
        _reviewState: "edited",
      } as unknown as HotelRow;
    }),
  };
}

/** Update one field on every row matching a hotel + room name. */
export function patchRoomField(
  result: NormalizedExtractionResult,
  hotelName: string,
  roomName: string,
  field: string,
  value: string | number | null
): NormalizedExtractionResult {
  return {
    ...result,
    hotelRows: result.hotelRows.map((r) => {
      const row = r as HotelRow;
      const name = (row["Hotel Name"] as string) || "Unknown Hotel";
      if (name !== hotelName || row["Room Name"] !== roomName) return r;
      return { ...r, [field]: value, _reviewState: "edited" };
    }),
  };
}

/** Update one field on every row of a season (matched by start+end date). */
export function patchSeasonField(
  result: NormalizedExtractionResult,
  startDate: string | null,
  endDate: string | null,
  field: string,
  value: string | number | null
): NormalizedExtractionResult {
  return {
    ...result,
    hotelRows: result.hotelRows.map((r) => {
      const row = r as HotelRow;
      if (row["Start Date"] !== startDate || row["End Date"] !== endDate) return r;
      return { ...r, [field]: value, _reviewState: "edited" };
    }),
  };
}

/** Update one field on a single row by id. */
export function patchRowField(
  result: NormalizedExtractionResult,
  rowId: string,
  field: string,
  value: string | number | null
): NormalizedExtractionResult {
  return {
    ...result,
    hotelRows: result.hotelRows.map((r) =>
      (r as HotelRow).id === rowId
        ? { ...r, [field]: value, _reviewState: "edited" }
        : r
    ),
  };
}

export type FieldState = "enriched" | "verify" | "edited" | "none";

/** Decide the badge state for a hotel-level field from the row's metadata. */
export function fieldState(row: HotelRow, field: string): FieldState {
  const meta = (row as unknown as Record<string, unknown>)._cellMeta as
    | Record<string, { aiInferred?: boolean; userEdited?: boolean }>
    | undefined;
  const cell = meta?.[field];
  if (cell?.aiInferred) return "enriched";
  if (cell?.userEdited) return "edited";
  const warnings = ((row as unknown as Record<string, unknown>)._warnings as string[]) || [];
  if (warnings.some((w) => w.includes(field))) return "verify";
  const conf = ((row as unknown as Record<string, unknown>)._confidence as number) ?? 1;
  if (conf < 0.4) return "verify";
  return "none";
}
