import { useState } from "react";

type Status = "idle" | "working" | "done" | "error";

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

    try {
      const res = await fetch("/api/contracts/extract-and-export", {
        method: "POST",
        body: fd,
      });
      if (!res.ok) {
        const body = await res.text();
        throw new Error(`${res.status} ${res.statusText}: ${body}`);
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
      setError(err instanceof Error ? err.message : String(err));
      setStatus("error");
    }
  }

  return (
    <main className="mx-auto max-w-md p-8">
      <h1 className="text-2xl font-semibold text-slate-900">
        Hotel Contract Extractor
      </h1>
      <p className="mt-2 text-sm text-slate-600">
        Upload a contract — PDF, Excel, Word, image, etc. GPT extracts it
        into a canonical model with strict schema enforcement; the backend
        deterministically writes two Moonstride imports — Hotel and
        Supplements — bundled into a single ZIP.
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
            Sending the file to GPT — this usually takes 30–90 seconds.
          </p>
        )}
        {error && (
          <div className="rounded border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-700">
            {error}
          </div>
        )}
        {status === "done" && !error && (
          <div className="rounded border border-emerald-300 bg-emerald-50 px-3 py-2 text-sm text-emerald-700">
            Done — your bundle (hotel + supplements) should have started downloading.
          </div>
        )}
      </form>
    </main>
  );
}
