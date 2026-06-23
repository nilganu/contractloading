import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";

import { getJob } from "../api/client";
import type { JobStatus, JobStatusResponse } from "../types";
import { useEffect } from "react";

const STEPS: { key: JobStatus; label: string }[] = [
  { key: "uploaded", label: "Uploaded" },
  { key: "detecting_file_type", label: "Detecting file type" },
  { key: "parsing", label: "Parsing file" },
  { key: "classifying_sheets_or_pages", label: "Classifying sheets / pages" },
  { key: "running_ocr_or_vision", label: "OCR / vision (if needed)" },
  { key: "building_intermediate_representation", label: "Building intermediate representation" },
  { key: "running_llm_extraction", label: "LLM extraction" },
  { key: "normalizing", label: "Normalizing" },
  { key: "validating", label: "Validating" },
  { key: "ready_for_review", label: "Ready for review" },
];

function stepClass(step: JobStatus, job: JobStatusResponse | undefined): string {
  if (!job) return "";
  if (job.status === "failed") {
    return STEPS.findIndex((s) => s.key === step) === STEPS.length - 1 ? "" : "done";
  }
  const cur = STEPS.findIndex((s) => s.key === job.status);
  const at = STEPS.findIndex((s) => s.key === step);
  if (at < cur) return "done";
  if (at === cur) return "current";
  return "";
}

export default function JobPage() {
  const { jobId = "" } = useParams();
  const navigate = useNavigate();
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["job", jobId],
    queryFn: () => getJob(jobId),
    refetchInterval: (q) => {
      const s = (q.state.data as JobStatusResponse | undefined)?.status;
      if (s === "ready_for_review" || s === "completed" || s === "failed") return false;
      return 600;
    },
  });

  useEffect(() => {
    if (data?.status === "ready_for_review" || data?.status === "completed") {
      const t = setTimeout(() => navigate(`/jobs/${jobId}/review`), 250);
      return () => clearTimeout(t);
    }
  }, [data?.status, jobId, navigate]);

  if (isLoading) return <div className="shell">Loading…</div>;
  if (isError) return <div className="shell error-text">Failed to load job: {String(error)}</div>;
  if (!data) return null;

  const hotelSheets = data.sheetSummary.filter((s) => s.classification === "hotel_contract");
  const indexSheets = data.sheetSummary.filter((s) => s.classification === "index_reference");

  return (
    <div className="shell">
      <div className="header">
        <h1>Job {jobId.slice(0, 8)}…</h1>
        <Link to="/">+ New upload</Link>
      </div>

      <div className="panel">
        <div className="row">
          <strong>{data.fileName}</strong>
          <span className="muted">({data.fileType ?? "unknown"})</span>
          <div className="spacer" />
          <span className="badge info">{data.status}</span>
          <span className="muted">{data.progress}%</span>
        </div>
      </div>

      <div className="panel">
        <h3 style={{ marginTop: 0 }}>Pipeline</h3>
        <div className="timeline">
          {STEPS.map((s) => (
            <div className={`timeline-step ${stepClass(s.key, data)} ${data.status === "failed" && s.key === "ready_for_review" ? "failed" : ""}`} key={s.key}>
              <div className="dot" />
              <div>{s.label}</div>
            </div>
          ))}
          {data.status === "failed" && (
            <div className="timeline-step failed">
              <div className="dot" />
              <div className="error-text">Failed: {data.errors.join("; ")}</div>
            </div>
          )}
        </div>
      </div>

      <div className="panel">
        <h3 style={{ marginTop: 0 }}>Pre-extraction summary</h3>
        <div className="cards">
          <div className="card">
            <div className="label">Sheets / pages</div>
            <div className="value">{data.sheetSummary.length}</div>
          </div>
          <div className="card">
            <div className="label">Hotel contract sheets</div>
            <div className="value">{hotelSheets.length}</div>
          </div>
          <div className="card">
            <div className="label">Index / reference</div>
            <div className="value">{indexSheets.length}</div>
          </div>
          <div className="card">
            <div className="label">Warnings</div>
            <div className="value warning-text">{data.warnings.length}</div>
          </div>
          <div className="card">
            <div className="label">Errors</div>
            <div className="value error-text">{data.errors.length}</div>
          </div>
        </div>
      </div>

      {data.sheetSummary.length > 0 && (
        <div className="panel">
          <h3 style={{ marginTop: 0 }}>Detected sheets / pages</h3>
          <table className="data">
            <thead>
              <tr>
                <th>ID</th>
                <th>Classification</th>
                <th>Detected hotel</th>
                <th>Source ref</th>
              </tr>
            </thead>
            <tbody>
              {data.sheetSummary.map((s) => (
                <tr key={s.id}>
                  <td>{s.id}</td>
                  <td>
                    <span className={"badge " + (s.classification === "hotel_contract" ? "success" : s.classification === "index_reference" ? "info" : "warning")}>
                      {s.classification}
                    </span>
                  </td>
                  <td>{s.detectedHotelName ?? "—"}</td>
                  <td className="muted" style={{ maxWidth: 480, overflow: "hidden", textOverflow: "ellipsis" }}>
                    {s.sourceRef}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {(data.status === "ready_for_review" || data.status === "completed") && (
        <div className="row">
          <div className="spacer" />
          <Link to={`/jobs/${jobId}/review`} className="primary" style={{ padding: "8px 14px", borderRadius: 6, color: "white", background: "#1565c0" }}>
            Open review →
          </Link>
        </div>
      )}
    </div>
  );
}
