import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";

import {
  enrichMetadata,
  exportXlsx,
  getAudit,
  getResult,
  getTemplate,
  patchResult,
  revalidate as revalidateApi,
} from "../api/client";
import type { NormalizedExtractionResult } from "../types";

import HotelRowsGrid from "../components/HotelRowsGrid";
import ExportPreviewTab from "../components/ExportPreviewTab";
import ChildPoliciesTab from "../components/ChildPoliciesTab";
import ExtractionNotesTab from "../components/ExtractionNotesTab";
import ValidationIssuesTab from "../components/ValidationIssuesTab";
import RawJsonTab from "../components/RawJsonTab";
import AuditTab from "../components/AuditTab";
import SummaryDashboard from "../components/SummaryDashboard";

type Tab =
  | "summary"
  | "rows"
  | "preview"
  | "child"
  | "notes"
  | "issues"
  | "json"
  | "audit";

const TABS: { key: Tab; label: string }[] = [
  { key: "summary", label: "Summary" },
  { key: "rows", label: "Hotel rows" },
  { key: "preview", label: "Export preview" },
  { key: "child", label: "Child policies" },
  { key: "notes", label: "Extraction notes" },
  { key: "issues", label: "Validation issues" },
  { key: "json", label: "Raw JSON" },
  { key: "audit", label: "Audit" },
];

export default function ReviewPage() {
  const { jobId = "" } = useParams();
  const qc = useQueryClient();
  const [tab, setTab] = useState<Tab>("summary");
  const [exportMode, setExportMode] = useState<string>("moonstride_auto");
  const [includeInternal, setIncludeInternal] = useState(false);
  const [exportStatus, setExportStatus] = useState<string | null>(null);
  const [enrichStatus, setEnrichStatus] = useState<string | null>(null);

  const { data: jobResult, refetch } = useQuery({
    queryKey: ["result", jobId],
    queryFn: () => getResult(jobId),
  });
  const { data: template } = useQuery({
    queryKey: ["template"],
    queryFn: () => getTemplate(),
  });
  const { data: audit } = useQuery({
    queryKey: ["audit", jobId],
    queryFn: () => getAudit(jobId),
  });

  const patch = useMutation({
    mutationFn: (next: NormalizedExtractionResult) => patchResult(jobId, next),
    onSuccess: (data) => {
      qc.setQueryData(["result", jobId], data);
    },
  });

  const reval = useMutation({
    mutationFn: () => revalidateApi(jobId),
    onSuccess: () => refetch(),
  });

  const enrich = useMutation({
    mutationFn: () => enrichMetadata(jobId, false),
    onSuccess: (data) => {
      qc.setQueryData(["result", jobId], { jobId, status: jobResult?.status, result: data.result });
      qc.invalidateQueries({ queryKey: ["export-preview", jobId] });
      const s = data.summary;
      setEnrichStatus(
        s.skipped
          ? s.message ?? "Enrichment skipped."
          : `Filled ${s.fieldsFilled} field(s) across ${s.hotelsProcessed} hotel(s) via GPT — review the AI-inferred values.`
      );
    },
    onError: (e) => setEnrichStatus(e instanceof Error ? e.message : String(e)),
  });

  const result = jobResult?.result;
  const blockingErrors = useMemo(
    () => result?.validationIssues.filter((i) => i.severity === "error").length ?? 0,
    [result]
  );

  async function onExport() {
    setExportStatus(null);
    try {
      const blob = await exportXlsx(jobId, exportMode, includeInternal || exportMode === "dynamic_review");
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${jobId}-${exportMode}.xlsx`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      setExportStatus("Downloaded.");
    } catch (e) {
      setExportStatus(e instanceof Error ? e.message : String(e));
    }
  }

  if (!result || !template) {
    return <div className="shell">Loading…</div>;
  }

  return (
    <div className="shell">
      <div className="header">
        <h1>{result.workbookSummary.sourceFile}</h1>
        <div className="row">
          <Link to="/" className="muted">+ New upload</Link>
          <Link to={`/jobs/${jobId}`} className="muted" style={{ marginLeft: 12 }}>
            ← Job progress
          </Link>
        </div>
      </div>

      <div className="panel">
        <div className="row">
          <span className="badge info">{jobResult.status}</span>
          <span className="muted">{result.hotelRows.length} rows</span>
          <span className="muted">
            {result.dynamicColumns.childColumns.length} child columns
          </span>
          <span className="muted">{result.extractionNotes.length} notes</span>
          {blockingErrors > 0 ? (
            <span className="badge error">{blockingErrors} blocking</span>
          ) : (
            <span className="badge success">No blocking errors</span>
          )}
          <div className="spacer" />
          <button
            onClick={() => { setEnrichStatus(null); enrich.mutate(); }}
            disabled={enrich.isPending}
            title="Use GPT to fill missing hotel address / contact / geo fields (AI-inferred — verify before export)"
          >
            {enrich.isPending ? "Filling…" : "Fill missing hotel info (GPT)"}
          </button>
          <button onClick={() => reval.mutate()} disabled={reval.isPending}>
            Re-validate
          </button>
          <select
            value={exportMode}
            onChange={(e) => setExportMode(e.target.value)}
            title="Export mode"
          >
            <option value="moonstride_auto">Moonstride (auto-detect format)</option>
            <option value="moonstride_ppn">Moonstride · Per Person Per Night</option>
            <option value="moonstride_prn_ac">Moonstride · Per Room (Adult / Child)</option>
            <option value="moonstride_prn_pax">Moonstride · Per Room (Pax count)</option>
            <option value="dynamic_export">Dynamic export (internal)</option>
            <option value="strict_template">Strict template (internal)</option>
            <option value="dynamic_review">Dynamic review (internal cols)</option>
          </select>
          <label className="muted" title="Include internal _confidence / _warnings / _sourceRefs columns">
            <input
              type="checkbox"
              checked={includeInternal}
              onChange={(e) => setIncludeInternal(e.target.checked)}
            />
            internal
          </label>
          <button
            className="primary"
            onClick={onExport}
            disabled={blockingErrors > 0}
            title={
              blockingErrors > 0
                ? "Fix blocking validation errors before exporting"
                : "Export Moonstride workbook"
            }
          >
            Export XLSX
          </button>
        </div>
        {enrichStatus && (
          <div className="muted" style={{ marginTop: 6 }}>
            {enrichStatus}
          </div>
        )}
        {exportStatus && (
          <div className="muted" style={{ marginTop: 6 }}>
            {exportStatus}
          </div>
        )}
      </div>

      <div className="tabs">
        {TABS.map((t) => (
          <button
            key={t.key}
            className={"tab" + (tab === t.key ? " active" : "")}
            onClick={() => setTab(t.key)}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === "summary" && (
        <SummaryDashboard result={result} sheetSummary={undefined} />
      )}
      {tab === "rows" && (
        <HotelRowsGrid
          result={result}
          template={template}
          onPatch={(next) => patch.mutate(next)}
          patching={patch.isPending}
        />
      )}
      {tab === "preview" && (
        <ExportPreviewTab jobId={jobId} exportMode={exportMode} />
      )}
      {tab === "child" && (
        <ChildPoliciesTab result={result} />
      )}
      {tab === "notes" && (
        <ExtractionNotesTab
          result={result}
          onPatch={(next) => patch.mutate(next)}
        />
      )}
      {tab === "issues" && (
        <ValidationIssuesTab
          result={result}
          onJumpToRows={() => setTab("rows")}
          onPatch={(next) => patch.mutate(next)}
        />
      )}
      {tab === "json" && (
        <RawJsonTab
          result={result}
          onPatch={(next) => patch.mutate(next)}
        />
      )}
      {tab === "audit" && <AuditTab audit={audit} />}
    </div>
  );
}
