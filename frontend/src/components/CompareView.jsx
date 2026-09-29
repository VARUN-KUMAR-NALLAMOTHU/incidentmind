function Side({ label, data }) {
  const { analysis, memories } = data;
  return (
    <div className="compare-side">
      <h3>{label}</h3>
      <p className="muted small">{memories.count} memories used</p>
      <p className="block recommend"><strong>Recommends:</strong> {analysis.recommendation}</p>
      {analysis.avoid?.length > 0 && (
        <p className="block avoid"><strong>Avoids:</strong> {analysis.avoid.join("; ")}</p>
      )}
      <p className="dim small">Confidence: {analysis.confidence}</p>
    </div>
  );
}

export default function CompareView({ result, onClose }) {
  if (!result) return null;
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <header className="row between">
          <h2>With memory vs. without — {result.incident.code}</h2>
          <button className="link" onClick={onClose}>Close</button>
        </header>
        <div className="compare-grid">
          <Side label="Without memory" data={result.without_memory} />
          <Side label="With Hindsight memory" data={result.with_memory} />
        </div>
      </div>
    </div>
  );
}
