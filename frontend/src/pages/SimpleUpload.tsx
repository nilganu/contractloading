import { useState } from "react";

type Status = "idle" | "working" | "done" | "error";

// In dev `/api` is proxied by Vite; in prod set VITE_API_BASE to the
// absolute backend URL, e.g. https://hotel-contract-backend.onrender.com/api.
const API_BASE = (import.meta as { env?: { VITE_API_BASE?: string } }).env?.VITE_API_BASE
  || "/api";

const TIMEOUT_MS = 15 * 60 * 1000;

// Short, readable message for a failed response. The backend sends JSON
// {"detail": "..."}; a proxy in front of it (Render) sends a full HTML page.
async function errorMessage(res: Response): Promise<string> {
  const text = await res.text();
  try {
    const detail = JSON.parse(text)?.detail;
    if (detail) return typeof detail === "string" ? detail : JSON.stringify(detail);
  } catch {
    /* not JSON */
  }
  if (res.status === 502 || res.status === 503 || res.status === 504) {
    return "The server stopped while reading this contract. Please try again in a minute.";
  }
  const plain = text.replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim();
  return `Error ${res.status}: ${plain.slice(0, 200) || res.statusText}`;
}

function friendlyError(err: unknown): string {
  if (err instanceof DOMException && err.name === "AbortError") {
    return "This took longer than 15 minutes, so it was stopped. Please try again.";
  }
  if (err instanceof TypeError) {
    return "Could not reach the server, or the connection dropped. Please try again in a minute.";
  }
  return err instanceof Error ? err.message : String(err);
}

export default function SimpleUpload() {
  const [file, setFile] = useState<File | null>(null);
  const [status, setStatus] = useState<Status>("idle");
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!file) return;
    setStatus("working");
    setError(null);

    const fd = new FormData();
    fd.append("file", file);

    // Large multi-hotel contracts can take several minutes; past this the
    // request is treated as lost so the page never spins forever.
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), TIMEOUT_MS);
    try {
      const res = await fetch(`${API_BASE}/contracts/extract-and-export`, {
        method: "POST",
        body: fd,
        signal: controller.signal,
      });
      if (!res.ok) {
        throw new Error(await errorMessage(res));
      }
      const blob = await res.blob();
      const cd = res.headers.get("content-disposition") || "";
      const m = cd.match(/filename="?([^";]+)"?/);
      const filename =
        m?.[1] ||
        `${file.name.replace(/\.[^.]+$/, "")}-moonstride-bundle.zip`;
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      setStatus("done");
    } catch (err) {
      setError(friendlyError(err));
      setStatus("error");
    } finally {
      window.clearTimeout(timer);
    }
  }

  return (
    <main className="mx-auto max-w-md p-8">
      <h1 className="text-2xl font-semibold text-slate-900">
        Hotel Contract Extractor
      </h1>
      <p className="mt-2 text-sm text-slate-600">
        Upload a hotel contract (PDF, Excel, Word or image). You get a ZIP
        with the moonstride hotel file, the supplements file and review notes.
      </p>

      <form
        onSubmit={submit}
        className="mt-6 space-y-4 rounded-lg border border-slate-200 bg-white p-6 shadow-sm"
      >
        <label className="block">
          <span className="text-sm font-medium text-slate-700">Contract file</span>
          <input
            type="file"
            accept=".pdf,.doc,.docx,.odt,.rtf,.xls,.xlsx,.csv,.tsv,.ods,.ppt,.pptx,.odp,.txt,.md,.html,.json,.xml,.png,.jpg,.jpeg,.webp,.gif"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            disabled={status === "working"}
            className="mt-2 block w-full rounded-md border border-slate-300 px-3 py-2 text-sm file:mr-3 file:rounded file:border-0 file:bg-slate-100 file:px-3 file:py-1.5 file:text-slate-700"
          />
          {file && (
            <span className="mt-1 block text-xs text-slate-500">
              {file.name} ({(file.size / 1024).toFixed(0)} KB)
            </span>
          )}
        </label>

        <button
          type="submit"
          disabled={!file || status === "working"}
          className="w-full rounded-md bg-slate-900 px-4 py-2.5 text-sm font-medium text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-400"
        >
          {status === "working" ? "Extracting…" : "Generate Bundle (ZIP)"}
        </button>

        {status === "working" && (
          <p className="text-xs text-slate-500">
            Reading the contract. This usually takes 1 to 3 minutes.
          </p>
        )}
        {error && (
          <div className="rounded border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-700">
            {error}
          </div>
        )}
        {status === "done" && !error && (
          <div className="rounded border border-emerald-300 bg-emerald-50 px-3 py-2 text-sm text-emerald-700">
            Done. Your ZIP should have started downloading.
          </div>
        )}
      </form>
    </main>
  );
}
