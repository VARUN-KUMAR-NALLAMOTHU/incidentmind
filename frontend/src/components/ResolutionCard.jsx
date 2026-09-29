import { useEffect, useState } from "react";
import { api } from "../api";

export default function ResolutionCard({ incident, analysis, resolutions, onResolve }) {
  const [fix, setFix] = useState("");
  const [result, setResult] = useState("success");
  const [feedback, setFeedback] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setFix(analysis?.recommendation || "");
    setResult("success");
    setFeedback("");
  }, [incident?.id, analysis?.recommendation]);

  if (!incident || !analysis) return null;

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    try {
      await onResolve({ fix, result, engineer_feedback: feedback });
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="card">
      <header className="row between">
        <h2>What happened when you tried it?</h2>
        <a className="link" href={api.runbookUrl(incident.service)} target="_blank" rel="noreferrer">
          Export {incident.service} runbook
        </a>
      </header>
      <p className="muted">Record every attempt, including the ones that failed. Both go into memory.</p>

      {resolutions.length > 0 && (
        <ul className="attempts">
          {resolutions.map((r) => (
            <li key={r.id} className={r.result}>
              <span className="badge">{r.result === "success" ? "Worked" : "Failed"}</span> {r.fix}
              <span className="dim small"> · saved to {r.retained_in}</span>
            </li>
          ))}
        </ul>
      )}

      <form onSubmit={submit} className="form">
        <label>
          Fix you applied
          <textarea rows={2} value={fix} onChange={(e) => setFix(e.target.value)} required />
        </label>
        <fieldset>
          <legend>Outcome</legend>
          <label className="radio"><input type="radio" checked={result === "success"} onChange={() => setResult("success")} /> It worked</label>
          <label className="radio"><input type="radio" checked={result === "failed"} onChange={() => setResult("failed")} /> It failed</label>
        </fieldset>
        <label>
          Notes for next time
          <input value={feedback} onChange={(e) => setFeedback(e.target.value)} placeholder="Worked immediately" />
        </label>
        <button className="primary" disabled={busy}>{busy ? "Saving…" : "Save outcome to memory"}</button>
      </form>
    </section>
  );
}
