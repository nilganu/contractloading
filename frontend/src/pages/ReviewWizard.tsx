import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";

import { getResult } from "../api/client";
import { SourcePane } from "../wizard/SourcePane";
import { StepNav, type StepKey } from "../wizard/StepNav";
import { WizardProvider, useWizard } from "../wizard/WizardContext";
import { HotelStep } from "../wizard/steps/HotelStep";
import { RoomsStep } from "../wizard/steps/RoomsStep";
import { SeasonsStep } from "../wizard/steps/SeasonsStep";
import { ChildPolicyStep } from "../wizard/steps/ChildPolicyStep";
import { SupplementsStep } from "../wizard/steps/SupplementsStep";
import { PreviewStep } from "../wizard/steps/PreviewStep";

function WizardInner() {
  const { data } = useWizard();
  const [step, setStep] = useState<StepKey>("hotel");

  return (
    <div className="flex h-screen flex-col bg-white text-slate-900">
      <header className="flex items-center justify-between border-b border-slate-200 px-6 py-3">
        <div>
          <div className="text-sm font-semibold text-slate-900">
            {data.workbookSummary.sourceFile}
          </div>
          <div className="text-xs text-slate-500">
            {data.hotelRows.length} rate rows · {data.dynamicColumns.childColumns.length} child
            columns · {data.extractionNotes.length} notes
          </div>
        </div>
        <Link to="/" className="text-sm text-slate-500 hover:text-slate-800 hover:underline">
          + New upload
        </Link>
      </header>

      <StepNav current={step} onStep={setStep} />

      <div className="grid min-h-0 flex-1 grid-cols-5 overflow-hidden">
        <div className="col-span-3 min-h-0 overflow-y-auto bg-slate-50 px-8 py-6">
          {step === "hotel" && <HotelStep onStep={setStep} />}
          {step === "rooms" && <RoomsStep onStep={setStep} />}
          {step === "seasons" && <SeasonsStep onStep={setStep} />}
          {step === "child" && <ChildPolicyStep onStep={setStep} />}
          {step === "supplements" && <SupplementsStep onStep={setStep} />}
          {step === "preview" && <PreviewStep onStep={setStep} />}
        </div>
        <div className="col-span-2 min-h-0 overflow-hidden border-l border-slate-200 bg-slate-100">
          <SourcePane />
        </div>
      </div>
    </div>
  );
}

export default function ReviewWizard() {
  const { jobId = "" } = useParams();
  const { data: jobResult, isLoading, error } = useQuery({
    queryKey: ["result", jobId],
    queryFn: () => getResult(jobId),
  });

  if (isLoading) return <div className="p-8 text-slate-500">Loading…</div>;
  if (error)
    return <div className="p-8 text-red-600">Failed to load: {(error as Error).message}</div>;
  if (!jobResult?.result)
    return <div className="p-8 text-slate-500">No result available.</div>;

  return (
    <WizardProvider jobId={jobId} initial={jobResult.result}>
      <WizardInner />
    </WizardProvider>
  );
}
