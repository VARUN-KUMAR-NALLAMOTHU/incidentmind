"""Tests for the memory layer with Hindsight disabled: default (no fallback) and opt-in local fallback."""
import asyncio


def _run(coro):
    return asyncio.run(coro)


def _incident(db):
    return db.create_incident("redis-cache", "Production", "Redis timeout", "ERROR timeout")


def test_recall_is_empty_and_unconfigured_by_default(app_modules):
    db, memory = app_modules["db"], app_modules["memory"]
    inc = _incident(db)
    result = _run(memory.recall(inc))
    assert result["source"] == "unconfigured"
    assert result["memories"] == []


def test_retain_always_writes_local_audit_copy(app_modules):
    db, memory = app_modules["db"], app_modules["memory"]
    inc = _incident(db)
    where = _run(memory.retain(inc, "Restart Redis", "failed", "no effect"))
    assert "local" in where
    assert len(db.fallback_all()) == 1


def test_local_fallback_recall_when_opted_in(app_modules, monkeypatch):
    db, memory = app_modules["db"], app_modules["memory"]
    monkeypatch.setattr(memory.cfg, "USE_LOCAL_FALLBACK", True)

    inc = _incident(db)
    _run(memory.retain(inc, "Increase Redis maxclients", "success", "fixed it"))
    other = db.create_incident("redis-cache", "Production", "Redis timeout again", "ERROR timeout retry")
    result = _run(memory.recall(other))
    assert result["source"] == "local"
    assert result["count"] == 1
    assert result["memories"][0]["result"] == "success"


def test_disabled_memory_short_circuits(app_modules):
    db, memory = app_modules["db"], app_modules["memory"]
    inc = _incident(db)
    result = _run(memory.recall(inc, use_memory=False))
    assert result == {"source": "disabled", "count": 0, "memories": [], "error": None}


def test_conflict_flag_set_when_same_fix_has_both_outcomes(app_modules, monkeypatch):
    db, memory = app_modules["db"], app_modules["memory"]
    monkeypatch.setattr(memory.cfg, "USE_LOCAL_FALLBACK", True)

    a = db.create_incident("redis-cache", "Production", "Replica lag", "lag climbing")
    _run(memory.retain(a, "Restart the replica pod", "success", "worked"))
    b = db.create_incident("redis-cache", "Production", "Replica lag again", "lag climbing again")
    _run(memory.retain(b, "Restart the replica pod", "failed", "did not help this time"))

    check = db.create_incident("redis-cache", "Production", "Replica lag once more", "lag rising")
    result = _run(memory.recall(check))
    assert result["count"] == 2
    assert all(m["conflict"] for m in result["memories"])


def test_stale_flag_on_old_memory(app_modules, monkeypatch):
    db, memory = app_modules["db"], app_modules["memory"]
    monkeypatch.setattr(memory.cfg, "USE_LOCAL_FALLBACK", True)
    monkeypatch.setattr(memory.cfg, "STALE_DAYS", 5)

    old = db.create_incident("nginx", "Production", "413 too large", "body too large")
    content = memory.build_memory_text(old, "Raise client_max_body_size", "success", "fixed", None)
    content = content.replace(content.split("Date: ")[1], "2020-01-01")
    db.fallback_add(content)

    check = db.create_incident("nginx", "Production", "413 too large again", "body too large again")
    result = _run(memory.recall(check))
    assert result["memories"][0]["stale"] is True


def test_recall_never_returns_the_incident_itself(app_modules, monkeypatch):
    db, memory = app_modules["db"], app_modules["memory"]
    monkeypatch.setattr(memory.cfg, "USE_LOCAL_FALLBACK", True)
    inc = _incident(db)
    _run(memory.retain(inc, "Restart Redis", "failed", "no effect"))
    result = _run(memory.recall(inc))
    assert all(m["incident"] != inc["code"] for m in result["memories"])


def test_recall_enriches_hindsight_summary_with_saved_outcome(app_modules, monkeypatch):
    db, memory = app_modules["db"], app_modules["memory"]
    inc = _incident(db)
    db.save_resolution(inc["id"], "Increase the Redis pool", "success", "fixed", "hindsight")
    monkeypatch.setattr(memory.cfg, "HINDSIGHT_BASE_URL", "https://hindsight.example")
    async def fake_recall(*_args):
        return [f"Incident {inc['code']} occurred in Production after a Redis timeout."]

    monkeypatch.setattr(memory, "_hs_recall", fake_recall)

    result = _run(memory.recall(db.create_incident(
        "redis-cache", "Production", "Redis timeout again", "ERROR timeout retry",
    )))

    assert result["count"] == 1
    recalled = result["memories"][0]
    assert recalled["service"] == "redis-cache"
    assert recalled["fix"] == "Increase the Redis pool"
    assert recalled["result"] == "success"


def test_reflection_counts_incident_outcomes_from_database(app_modules):
    db, memory = app_modules["db"], app_modules["memory"]
    resolved = _incident(db)
    db.save_resolution(resolved["id"], "Increase pool", "success", "worked", "local")
    db.update_incident(resolved["id"], status="resolved")

    failed = db.create_incident("redis-cache", "Production", "Replica lag", "lag rising")
    db.save_resolution(failed["id"], "Restart replica", "failed", "no effect", "local")

    db.create_incident("nginx", "Staging", "413 too large", "body too large")
    summary = _run(memory.reflect())["summary"]

    assert summary["total_incidents"] == 3
    assert summary["resolved"] == 1
    assert summary["failed"] == 1
    assert summary["no_outcome"] == 1
    assert summary["worked_attempts"] == 1
    assert summary["failed_attempts"] == 1


def test_reflection_keeps_local_summary_when_hindsight_fails(app_modules, monkeypatch):
    memory = app_modules["memory"]
    _incident(app_modules["db"])
    monkeypatch.setattr(memory.cfg, "HINDSIGHT_BASE_URL", "https://hindsight.example")

    def fail_reflect(*_args):
        raise RuntimeError("reflection unavailable")

    monkeypatch.setattr(memory, "_hs_reflect", fail_reflect)
    result = _run(memory.reflect())

    assert result["source"] == "local"
    assert result["summary"]["total_incidents"] == 1
    assert result["error"] == "reflection unavailable"
