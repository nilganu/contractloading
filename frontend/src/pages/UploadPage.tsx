import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { uploadContract } from "../api/client";
import type { ChildColumnMode, ExtractionMode } from "../types";

const ACCEPT = ".xlsx,.xls,.pdf,.docx,.png,.jpg,.jpeg,.tif,.tiff";

export default function UploadPage() {
  const navigate = useNavigate();
  const [file, setFile] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [form, setForm] = useState({
    supplierDefault: "",
    countryDefault: "",
    cityAreaDefault: "",
    currencyDefault: "EUR",
    statusDefault: "Open",
    checkInDefault: "",
    checkOutDefault: "",
    childColumnMode: "dynamic_review" as ChildColumnMode,
    preserveChildPositions: true,
    extractionMode: "auto" as ExtractionMode,
  });

  function onPick(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    if (f) setFile(f);
  }

  function onDrop(e: React.DragEvent<HTMLDivElement>) {
    e.preventDefault();
    setDragging(false);
    const f = e.dataTransfer.files?.[0];
    if (f) setFile(f);
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!file) {
      setError("Pick a file first.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const job = await uploadContract(file, form);
      navigate(`/jobs/${job.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="shell">
      <div className="header">
        <h1>Hotel Contract Extraction</h1>
        <a href="https://github.com/" target="_blank" rel="noreferrer" className="muted">
          v1
        </a>
      </div>

      <form onSubmit={onSubmit}>
        <div className="panel">
          <h3 style={{ marginTop: 0 }}>1. Upload contract</h3>
          <div
            className={"drop-zone" + (dragging ? " dragging" : "")}
            onDragOver={(e) => {
              e.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={onDrop}
            onClick={() => document.getElementById("file-input")?.click()}
          >
            <input
              id="file-input"
              type="file"
              accept={ACCEPT}
              onChange={onPick}
              style={{ display: "none" }}
              data-testid="file-input"
            />
            {file ? (
              <>
                <strong>{file.name}</strong>
                <div className="muted">{(file.size / 1024).toFixed(1)} KB</div>
              </>
            ) : (
              <>
                <div>
                  Drag and drop a contract here, or <strong>click to pick</strong>
                </div>
                <div className="muted">XLSX, XLS, PDF, DOCX, PNG, JPG, JPEG, TIFF</div>
              </>
            )}
          </div>
        </div>

        <div className="panel">
          <h3 style={{ marginTop: 0 }}>2. Defaults (optional)</h3>
          <div className="field-row">
            <div className="field">
              <label>Supplier</label>
              <input
                value={form.supplierDefault}
                onChange={(e) => setForm({ ...form, supplierDefault: e.target.value })}
              />
            </div>
            <div className="field">
              <label>Country code</label>
              <input
                value={form.countryDefault}
                onChange={(e) => setForm({ ...form, countryDefault: e.target.value })}
                placeholder="EG"
                maxLength={3}
              />
            </div>
            <div className="field">
              <label>City / Area</label>
              <input
                value={form.cityAreaDefault}
                onChange={(e) => setForm({ ...form, cityAreaDefault: e.target.value })}
              />
            </div>
          </div>
          <div className="field-row">
            <div className="field">
              <label>Currency</label>
              <select
                value={form.currencyDefault}
                onChange={(e) => setForm({ ...form, currencyDefault: e.target.value })}
              >
                {["EUR", "USD", "GBP", "AED", "EGP"].map((c) => (
                  <option key={c} value={c}>{c}</option>
                ))}
              </select>
            </div>
            <div className="field">
              <label>Default status</label>
              <select
                value={form.statusDefault}
                onChange={(e) => setForm({ ...form, statusDefault: e.target.value })}
              >
                <option value="Open">Open</option>
                <option value="On Request">On Request</option>
              </select>
            </div>
            <div className="field">
              <label>Check-in / Check-out</label>
              <div className="row">
                <input
                  placeholder="14:00"
                  value={form.checkInDefault}
                  onChange={(e) => setForm({ ...form, checkInDefault: e.target.value })}
                />
                <input
                  placeholder="12:00"
                  value={form.checkOutDefault}
                  onChange={(e) => setForm({ ...form, checkOutDefault: e.target.value })}
                />
              </div>
            </div>
          </div>
        </div>

        <div className="panel">
          <h3 style={{ marginTop: 0 }}>3. Extraction options</h3>
          <div className="field-row">
            <div className="field">
              <label>Child column mode</label>
              <select
                value={form.childColumnMode}
                onChange={(e) =>
                  setForm({ ...form, childColumnMode: e.target.value as ChildColumnMode })
                }
              >
                <option value="dynamic_review">Dynamic — review</option>
                <option value="dynamic_export">Dynamic — export</option>
                <option value="strict_template">Strict template</option>
              </select>
            </div>
            <div className="field">
              <label>Extraction mode</label>
              <select
                value={form.extractionMode}
                onChange={(e) =>
                  setForm({ ...form, extractionMode: e.target.value as ExtractionMode })
                }
              >
                <option value="auto">Auto</option>
                <option value="text_only">Text/table only</option>
                <option value="vision_allowed">Allow vision fallback</option>
                <option value="vision_required">Force vision</option>
              </select>
            </div>
            <div className="field">
              <label>
                <input
                  type="checkbox"
                  checked={form.preserveChildPositions}
                  onChange={(e) =>
                    setForm({ ...form, preserveChildPositions: e.target.checked })
                  }
                />{" "}
                Preserve child positions (CHD1/CHD2/CHD3)
              </label>
            </div>
          </div>
        </div>

        {error && (
          <div className="panel error-text">
            <strong>Upload failed:</strong> {error}
          </div>
        )}

        <div className="row">
          <div className="spacer" />
          <button type="submit" className="primary" disabled={submitting || !file}>
            {submitting ? "Uploading…" : "Start extraction"}
          </button>
        </div>
      </form>
    </div>
  );
}
