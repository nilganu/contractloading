import { useState } from "react";

import type { ExtractionNote, NormalizedExtractionResult } from "../types";

const CATEGORIES = [
  "Taxes/service",
  "Child policy",
  "Cancellation",
  "Gala dinner",
  "Special offer",
  "Booking window",
  "Minimum stay",
  "Room allocation",
  "Rate anomaly",
  "Meal plan nuance",
  "Room supplement",
  "Source ambiguity",
  "Other",
];

export default function ExtractionNotesTab(props: {
  result: NormalizedExtractionResult;
  onPatch: (next: NormalizedExtractionResult) => void;
}) {
  const { result, onPatch } = props;
  const [filter, setFilter] = useState("");
  const [cat, setCat] = useState("");
  const [editing, setEditing] = useState<Record<string, ExtractionNote>>({});

  const notes = result.extractionNotes
    .map((n) => editing[n.id] ?? n)
    .filter(
      (n) =>
        (!filter || (n.Note ?? "").toLowerCase().includes(filter.toLowerCase())) &&
        (!cat || n.Category === cat)
    );

  function commit(id: string) {
    const edited = editing[id];
    if (!edited) return;
    const next = {
      ...result,
      extractionNotes: result.extractionNotes.map((n) =>
        n.id === id ? edited : n
      ),
    };
    onPatch(next);
    setEditing(({ [id]: _, ...rest }) => rest);
  }

  function addNote() {
    const newNote: ExtractionNote = {
      id: `note_${Math.random().toString(36).slice(2, 10)}`,
      "Source File": result.workbookSummary.sourceFile,
      Page: "—",
      Category: "Other",
      Note: "",
    };
    onPatch({ ...result, extractionNotes: [newNote, ...result.extractionNotes] });
  }

  function remove(id: string) {
    onPatch({
      ...result,
      extractionNotes: result.extractionNotes.filter((n) => n.id !== id),
    });
  }

  return (
    <>
      <div className="panel">
        <div className="row">
          <input
            placeholder="Filter notes…"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          />
          <select value={cat} onChange={(e) => setCat(e.target.value)}>
            <option value="">All categories</option>
            {CATEGORIES.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
          <div className="spacer" />
          <button onClick={addNote}>+ Add note</button>
        </div>
      </div>

      <div className="scroll-grid">
        <table className="data">
          <thead>
            <tr>
              <th>Source File</th>
              <th>Page</th>
              <th>Category</th>
              <th style={{ minWidth: 360 }}>Note</th>
              <th>Hotel</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {notes.map((n) => (
              <tr key={n.id}>
                <td>
                  <input
                    className="cell-input"
                    value={n["Source File"] ?? ""}
                    onChange={(e) =>
                      setEditing((c) => ({
                        ...c,
                        [n.id]: { ...n, "Source File": e.target.value },
                      }))
                    }
                    onBlur={() => commit(n.id)}
                  />
                </td>
                <td>
                  <input
                    className="cell-input"
                    value={n.Page ?? ""}
                    onChange={(e) =>
                      setEditing((c) => ({
                        ...c,
                        [n.id]: { ...n, Page: e.target.value },
                      }))
                    }
                    onBlur={() => commit(n.id)}
                  />
                </td>
                <td>
                  <select
                    className="cell-input"
                    value={n.Category}
                    onChange={(e) =>
                      setEditing((c) => ({
                        ...c,
                        [n.id]: { ...n, Category: e.target.value },
                      }))
                    }
                    onBlur={() => commit(n.id)}
                  >
                    {CATEGORIES.map((c) => (
                      <option key={c} value={c}>
                        {c}
                      </option>
                    ))}
                  </select>
                </td>
                <td>
                  <input
                    className="cell-input"
                    value={n.Note ?? ""}
                    onChange={(e) =>
                      setEditing((c) => ({
                        ...c,
                        [n.id]: { ...n, Note: e.target.value },
                      }))
                    }
                    onBlur={() => commit(n.id)}
                  />
                </td>
                <td>{n.hotelName ?? "—"}</td>
                <td>
                  <button onClick={() => remove(n.id)} title="Delete note">
                    ✕
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
