import { useWizard } from "./WizardContext";

export const STEPS = [
  { key: "hotel", label: "Hotel" },
  { key: "rooms", label: "Rooms" },
  { key: "seasons", label: "Seasons" },
  { key: "child", label: "Child Policy" },
  { key: "supplements", label: "Supplements" },
  { key: "preview", label: "Preview" },
] as const;

export type StepKey = (typeof STEPS)[number]["key"];

export function StepNav({
  current,
  onStep,
}: {
  current: StepKey;
  onStep: (k: StepKey) => void;
}) {
  const { saving, saveError } = useWizard();
  return (
    <nav className="flex items-center gap-1 border-b border-slate-200 bg-white px-6 py-3">
      {STEPS.map((s, i) => {
        const active = current === s.key;
        return (
          <div key={s.key} className="flex items-center gap-1">
            <button
              onClick={() => onStep(s.key)}
              className={
                "rounded-md px-3 py-1.5 text-sm font-medium transition-colors " +
                (active
                  ? "bg-slate-900 text-white"
                  : "text-slate-600 hover:bg-slate-100")
              }
            >
              <span className="mr-1 text-slate-400">{i + 1}.</span>
              {s.label}
            </button>
            {i < STEPS.length - 1 && (
              <span className="px-1 text-slate-300">›</span>
            )}
          </div>
        );
      })}
      <div className="ml-auto text-xs">
        {saving ? (
          <span className="text-slate-400">Saving…</span>
        ) : saveError ? (
          <span className="text-red-600">Save error: {saveError}</span>
        ) : (
          <span className="text-emerald-600">All changes saved</span>
        )}
      </div>
    </nav>
  );
}

export function StepFooter({
  current,
  onStep,
}: {
  current: StepKey;
  onStep: (k: StepKey) => void;
}) {
  const idx = STEPS.findIndex((s) => s.key === current);
  const prev = idx > 0 ? STEPS[idx - 1] : null;
  const next = idx < STEPS.length - 1 ? STEPS[idx + 1] : null;
  return (
    <div className="mt-8 flex items-center justify-between">
      {prev ? (
        <button
          onClick={() => onStep(prev.key)}
          className="rounded-md border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
        >
          ← {prev.label}
        </button>
      ) : (
        <span />
      )}
      {next && (
        <button
          onClick={() => onStep(next.key)}
          className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800"
        >
          {next.label} →
        </button>
      )}
    </div>
  );
}
