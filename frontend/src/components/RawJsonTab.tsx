import { useState } from "react";

import type { NormalizedExtractionResult } from "../types";

export default function RawJsonTab(props: {
  result: NormalizedExtractionResult;
  onPatch: (next: NormalizedExtractionResult) => void;
}) {
  const { result, onPatch } = props;
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<string>(JSON.stringify(result, null, 2));
  const [err, setErr] = useState<string | null>(null);

  function start() {
    setDraft(JSON.stringify(result, null, 2));
    setEditing(true);
    setErr(null);
  }

  function save() {
    try {
      const parsed = JSON.parse(draft);
      if (!parsed || typeof parsed !== "object" || !parsed.hotelRows) {
        throw new Error("JSON must contain hotelRows");
      }
      onPatch(parsed as NormalizedExtractionResult);
      setEditing(false);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <div className="panel">
      <div className="row">
        <h3 style={{ margin: 0 }}>Normalized JSON</h3>
        <div className="spacer" />
        {!editing ? (
          <button onClick={start}>Enable edit</button>
        ) : (
          <>
            <button onClick={() => setEditing(false)}>Cancel</button>
            <button className="primary" onClick={save}>
              Validate & save
            </button>
          </>
        )}
      </div>
      {err && <div className="error-text">{err}</div>}
      {editing ? (
        <textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          style={{
            width: "100%",
            minHeight: "60vh",
            fontFamily: "monospace",
            fontSize: 12,
          }}
        />
      ) : (
        <pre className="json">{JSON.stringify(result, null, 2)}</pre>
      )}
    </div>
  );
}
