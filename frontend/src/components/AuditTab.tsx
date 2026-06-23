import type { AuditResponse } from "../types";

export default function AuditTab(props: { audit?: AuditResponse }) {
  const { audit } = props;
  if (!audit) {
    return <div className="panel">Loading audit…</div>;
  }
  return (
    <>
      <div className="panel">
        <h3 style={{ marginTop: 0 }}>Job</h3>
        <table className="data">
          <tbody>
            <tr><th>File</th><td>{audit.fileName}</td></tr>
            <tr><th>File type</th><td>{audit.fileType ?? "—"}</td></tr>
            <tr><th>Parser version</th><td>{audit.parserVersion}</td></tr>
            <tr><th>Prompt version</th><td>{audit.promptVersion}</td></tr>
            <tr><th>OpenAI model</th><td>{audit.openaiModel ?? "—"}</td></tr>
            <tr><th>Extraction mode</th><td>{audit.extractionMode}</td></tr>
            <tr><th>Created at</th><td>{audit.createdAt}</td></tr>
            <tr><th>Updated at</th><td>{audit.updatedAt}</td></tr>
            <tr><th>Export path</th><td>{audit.exportPath ?? "—"}</td></tr>
          </tbody>
        </table>
      </div>

      <div className="panel">
        <h3 style={{ marginTop: 0 }}>Events</h3>
        <table className="data">
          <thead>
            <tr><th>At</th><th>Event</th><th>Detail</th></tr>
          </thead>
          <tbody>
            {audit.audit.map((e, i) => (
              <tr key={i}>
                <td>{e.at}</td>
                <td>{e.event}</td>
                <td><pre style={{ margin: 0, whiteSpace: "pre-wrap" }}>{JSON.stringify(e.detail)}</pre></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
