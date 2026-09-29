"""Hindsight memory layer: recall / retain / reflect.

Real Hindsight (https://hindsight.vectorize.io/) is the default memory backend. The `_hs_*` helpers below
are the only place the SDK is called; they follow the `hindsight-client` Python API:
  Hindsight(base_url=..., api_key=...)
  client.create_bank(bank_id, name, mission)
  client.retain(bank_id, content, context=None, metadata=None, retain_async=False)
  client.recall(bank_id, query, types=None, budget="mid")
  client.reflect(bank_id, query, budget="mid")
Re-check these against the current docs if the SDK version changes.

Every retained record is ALSO written to a local SQLite table (`memory_fallback`). That copy is not a
"fake memory store" — it never answers `recall()` unless USE_LOCAL_FALLBACK=true and Hindsight is down —
it is an audit index used to detect conflicting or stale memories and to power the /stats endpoint, since
Hindsight itself is the source of truth for recall and reflect.
"""
import logging
import re
from datetime import datetime, timedelta, timezone

import config as cfg
import database as db
from prompts import REFLECT_QUERY, RUNBOOK_QUERY

log = logging.getLogger("hindsight")

_client = None
_bank_ready = None  # bank_id the bank was last created/confirmed for


def hindsight_enabled() -> bool:
    return bool(cfg.HINDSIGHT_BASE_URL)


def _get_client():
    global _client
    if _client is None:
        from hindsight_client import Hindsight  # pip install hindsight-client

        kwargs = {"base_url": cfg.HINDSIGHT_BASE_URL}
        if cfg.HINDSIGHT_API_KEY:
            kwargs["api_key"] = cfg.HINDSIGHT_API_KEY
        _client = Hindsight(**kwargs)
    return _client


async def _ensure_bank(bank_id: str):
    """create_bank is create-or-update and safe to call repeatedly. `name`/`mission` are deprecated in
    hindsight-client>=0.10, so the bank's behavior is set via retain/reflect/observations mission instead."""
    global _bank_ready
    if _bank_ready == bank_id:
        return
    await _get_client().acreate_bank(
        bank_id=bank_id,
        retain_mission="Record incident-response resolution attempts, including failed ones, precisely.",
        reflect_mission=(
            "Incident-response memory. Prefer verified outcomes over speculation. Always distinguish "
            "fixes that worked from fixes that failed, and flag when the same fix has conflicting results."
        ),
        enable_observations=True,
    )
    _bank_ready = bank_id


# ---- Hindsight SDK calls (checked against hindsight-client==0.10.1's actual signatures) --------------------
async def _hs_retain(bank_id: str, content: str, metadata: dict, tags: list[str]):
    await _ensure_bank(bank_id)
    await _get_client().aretain(
        bank_id=bank_id, content=content, context="incident resolution record",
        metadata=metadata, tags=tags, retain_async=False,
    )


async def _hs_recall(bank_id: str, query: str, service_tag: str | None) -> list[str]:
    await _ensure_bank(bank_id)
    # `tags`/`tags_match` filter server-side by the service tag written at retain time, so recall for
    # "redis-cache" doesn't compete for budget against unrelated services in the same bank.
    kwargs = {"bank_id": bank_id, "query": query, "types": ["experience", "observation"], "budget": "mid"}
    if service_tag:
        kwargs["tags"] = [f"service:{service_tag}"]
        kwargs["tags_match"] = "any"
    resp = await _get_client().arecall(**kwargs)
    return [r.text for r in resp.results if r.text]


async def _hs_reflect(bank_id: str, query: str, service_tag: str | None) -> str:
    await _ensure_bank(bank_id)
    kwargs = {"bank_id": bank_id, "query": query, "budget": "mid"}
    if service_tag:
        kwargs["tags"] = [f"service:{service_tag}"]
        kwargs["tags_match"] = "any"
    resp = await _get_client().areflect(**kwargs)
    return resp.text or "No relevant memory found for this query."


# ---- text / parsing helpers --------------------------------------------------------------------------------
def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9_.\-]{3,}", text.lower()))


def _overlap(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    return round(len(ta & tb) / len(ta | tb), 2) if ta and tb else 0.0


def _field(text: str, name: str) -> str:
    m = re.search(rf"^{name}:\s*(.+)$", text, re.MULTILINE | re.IGNORECASE)
    return m.group(1).strip() if m else ""


def _fix_key(fix: str) -> str:
    """Normalize a fix description so the same action is recognized across incidents."""
    return " ".join(sorted(_tokens(fix)))[:200]


def build_query(incident: dict) -> str:
    return f"{incident['service']} {incident['symptoms']} {incident['logs']}"[:1500]


def build_memory_text(incident: dict, fix: str, result: str, feedback: str, minutes) -> str:
    return (
        f"Incident {incident['code']} resolution record\n"
        f"Service: {incident['service']}\n"
        f"Environment: {incident['environment']}\n"
        f"Symptoms: {incident['symptoms']}\n"
        f"Key logs: {incident['logs'][:600]}\n"
        f"Fix attempted: {fix}\n"
        f"Result: {result.upper()}\n"
        f"Time to resolve: {f'{minutes} minutes' if minutes else 'not recorded'}\n"
        f"Engineer feedback: {feedback or 'none'}\n"
        f"Date: {datetime.now(timezone.utc).date().isoformat()}"
    )


def parse_memory(text: str, query: str) -> dict:
    code = re.search(r"INC-\d+", text)
    date_str = _field(text, "Date")
    return {
        "incident": code.group(0) if code else None,
        "service": _field(text, "Service"),
        "severity": _field(text, "Severity"),
        "fix": _field(text, "Fix attempted"),
        "result": (_field(text, "Result") or "unknown").lower(),
        "feedback": _field(text, "Engineer feedback"),
        "minutes": _field(text, "Time to resolve"),
        "date": date_str,
        "overlap": _overlap(query, text),
        "text": text,
    }


def _enrich_memory_from_local(memory: dict) -> dict:
    """Fill fields omitted by Hindsight summaries from the local incident audit record."""
    code = memory.get("incident") or ""
    match = re.fullmatch(r"INC-(\d+)", code)
    if not match:
        return memory

    incident = db.get_incident(int(match.group(1)))
    if not incident or incident["code"] != code:
        return memory

    memory["service"] = memory.get("service") or incident["service"]
    memory["environment"] = memory.get("environment") or incident["environment"]
    resolutions = db.list_resolutions(incident["id"])
    successful = [r for r in resolutions if r["result"] == "success"]
    selected = (successful or resolutions)[-1] if resolutions else None

    if memory.get("result", "unknown") == "unknown":
        if successful or incident["status"] == "resolved":
            memory["result"] = "success"
        elif resolutions:
            memory["result"] = "failed"
    if selected:
        memory["fix"] = memory.get("fix") or selected["fix"]
        memory["feedback"] = memory.get("feedback") or selected["engineer_feedback"]
        memory["minutes"] = memory.get("minutes") or selected["minutes"]
        memory["date"] = memory.get("date") or selected["created_at"][:10]
    if not memory.get("date"):
        memory["date"] = incident["created_at"][:10]
    return memory


def enrich_recalled_memories(recalled: dict) -> dict:
    """Refresh stored recall snapshots with outcomes recorded after the analysis ran."""
    memories = [
        _enrich_memory_from_local(dict(item))
        for item in recalled.get("memories", [])
    ]
    return {**recalled, "count": len(memories), "memories": memories}


def _annotate_conflicts_and_staleness(memories: list[dict]):
    """Mark memories whose fix has been recorded with a different outcome elsewhere, or that are old."""
    by_fix: dict[str, set[str]] = {}
    for m in memories:
        key = (m["service"] or "").lower(), _fix_key(m["fix"] or "")
        by_fix.setdefault(key, set()).add(m["result"])
    cutoff = datetime.now(timezone.utc).date() - timedelta(days=cfg.STALE_DAYS)
    for m in memories:
        key = (m["service"] or "").lower(), _fix_key(m["fix"] or "")
        m["conflict"] = len(by_fix.get(key, set())) > 1
        try:
            m["stale"] = bool(m["date"]) and datetime.fromisoformat(m["date"]).date() < cutoff
        except ValueError:
            m["stale"] = False


# ---- public interface ---------------------------------------------------------------------------------------
async def recall(incident: dict, limit: int = 5, use_memory: bool = True) -> dict:
    if not use_memory:
        return {"source": "disabled", "count": 0, "memories": [], "error": None}

    bank_id = db.current_bank()
    query = build_query(incident)
    source, texts, error = "none", [], None

    if hindsight_enabled():
        try:
            texts, source = await _hs_recall(bank_id, query, incident.get("service")), "hindsight"
        except Exception as e:  # noqa: BLE001
            error = str(e)
            log.warning("Hindsight recall failed: %s", e)

    if source != "hindsight":
        if cfg.USE_LOCAL_FALLBACK:
            source = "local"
            texts = [t for t in db.fallback_all() if _overlap(query, t) > 0.05]
        else:
            source = "error" if error else "unconfigured"
            texts = []

    recalled = enrich_recalled_memories({
        "source": source,
        "count": 0,
        "memories": [parse_memory(t, query) for t in texts if t],
        "error": error,
    })
    memories = recalled["memories"]
    memories = [m for m in memories if m["incident"] != incident["code"]]  # never recall the incident itself
    # de-duplicate by incident code (Hindsight may return several facts about the same incident)
    seen, deduped = set(), []
    for m in sorted(memories, key=lambda m: m["overlap"], reverse=True):
        if m["incident"] in seen:
            continue
        seen.add(m["incident"])
        deduped.append(m)
    _annotate_conflicts_and_staleness(deduped)
    return enrich_recalled_memories({
        "source": source,
        "count": len(deduped[:limit]),
        "memories": deduped[:limit],
        "error": error,
    })


async def retain(incident: dict, fix: str, result: str, feedback: str, minutes=None) -> str:
    """Store one verified attempt (successful OR failed). Returns where it was stored, never silently drops it."""
    content = build_memory_text(incident, fix, result, feedback, minutes)
    db.fallback_add(content)  # always kept: audit trail for conflict/staleness detection and /stats

    if not hindsight_enabled():
        return "local" if cfg.USE_LOCAL_FALLBACK else "local-only (Hindsight not configured)"

    bank_id = db.current_bank()
    try:
        await _hs_retain(
            bank_id, content,
            metadata={"incident": incident["code"], "service": incident["service"],
                      "environment": incident["environment"], "result": result},
            tags=[f"service:{incident['service']}", f"result:{result}"],
        )
        return "hindsight"
    except Exception as e:  # noqa: BLE001
        log.warning("Hindsight retain failed, kept in local audit store only: %s", e)
        return "local-fallback (Hindsight error)"


def _outcome_summary(service: str | None = None) -> dict:
    incidents = db.list_incidents()
    if service:
        incidents = [i for i in incidents if i["service"].lower() == service.lower()]

    resolutions = db.all_resolutions()
    by_incident: dict[int, list[dict]] = {}
    for resolution in resolutions:
        by_incident.setdefault(resolution["incident_id"], []).append(resolution)

    counts = {"resolved": 0, "failed": 0, "no_outcome": 0}
    services: dict[str, dict] = {}
    worked_attempts = failed_attempts = 0
    for incident in incidents:
        attempts = by_incident.get(incident["id"], [])
        outcomes = {attempt["result"] for attempt in attempts}
        if "success" in outcomes or (not outcomes and incident["status"] == "resolved"):
            outcome = "resolved"
        elif outcomes:
            outcome = "failed"
        else:
            outcome = "no_outcome"

        counts[outcome] += 1
        service_counts = services.setdefault(
            incident["service"],
            {"service": incident["service"], "total_incidents": 0,
             "resolved": 0, "failed": 0, "no_outcome": 0},
        )
        service_counts["total_incidents"] += 1
        service_counts[outcome] += 1
        worked_attempts += sum(attempt["result"] == "success" for attempt in attempts)
        failed_attempts += sum(attempt["result"] == "failed" for attempt in attempts)

    return {
        "total_incidents": len(incidents),
        **counts,
        "worked_attempts": worked_attempts,
        "failed_attempts": failed_attempts,
        "by_service": sorted(services.values(), key=lambda item: item["total_incidents"], reverse=True),
    }


def _format_local_reflection(summary: dict) -> str:
    lines = [
        "### Incident outcomes",
        f"- Total incidents: {summary['total_incidents']}",
        f"- Resolved: {summary['resolved']}",
        f"- Failed: {summary['failed']}",
        f"- No outcome recorded: {summary['no_outcome']}",
        f"- Resolution attempts: {summary['worked_attempts']} worked, {summary['failed_attempts']} failed",
    ]
    if summary["by_service"]:
        lines.extend(["", "### By service"])
        lines.extend(
            f"- {item['service']}: {item['total_incidents']} incidents, "
            f"{item['resolved']} resolved, {item['failed']} failed, "
            f"{item['no_outcome']} without an outcome"
            for item in summary["by_service"]
        )
    return "\n".join(lines)


async def reflect(service: str | None = None) -> dict:
    summary = _outcome_summary(service)
    insights = ""
    error = None
    source = "local"
    if hindsight_enabled():
        bank_id = db.current_bank()
        query = RUNBOOK_QUERY.format(service=service) if service else REFLECT_QUERY
        try:
            insights = await _hs_reflect(bank_id, query, service)
            source = "hindsight"
        except Exception as e:  # noqa: BLE001
            error = str(e)
            log.warning("Hindsight reflect failed: %s", e)

    return {
        "source": source,
        "summary": summary,
        "text": _format_local_reflection(summary),
        "insights": insights,
        "error": error,
    }


def stats() -> dict:
    """Local, cheap statistics for the learning-curve panel. Computed from the audit trail, not from
    Hindsight (Hindsight has no 'list all incidents' call), so this always works regardless of backend."""
    analyses = db.all_analyses()
    resolutions = db.all_resolutions()
    with_mem = [a for a in analyses if a["use_memory"] and a["memories"]["count"] > 0]
    recalled_counts = [a["memories"]["count"] for a in analyses if a["use_memory"]]
    successful_memory_fixes: dict[int, set[str]] = {}
    for analysis in analyses:
        if not analysis["use_memory"]:
            continue
        fixes = {
            _fix_key(item["fix"])
            for item in analysis["memories"].get("memories", [])
            if item.get("result") == "success" and item.get("fix")
        }
        successful_memory_fixes.setdefault(analysis["incident_id"], set()).update(fixes)
    eligible_resolutions = [
        resolution for resolution in resolutions
        if successful_memory_fixes.get(resolution["incident_id"])
    ]
    reused_successes = sum(
        resolution["result"] == "success"
        and _fix_key(resolution["fix"]) in successful_memory_fixes[resolution["incident_id"]]
        for resolution in eligible_resolutions
    )
    minutes = [r["minutes"] for r in resolutions if r["minutes"]]
    trend = minutes[-10:]
    return {
        "incidents_handled": len(db.list_incidents()),
        "analyses_run": len(analyses),
        "avg_memories_recalled": round(sum(recalled_counts) / len(recalled_counts), 1) if recalled_counts else 0,
        "fix_reuse_rate": round(reused_successes / len(eligible_resolutions), 2)
        if eligible_resolutions else 0,
        "memory_backed_resolutions": len(eligible_resolutions),
        "memory_backed_successes": reused_successes,
        "avg_minutes_to_resolve": round(sum(trend) / len(trend), 1) if trend else None,
        "minutes_trend": trend,
        "memory_backed_analyses": len(with_mem),
    }