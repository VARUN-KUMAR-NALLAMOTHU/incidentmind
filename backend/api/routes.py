import uuid

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse

import config as cfg
import database as db
import seed_data
from schemas import IncidentCreate, ResolveRequest
from services import hindsight_service as memory
from services import llm_service

router = APIRouter(prefix="/api")


def _get_or_404(incident_id: int) -> dict:
    incident = db.get_incident(incident_id)
    if not incident:
        raise HTTPException(404, "Incident not found")
    return incident


def _minutes_since(incident: dict, override) -> int | None:
    if override is not None:
        return override
    from datetime import datetime

    try:
        created = datetime.fromisoformat(incident["created_at"])
        delta = datetime.now(created.tzinfo) - created
        return max(1, int(delta.total_seconds() // 60))
    except Exception:  # noqa: BLE001
        return None


@router.get("/health")
def health():
    return {
        "ok": True,
        "hindsight": "configured" if memory.hindsight_enabled() else (
            "local-fallback" if cfg.USE_LOCAL_FALLBACK else "unconfigured"
        ),
        "bank_id": db.current_bank(),
        "local_fallback_enabled": cfg.USE_LOCAL_FALLBACK,
        "llm": "groq" if cfg.GROQ_API_KEY else "mock",
        "llm_model": cfg.GROQ_MODEL if cfg.GROQ_API_KEY else "mock",
    }


@router.post("/incidents")
def create_incident(body: IncidentCreate):
    dup = db.find_open_duplicate(body.service, body.symptoms)
    incident = db.create_incident(body.service, body.environment, body.symptoms, body.logs)
    return {**incident, "possible_duplicate_of": dup["code"] if dup else None}


@router.get("/incidents")
def list_incidents():
    return db.list_incidents()


@router.get("/incidents/{incident_id}")
def get_incident(incident_id: int):
    incident = _get_or_404(incident_id)
    latest = db.latest_analysis(incident_id)
    if latest:
        latest["memories"] = memory.enrich_recalled_memories(latest["memories"])
    return {
        "incident": incident,
        "latest": latest,
        "resolutions": db.list_resolutions(incident_id),
    }


@router.post("/incidents/{incident_id}/analyze")
async def analyze(incident_id: int, use_memory: bool = Query(default=True)):
    incident = _get_or_404(incident_id)
    recalled = await memory.recall(incident, use_memory=use_memory)    # RECALL
    try:
        analysis = llm_service.analyze(incident, recalled)              # REASON
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"LLM call failed after retries and model fallback: {e}") from e
    db.save_analysis(incident_id, analysis, recalled, use_memory=use_memory)
    db.update_incident(incident_id, severity=analysis["severity"], status="analyzed")
    return {"incident": db.get_incident(incident_id), "analysis": analysis, "memories": recalled}


@router.post("/incidents/{incident_id}/compare")
async def compare(incident_id: int):
    """Run the same incident with and without memory, side by side, for the before/after demo view."""
    incident = _get_or_404(incident_id)
    with_recalled = await memory.recall(incident, use_memory=True)
    without_recalled = await memory.recall(incident, use_memory=False)
    try:
        with_analysis = llm_service.analyze(incident, with_recalled)
        without_analysis = llm_service.analyze(incident, without_recalled)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"LLM call failed: {e}") from e
    db.save_analysis(incident_id, with_analysis, with_recalled, use_memory=True)
    return {
        "incident": incident,
        "with_memory": {"analysis": with_analysis, "memories": with_recalled},
        "without_memory": {"analysis": without_analysis, "memories": without_recalled},
    }


@router.get("/incidents/{incident_id}/memories")
def memories(incident_id: int):
    _get_or_404(incident_id)
    latest = db.latest_analysis(incident_id)
    if not latest:
        raise HTTPException(409, "Analyze the incident first")
    m = memory.enrich_recalled_memories(latest["memories"])
    return {"memories_found": m["count"], **m}


@router.post("/incidents/{incident_id}/resolve")
async def resolve(incident_id: int, body: ResolveRequest):
    incident = _get_or_404(incident_id)
    minutes = _minutes_since(incident, body.minutes_to_resolve)
    stored_in = await memory.retain(incident, body.fix, body.result, body.engineer_feedback, minutes)  # RETAIN
    resolution = db.save_resolution(
        incident_id, body.fix, body.result, body.engineer_feedback, stored_in, minutes
    )
    if body.result == "success":
        db.update_incident(incident_id, status="resolved")
    return {"resolution": resolution, "retained_in": stored_in, "status": db.get_incident(incident_id)["status"]}


@router.post("/reflect")
async def reflect(service: str | None = Query(default=None)):
    return await memory.reflect(service)


@router.get("/runbook/{service}.md", response_class=PlainTextResponse)
async def runbook(service: str):
    result = await memory.reflect(service)
    header = f"# Runbook: {service}\n\n_Generated from Hindsight memory (source: {result['source']})._\n\n"
    body = result["text"]
    if result["insights"]:
        body += f"\n\n### Hindsight-generated patterns\n\n{result['insights']}"
    if result["error"]:
        body += f"\n\n_Hindsight reflection unavailable: {result['error']}_"
    return header + body


@router.get("/stats")
def stats():
    return memory.stats()


@router.post("/demo/seed")
async def seed():
    """Create resolved history (incl. failed and conflicting fixes) and retain it, so the first live
    analysis in the demo can recall it. Kafka is deliberately absent - see seed_data.py."""
    created = []
    for item in seed_data.SEED:
        created_at = db.now(days_ago=item["days_ago"])
        inc = db.create_incident(item["service"], item["environment"], item["symptoms"], item["logs"], created_at)
        for fix, result, feedback, days_ago, resolve_minutes_ago in item["attempts"]:
            await memory.retain(inc, fix, result, feedback, minutes=resolve_minutes_ago)
            db.save_resolution(inc["id"], fix, result, feedback, "seed", resolve_minutes_ago,
                                created_at=db.now(days_ago=days_ago))
        db.update_incident(inc["id"], status="resolved", severity="high")
        created.append(inc["code"])
    return {"seeded": created}


@router.post("/demo/reset")
def reset_demo():
    """Wipe local data and switch to a brand-new Hindsight bank, so the demo can restart from zero
    without deleting the database file by hand."""
    new_bank = f"incidentmind-demo-{uuid.uuid4().hex[:8]}"
    db.reset_all(new_bank)
    return {"bank_id": new_bank}
