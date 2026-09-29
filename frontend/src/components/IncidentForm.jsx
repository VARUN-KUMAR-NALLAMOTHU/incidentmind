import { useState } from "react";

const empty = { service: "", environment: "Production", symptoms: "", logs: "" };

export default function IncidentForm({ onSubmit, busy }) {
  const [form, setForm] = useState(empty);
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });

  const submit = async (e) => {
    e.preventDefault();
    const ok = await onSubmit(form);
    if (ok) setForm(empty); // keep the user's input on failure instead of silently discarding it
  };

  return (
    <form className="card form" onSubmit={submit}>
      <h2>Report a new incident</h2>
      <label>
        Service
        <input value={form.service} onChange={set("service")} placeholder="payment-api" required pattern=".*\S.*" title="Enter a service name, not only spaces." />
      </label>
      <label>
        Environment
        <select value={form.environment} onChange={set("environment")}>
          <option>Production</option>
          <option>Staging</option>
          <option>Development</option>
        </select>
      </label>
      <label>
        Symptoms / impact
        <input value={form.symptoms} onChange={set("symptoms")} placeholder="Consumer keeps disconnecting" required pattern=".*\S.*" title="Enter symptoms, not only spaces." />
      </label>
      <label>
        Logs
        <textarea className="mono" rows={5} value={form.logs} onChange={set("logs")} placeholder="Paste the relevant log lines" />
      </label>
      <button className="primary" disabled={busy}>
        {busy ? "Analyzing…" : "Analyze incident"}
      </button>
    </form>
  );
}
