export default function StatsPanel({ stats }) {
  if (!stats) return null;
  const trendMax = Math.max(1, ...stats.minutes_trend);
  return (
    <section className="card stats">
      <h2>Learning curve</h2>
      <div className="stat-grid">
        <div><strong>{stats.incidents_handled}</strong><span>incidents handled</span></div>
        <div><strong>{stats.avg_memories_recalled}</strong><span>memories recalled / analysis</span></div>
        <div>
          <strong>{Math.round(stats.fix_reuse_rate * 100)}%</strong>
          <span>reused fixes that worked ({stats.memory_backed_successes}/{stats.memory_backed_resolutions})</span>
        </div>
        <div><strong>{stats.avg_minutes_to_resolve ?? "—"}</strong><span>avg. minutes to resolve</span></div>
      </div>
      {stats.minutes_trend.length > 1 && (
        <div className="trend" aria-label="Recent time-to-resolve trend">
          {stats.minutes_trend.map((m, i) => (
            <span key={i} className="bar" style={{ height: `${(m / trendMax) * 100}%` }} title={`${m} min`} />
          ))}
        </div>
      )}
    </section>
  );
}
