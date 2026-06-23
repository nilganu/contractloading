import type { FieldState } from "./WizardContext";

interface FieldProps {
  label: string;
  value: string | number | null | undefined;
  onChange: (v: string) => void;
  onCommit?: () => void;
  state?: FieldState;
  type?: "text" | "number" | "email" | "url" | "time" | "date";
  placeholder?: string;
  options?: string[];
  className?: string;
}

function Badge({ state }: { state: FieldState }) {
  if (state === "enriched")
    return (
      <span
        title="Filled by AI from the hotel name — please verify"
        className="rounded bg-cyan-100 px-1.5 py-0.5 text-[10px] font-semibold text-cyan-800"
      >
        🌐 enriched
      </span>
    );
  if (state === "verify")
    return (
      <span
        title="Low confidence — verify against the source"
        className="rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-semibold text-amber-800"
      >
        ⚠ verify
      </span>
    );
  if (state === "edited")
    return (
      <span className="rounded bg-emerald-100 px-1.5 py-0.5 text-[10px] font-semibold text-emerald-800">
        edited
      </span>
    );
  return null;
}

export function Field({
  label,
  value,
  onChange,
  onCommit,
  state = "none",
  type = "text",
  placeholder,
  options,
  className = "",
}: FieldProps) {
  const stringValue = value === null || value === undefined ? "" : String(value);
  const cls =
    "mt-1 block w-full rounded-md border border-slate-300 px-2.5 py-1.5 text-sm focus:border-slate-500 focus:outline-none " +
    (state === "enriched" ? "field-enriched " : "") +
    (state === "verify" ? "field-flagged " : "");

  return (
    <label className={"block " + className}>
      <span className="flex items-center gap-2 text-xs font-medium text-slate-700">
        {label}
        <Badge state={state} />
      </span>
      {options ? (
        <select
          value={stringValue}
          onChange={(e) => onChange(e.target.value)}
          onBlur={onCommit}
          className={cls}
        >
          <option value="">—</option>
          {options.map((o) => (
            <option key={o} value={o}>
              {o}
            </option>
          ))}
        </select>
      ) : (
        <input
          type={type}
          value={stringValue}
          placeholder={placeholder}
          onChange={(e) => onChange(e.target.value)}
          onBlur={onCommit}
          className={cls}
        />
      )}
    </label>
  );
}
