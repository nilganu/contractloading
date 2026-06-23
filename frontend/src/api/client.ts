import type {
  AuditResponse,
  JobResultResponse,
  JobStatusResponse,
  NormalizedExtractionResult,
  TemplateMetadata,
} from "../types";

// In dev: `/api` is proxied to the backend by Vite (see vite.config.ts).
// In prod: set VITE_API_BASE to the absolute backend URL,
// e.g. "https://hotel-contract-backend.onrender.com/api".
const BASE = (import.meta as { env?: { VITE_API_BASE?: string } }).env?.VITE_API_BASE
  || "/api";

async function asJson<T>(resp: Response): Promise<T> {
  if (!resp.ok) {
    const body = await resp.text();
    throw new Error(`${resp.status} ${resp.statusText}: ${body}`);
  }
  return resp.json() as Promise<T>;
}

export async function uploadContract(
  file: File,
  options: Record<string, string | boolean | undefined | null>
): Promise<JobStatusResponse> {
  const fd = new FormData();
  fd.set("file", file);
  for (const [k, v] of Object.entries(options)) {
    if (v === undefined || v === null || v === "") continue;
    fd.set(k, String(v));
  }
  const resp = await fetch(`${BASE}/contracts/upload`, {
    method: "POST",
    body: fd,
  });
  return asJson(resp);
}

export async function getJob(jobId: string): Promise<JobStatusResponse> {
  return asJson(await fetch(`${BASE}/contracts/jobs/${jobId}`));
}

export async function getResult(jobId: string): Promise<JobResultResponse> {
  return asJson(await fetch(`${BASE}/contracts/jobs/${jobId}/result`));
}

export async function patchResult(
  jobId: string,
  result: NormalizedExtractionResult
): Promise<JobResultResponse> {
  return asJson(
    await fetch(`${BASE}/contracts/jobs/${jobId}/result`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ result }),
    })
  );
}

export async function revalidate(jobId: string): Promise<JobResultResponse> {
  return asJson(
    await fetch(`${BASE}/contracts/jobs/${jobId}/validate`, {
      method: "POST",
    })
  );
}

export interface EnrichSummary {
  hotelsProcessed: number;
  fieldsFilled: number;
  skipped?: boolean;
  message?: string;
  details?: { hotel: string; filled?: string[]; error?: string }[];
}

export async function enrichMetadata(
  jobId: string,
  force = false
): Promise<{ jobId: string; result: NormalizedExtractionResult; summary: EnrichSummary }> {
  const params = new URLSearchParams({ force: String(force) });
  return asJson(
    await fetch(
      `${BASE}/contracts/jobs/${jobId}/enrich-metadata?${params.toString()}`,
      { method: "POST" }
    )
  );
}

export async function exportXlsx(
  jobId: string,
  mode: string,
  includeInternal: boolean
): Promise<Blob> {
  const params = new URLSearchParams({
    mode,
    include_internal: String(includeInternal),
  });
  const resp = await fetch(
    `${BASE}/contracts/jobs/${jobId}/export.xlsx?${params.toString()}`
  );
  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(`Export failed: ${resp.status} ${text}`);
  }
  return resp.blob();
}

export async function getTemplate(): Promise<TemplateMetadata> {
  return asJson(await fetch(`${BASE}/contracts/template`));
}

export interface ExportPreview {
  templateId: string;
  rateType: string;
  headers: string[];
  rows: Record<string, string | number | null>[];
}

export async function getExportPreview(
  jobId: string,
  mode: string
): Promise<ExportPreview> {
  const params = new URLSearchParams({ mode });
  return asJson(
    await fetch(
      `${BASE}/contracts/jobs/${jobId}/export-preview?${params.toString()}`
    )
  );
}

export async function getSourcePreview(
  jobId: string,
  sourceRef: string
): Promise<unknown> {
  const enc = encodeURIComponent(sourceRef);
  return asJson(
    await fetch(`${BASE}/contracts/jobs/${jobId}/source/${enc}`)
  );
}

export async function getAudit(jobId: string): Promise<AuditResponse> {
  return asJson(await fetch(`${BASE}/contracts/jobs/${jobId}/audit`));
}
