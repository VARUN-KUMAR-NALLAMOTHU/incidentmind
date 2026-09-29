export default function IncidentHistory({ incidents, selectedId, onSelect }) {
  return (
    <section className="card history">
      <h2>Incident history</h2>
      {incidents.length === 0 && <p className="muted">Nothing yet. Load the demo history or report an incident.</p>}
      <ul>
        {incidents.map((i) => (
          <li key={i.id}>
            <button className={i.id === selectedId ? "sel" : ""} onClick={() => onSelect(i.id)}>
              <strong>{i.code}</strong> {i.service}
              <span className={`status ${i.status}`}>{i.status}</span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
