def test_health_reports_unconfigured_and_mock(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["hindsight"] == "unconfigured"
    assert body["llm"] == "mock"


def test_full_loop_report_analyze_resolve_recall_again(client):
    created = client.post("/api/incidents", json={
        "service": "redis-cache", "environment": "Production",
        "symptoms": "Redis timeout", "logs": "ERROR timeout pool exhausted",
    }).json()
    inc_id = created["id"]

    analyzed = client.post(f"/api/incidents/{inc_id}/analyze").json()
    assert analyzed["memories"]["source"] == "unconfigured"

    resolved = client.post(f"/api/incidents/{inc_id}/resolve", json={
        "fix": "Increase Redis pool size", "result": "success", "engineer_feedback": "fixed",
    }).json()
    assert "local" in resolved["retained_in"]
    assert resolved["status"] == "resolved"


def test_duplicate_incident_is_flagged_not_blocked(client):
    first = client.post("/api/incidents", json={
        "service": "kafka", "environment": "Production",
        "symptoms": "Consumer disconnecting", "logs": "ERROR disconnect",
    }).json()
    second = client.post("/api/incidents", json={
        "service": "kafka", "environment": "Production",
        "symptoms": "Consumer disconnecting", "logs": "ERROR disconnect again",
    }).json()
    assert second["possible_duplicate_of"] == first["code"]


def test_compare_endpoint_returns_both_variants(client):
    created = client.post("/api/incidents", json={
        "service": "nginx", "environment": "Production",
        "symptoms": "413 too large", "logs": "body too large",
    }).json()
    r = client.post(f"/api/incidents/{created['id']}/compare")
    assert r.status_code == 200
    body = r.json()
    assert "with_memory" in body and "without_memory" in body
    assert body["without_memory"]["memories"]["source"] == "disabled"


def test_seed_then_reset_clears_incidents(client):
    seeded = client.post("/api/demo/seed").json()
    assert len(seeded["seeded"]) > 0
    assert len(client.get("/api/incidents").json()) == len(seeded["seeded"])

    reset = client.post("/api/demo/reset").json()
    assert reset["bank_id"].startswith("incidentmind-demo-")
    assert client.get("/api/incidents").json() == []


def test_stats_endpoint_after_seed(client):
    client.post("/api/demo/seed")
    stats = client.get("/api/stats").json()
    assert stats["incidents_handled"] > 0


def test_memory_success_metric_requires_a_saved_outcome(app_modules):
    db, memory = app_modules["db"], app_modules["memory"]
    resolved = db.create_incident("redis-cache", "Production", "Redis timeout", "timeout")
    db.save_analysis(resolved["id"], {"memory_influenced": True}, {
        "count": 1,
        "memories": [{"fix": "Increase pool", "result": "success"}],
    }, use_memory=True)
    assert memory.stats()["memory_backed_resolutions"] == 0

    db.save_resolution(resolved["id"], "Increase pool", "success", "worked", "local")
    failed = db.create_incident("redis-cache", "Production", "Replica lag", "lag")
    db.save_analysis(failed["id"], {"memory_influenced": True}, {
        "count": 1,
        "memories": [{"fix": "Restart replica", "result": "success"}],
    }, use_memory=True)
    db.save_resolution(failed["id"], "Restart replica", "failed", "no effect", "local")

    stats = memory.stats()
    assert stats["memory_backed_resolutions"] == 2
    assert stats["memory_backed_successes"] == 1
    assert stats["fix_reuse_rate"] == 0.5


def test_runbook_export_returns_markdown(client):
    client.post("/api/demo/seed")
    r = client.get("/api/runbook/redis-cache.md")
    assert r.status_code == 200
    assert r.text.startswith("# Runbook: redis-cache")


def test_analyze_missing_incident_returns_404(client):
    r = client.post("/api/incidents/9999/analyze")
    assert r.status_code == 404


def test_saved_memory_snapshot_refreshes_outcome_when_reopened(client, app_modules):
    db = app_modules["db"]
    past = db.create_incident("payments", "Production", "Payment timeout", "gateway timeout")
    db.save_resolution(past["id"], "Switch to backup gateway", "failed", "still timing out", "hindsight")
    current = db.create_incident("payments", "Production", "Payment timeout again", "gateway timeout")
    db.save_analysis(current["id"], {"severity": "high"}, {
        "source": "hindsight",
        "count": 1,
        "memories": [{
            "incident": past["code"], "service": "", "fix": "", "result": "unknown",
            "feedback": "", "minutes": "", "date": "", "overlap": 0.1,
            "text": f"Incident {past['code']} occurred in Production after a payment timeout.",
            "conflict": False, "stale": False,
        }],
        "error": None,
    })

    detail = client.get(f"/api/incidents/{current['id']}").json()
    memory_response = client.get(f"/api/incidents/{current['id']}/memories").json()

    assert detail["latest"]["memories"]["memories"][0]["result"] == "failed"
    assert detail["latest"]["memories"]["memories"][0]["fix"] == "Switch to backup gateway"
    assert memory_response["memories"][0]["result"] == "failed"


def test_create_incident_rejects_blank_required_text(client):
    for field in ("service", "symptoms"):
        payload = {
            "service": "payments",
            "environment": "Production",
            "symptoms": "Requests timing out",
            "logs": "",
        }
        payload[field] = "   "
        response = client.post("/api/incidents", json=payload)
        assert response.status_code == 422

    accepted = client.post("/api/incidents", json={
        "service": "  payments  ", "environment": "Production",
        "symptoms": "  Requests timing out  ", "logs": "",
    })
    assert accepted.status_code == 200
    assert accepted.json()["service"] == "payments"
    assert accepted.json()["symptoms"] == "Requests timing out"
