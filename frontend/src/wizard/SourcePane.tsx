import { useWizard } from "./WizardContext";

function firstPage(ref: string | null): number | null {
  if (!ref) return null;
  const tail = ref.includes("|") ? ref.split("|").slice(1).join("|") : ref;
  const m = tail.match(/\d+/);
  return m ? Number(m[0]) : null;
}

export function SourcePane() {
  const { jobId, activeSourceRef, data } = useWizard();
  const fmt = data.workbookSummary.inputFormat;
  const fileUrl = `/api/contracts/jobs/${jobId}/file`;

  if (fmt === "pdf") {
    const page = firstPage(activeSourceRef);
    const anchor = page ? `#page=${page}&view=FitH` : "#view=FitH";
    return (
      <div className="flex h-full flex-col">
        <div className="border-b border-slate-200 bg-slate-100 px-4 py-2">
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">
            Source PDF{page ? ` · page ${page}` : ""}
          </div>
        </div>
        <iframe
          title="Contract PDF"
          src={`${fileUrl}${anchor}`}
          className="min-h-0 w-full flex-1 border-0 bg-white"
        />
      </div>
    );
  }

  if (fmt === "image") {
    return (
      <div className="flex h-full flex-col">
        <div className="border-b border-slate-200 bg-slate-100 px-4 py-2">
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">
            Source image
          </div>
        </div>
        <div className="min-h-0 flex-1 overflow-auto bg-slate-100 p-4">
          <img src={fileUrl} alt="Contract source" className="mx-auto max-w-full object-contain" />
        </div>
      </div>
    );
  }

  // Excel / DOCX / other: not rendered inline (matches the reference's behaviour).
  return (
    <div className="flex h-full flex-col items-center justify-center gap-2 p-6 text-center text-sm text-slate-500">
      <div className="text-3xl">📄</div>
      <div className="font-medium text-slate-700">{data.workbookSummary.sourceFile}</div>
      <div className="text-xs">
        This file type ({fmt}) doesn&apos;t render inline.
      </div>
      <div className="text-xs">
        It was parsed directly — review and edit the extracted data on the left.
      </div>
    </div>
  );
}
