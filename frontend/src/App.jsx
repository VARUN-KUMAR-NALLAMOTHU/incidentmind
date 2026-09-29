import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import IncidentForm from "./components/IncidentForm";
import AnalysisCard from "./components/AnalysisCard";
import MemoryPanel from "./components/MemoryPanel";
import ResolutionCard from "./components/ResolutionCard";
import IncidentHistory from "./components/IncidentHistory";
import CompareView from "./components/CompareView";
import StatsPanel from "./components/StatsPanel";

export default function App() {
  const [health, setHealth] = useState(null);
  const [incidents, setIncidents] = useState([]);
  const [current, setCurrent] = useState(null); // { incident, analysis, memories, resolutions }
  const [useMemory, setUseMemory] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [reflection, setReflection] = useState(null);
  const [compareResult, setCompareResult] = useState(null);
  const [stats, setStats] = useState(null);

  const refresh = useCallback(async () => setIncidents(await api.listIncidents()), []);
  const refreshStats = useCallback(async () => setStats(await api.stats()), []);

  useEffect(() => {
    api.health().then(setHealth).catch(() => setError("Can't reach the backend on port 8000."));
    refresh().catch(() => {});
    refreshStats().catch(() => {});
  }, [refresh, refreshStats]);

  const guard = async (fn) => {
    setError("");
    try {
      await fn();
      return true;
    } catch (e) {
      setError(e.message);
      return false;
    }
  };

  const select = (id) =>
    guard(async () => {
      const d = await api.getIncident(id);
      setCurrent({
        incident: d.incident,
        analysis: d.latest?.analysis,
        memories: d.latest?.memories,
        resolutions: d.resolutions,
      });
    });

  const report = (form) =>
    guard(async () => {
      setBusy(true);
      try {
        const created = await api.createIncident(form);
        if (created.possible_duplicate_of) {
          setError(`Heads up: this looks similar to open incident ${created.possible_duplicate_of}.`);
        }
        const r = await api.analyze(created.id, useMemory);
        setCurrent({ incident: r.incident, analysis: r.analysis, memories: r.memories, resolutions: [] });
        await refresh();
      } finally {
        setBusy(false);
      }
    });

  const toggleMemory = (val) =>
    guard(async () => {
      setUseMemory(val);
      if (!current) return;
      setBusy(true);
      try {
        const r = await api.analyze(current.incident.id, val);
        setCurrent((c) => ({ ...c, analysis: r.analysis, memories: r.memories }));
      } finally {
        setBusy(false);
      }
    });

  const compare = () =>
    guard(async () => {
      setBusy(true);
      try {
        setCompareResult(await api.compare(current.incident.id));
      } finally {
        setBusy(false);
      }
    });

  const resolve = (data) =>
    guard(async () => {
      await api.resolve(current.incident.id, data);
      await select(current.incident.id);
      await refresh();
      await refreshStats();
    });

  const seed = () => guard(async () => { await api.seed(); await refresh(); await refreshStats(); });
  const reflect = () => guard(async () => setReflection(await api.reflect()));
  const resetDemo = () =>
    guard(async () => {
      if (!window.confirm("Reset all incidents and start a new Hindsight bank?")) return;
      await api.reset();
      setCurrent(null);
      setCompareResult(null);
      setReflection(null);
      await refresh();
      await refreshStats();
      setHealth(await api.health());
    });

  const memoryOk = health && (health.hindsight === "configured" || health.local_fallback_enabled);

  return (
    <div className="app">
      <header className="top">
        <div>
          <h1>IncidentMind</h1>
          <p className="muted">Every incident your team resolves makes the next one faster.</p>
        </div>
        <div className="row gap">
          {health && (
            <span className={`pill ${health.hindsight === "configured" ? "ok" : memoryOk ? "warn" : "bad"}`}>
              Memory: {health.hindsight === "configured" ? "Hindsight" : health.local_fallback_enabled ? "local fallback" : "not configured"}
              {" · "}LLM: {health.llm}
            </span>
          )}
          <button onClick={seed}>Load demo history</button>
          <button onClick={reflect}>Reflect on all incidents</button>
          <button onClick={resetDemo}>Reset demo</button>
        </div>
      </header>

      {!memoryOk && health && (
        <div className="banner">
          Running without Hindsight — set <code>HINDSIGHT_BASE_URL</code> in the backend .env to see real
          memory recall, or set <code>USE_LOCAL_FALLBACK=true</code> for a local-only demo.
        </div>
      )}
      {error && <div className="error" role="alert">{error}</div>}
      {reflection && (
        <div className="reflection">
          <header className="row between">
            <strong>Incident learning ({reflection.source})</strong>
            <button className="link" onClick={() => setReflection(null)}>Dismiss</button>
          </header>
          <div className="stat-grid reflection-stats">
            <div><strong>{reflection.summary.total_incidents}</strong><span>incidents</span></div>
            <div><strong>{reflection.summary.resolved}</strong><span>resolved</span></div>
            <div><strong>{reflection.summary.failed}</strong><span>failed</span></div>
            <div><strong>{reflection.summary.no_outcome}</strong><span>no outcome</span></div>
          </div>
          {reflection.summary.by_service.length > 0 && (
            <ul className="reflection-services">
              {reflection.summary.by_service.map((item) => (
                <li key={item.service}>
                  <strong>{item.service}</strong>
                  <span>{item.total_incidents} incidents</span>
                  <span>{item.resolved} worked · {item.failed} failed · {item.no_outcome} unknown</span>
                </li>
              ))}
            </ul>
          )}
          <details className="reflection-details">
            <summary>{reflection.insights ? "Hindsight-generated patterns" : "Outcome details"}</summary>
            <pre>{reflection.insights || reflection.text}</pre>
          </details>
          {reflection.error && (
            <p className="reflection-warning">
              Hindsight detail unavailable; counts above come from saved incident outcomes.
            </p>
          )}
        </div>
      )}

      <main className="grid">
        <div className="col">
          <IncidentForm onSubmit={report} busy={busy} />
          <IncidentHistory incidents={incidents} selectedId={current?.incident?.id} onSelect={select} />
          <StatsPanel stats={stats} />
        </div>
        <div className="col">
          <AnalysisCard
            incident={current?.incident}
            analysis={current?.analysis}
            useMemory={useMemory}
            onToggleMemory={toggleMemory}
            onCompare={compare}
            busy={busy}
          />
          <ResolutionCard
            incident={current?.incident}
            analysis={current?.analysis}
            resolutions={current?.resolutions || []}
            onResolve={resolve}
          />
        </div>
        <MemoryPanel memories={current?.memories} analysis={current?.analysis} />
      </main>

      <CompareView result={compareResult} onClose={() => setCompareResult(null)} />
    </div>
  );
}
