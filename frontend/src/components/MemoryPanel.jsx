const sourceLabel = {
  hindsight: "Recalled from Hindsight",
  local: "Recalled from local fallback store",
  disabled: "Memory turned off for this analysis",
  unconfigured: "Hindsight is not configured — set HINDSIGHT_BASE_URL",
  error: "Hindsight recall failed",
  none: "No memory source",
};

const outcomeLabel = {
  success: "Worked",
  failed: "Failed",
  unknown: "Outcome not recorded",
};

export default function MemoryPanel({ memories, analysis }) {
  if (!memories) {
    return (
      <aside className="memory">
        <h2>Hindsight memory</h2>
        <p className="dim">Past experiences that match an incident appear here once it is analyzed.</p>
      </aside>
    );
  }
  const used = new Set(analysis?.memories_used || []);

  return (
    <aside className="memory">
      <h2>Hindsight memory</h2>
      <p className={`dim ${memories.source === "error" ? "source-error" : ""}`}>{sourceLabel[memories.source]}</p>
      {memories.error && <p className="dim small source-error">{memories.error}</p>}

      <p className="verdict">
        {memories.count === 0
          ? memories.source === "disabled"
            ? "Memory is off. This analysis used only the current logs."
            : "No relevant experience yet. This one is analyzed from the logs alone."
          : `${memories.count} relevant ${memories.count === 1 ? "experience" : "experiences"} found${
              used.size ? `, ${used.size} cited in the recommendation` : ""
            }.`}
      </p>

      <ol className="timeline">
        {memories.memories.map((m, i) => (
          <li key={i} className={`mem ${m.result} ${used.has(m.incident) ? "cited" : ""}`}>
            <div className="row between">
              <strong>{m.incident || "Earlier incident"}</strong>
              <span className="badge">{outcomeLabel[m.result] || m.result}</span>
            </div>
            <p className="fix">{m.fix}</p>
            {m.feedback && m.feedback !== "none" && <p className="dim">“{m.feedback}”</p>}
            <div className="row gap flags">
              {used.has(m.incident) && <span className="flag cited">Cited in recommendation</span>}
              {m.conflict && <span className="flag conflict">Mixed evidence</span>}
              {m.stale && <span className="flag stale">Old — may be outdated</span>}
              {m.date && <span className="dim small">{m.date}</span>}
            </div>
          </li>
        ))}
      </ol>
    </aside>
  );
}
