export default function AnalysisCard({ incident, analysis, useMemory, onToggleMemory, onCompare, busy }) {
  if (!analysis) {
    return (
      <section className="card empty">
        <h2>No incident selected</h2>
        <p>Report an incident, or pick one from the history, to see the analysis here.</p>
      </section>
    );
  }
  return (
    <section className="card">
      <header className="row between">
        <div>
          <h2>{incident.code} · {incident.service}</h2>
          <p className="muted">{incident.environment}</p>
        </div>
        <span className={`pill sev-${analysis.severity}`}>{analysis.severity} severity</span>
      </header>

      <section className="current-evidence">
        <h3>Current evidence</h3>
        <dl>
          <div>
            <dt>Symptoms / impact</dt>
            <dd>{incident.symptoms}</dd>
          </div>
          <div>
            <dt>Logs</dt>
            <dd><pre>{incident.logs || "No logs provided."}</pre></dd>
          </div>
        </dl>
      </section>

      <div className="row gap memtoggle">
        <label className="switch">
          <input type="checkbox" checked={useMemory} onChange={(e) => onToggleMemory(e.target.checked)} />
          <span>Use memory</span>
        </label>
        <button className="link" onClick={onCompare} disabled={busy}>
          Compare with/without memory
        </button>
      </div>

      <div className="block">
        <h3>Likely cause</h3>
        <p>{analysis.root_cause} <span className="muted">({analysis.confidence} confidence)</span></p>
      </div>
      <div className="block recommend">
        <h3>Recommended fix</h3>
        <p>{analysis.recommendation}</p>
        {analysis.memories_used?.length > 0 && (
          <p className="muted small">Based on {analysis.memories_used.join(", ")}</p>
        )}
      </div>
      {analysis.avoid?.length > 0 && (
        <div className="block avoid">
          <h3>Skip these, they failed before</h3>
          <ul>{analysis.avoid.map((a) => <li key={a}>{a}</li>)}</ul>
        </div>
      )}
      <div className="block">
        <h3>Reasoning</h3>
        <p>{analysis.reasoning}</p>
      </div>
      {analysis.detected_symptoms?.length > 0 && (
        <ul className="chips">{analysis.detected_symptoms.map((s) => <li key={s}>{s}</li>)}</ul>
      )}
      <p className="muted small">Analysis engine: {analysis.engine}</p>
    </section>
  );
}
