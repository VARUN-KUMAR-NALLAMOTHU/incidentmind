async function request(path, options = {}) {
  const res = await fetch(`/api${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `Request failed (${res.status})`);
  }
  return res.json();
}

const post = (path, body) => request(path, { method: "POST", body: body ? JSON.stringify(body) : undefined });

export const api = {
  health: () => request("/health"),
  listIncidents: () => request("/incidents"),
  getIncident: (id) => request(`/incidents/${id}`),
  createIncident: (data) => post("/incidents", data),
  analyze: (id, useMemory = true) => post(`/incidents/${id}/analyze?use_memory=${useMemory}`),
  compare: (id) => post(`/incidents/${id}/compare`),
  resolve: (id, data) => post(`/incidents/${id}/resolve`, data),
  reflect: (service) => post(`/reflect${service ? `?service=${encodeURIComponent(service)}` : ""}`),
  seed: () => post("/demo/seed"),
  reset: () => post("/demo/reset"),
  stats: () => request("/stats"),
  runbookUrl: (service) => `/api/runbook/${encodeURIComponent(service)}.md`,
};
