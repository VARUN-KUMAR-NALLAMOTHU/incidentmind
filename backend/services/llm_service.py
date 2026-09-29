import json
import logging
import re

import config as cfg
from prompts import ANALYSIS_SYSTEM

log = logging.getLogger("llm")

REQUIRED_KEYS = {
    "severity", "detected_symptoms", "root_cause", "confidence",
    "recommendation", "reasoning", "memory_influenced", "memories_used", "avoid",
}


def _user_prompt(incident: dict, recalled: dict) -> str:
    mems = [
        {k: m[k] for k in ("incident", "service", "fix", "result", "feedback", "date", "conflict", "stale")}
        for m in recalled["memories"]
    ]
    return json.dumps(
        {
            "CURRENT_EVIDENCE": {k: incident[k] for k in ("service", "environment", "symptoms", "logs")},
            "HISTORICAL_CONTEXT": mems or "none found",
        },
        indent=2,
    )


def _parse_json(raw: str) -> dict:
    raw = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.MULTILINE).strip()
    data = json.loads(raw)  # raises ValueError on malformed JSON -> caught by caller, triggers retry/fallback
    if not isinstance(data, dict) or not REQUIRED_KEYS.issubset(data.keys()):
        missing = REQUIRED_KEYS - set(data if isinstance(data, dict) else {})
        raise ValueError(f"LLM response missing required keys: {sorted(missing)}")
    return data


def _normalize(data: dict, recalled: dict) -> dict:
    valid_codes = {m["incident"] for m in recalled["memories"]}
    used = [c for c in data.get("memories_used", []) if c in valid_codes]  # drop hallucinated codes
    return {
        "severity": str(data.get("severity", "medium")).lower(),
        "detected_symptoms": data.get("detected_symptoms", []),
        "root_cause": data.get("root_cause", "Unknown"),
        "confidence": str(data.get("confidence", "low")).lower(),
        "recommendation": data.get("recommendation", ""),
        "reasoning": data.get("reasoning", ""),
        "memory_influenced": bool(used),
        "memories_used": used,
        "avoid": data.get("avoid", []),
    }


def _mock(incident: dict, recalled: dict) -> dict:
    """Deterministic stand-in used when GROQ_API_KEY is not set, so the UI always works."""
    wins = [m for m in recalled["memories"] if m["result"] == "success" and not m.get("conflict")]
    fails = [m for m in recalled["memories"] if m["result"] == "failed"]
    conflicted = [m for m in recalled["memories"] if m.get("conflict")]
    text = f"{incident['symptoms']} {incident['logs']}".lower()
    sev = "high" if any(w in text for w in ("504", "timeout", "exhaust", "down")) else "medium"
    if wins:
        best = wins[0]
        rec = f"Apply the fix that worked before: {best['fix']}"
        reasoning = f"{best['incident']} had a similar profile and this fix succeeded."
        confidence = "medium"
    else:
        rec = "Inspect the timeout and pool settings named in the logs before restarting the service."
        reasoning = "No relevant past experience; reasoning from the logs alone. (mock engine)"
        confidence = "low"
    if fails:
        reasoning += f" Previously failed for similar incidents: {', '.join(f['fix'] for f in fails)}."
    if conflicted:
        reasoning += " Some past fixes have conflicting outcomes recorded; treat those with caution."
        confidence = "low"
    return {
        "severity": sev,
        "detected_symptoms": [s.strip() for s in incident["symptoms"].split(",") if s.strip()][:5],
        "root_cause": "Likely resource or configuration limit (mock analysis)",
        "confidence": confidence,
        "recommendation": rec,
        "reasoning": reasoning,
        "memory_influenced": bool(recalled["memories"]),
        "memories_used": [m["incident"] for m in recalled["memories"] if m["incident"]],
        "avoid": [f["fix"] for f in fails],
    }


def _call_groq(model: str, incident: dict, recalled: dict) -> dict:
    from groq import Groq  # pip install groq

    client = Groq(api_key=cfg.GROQ_API_KEY)
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": ANALYSIS_SYSTEM},
            {"role": "user", "content": _user_prompt(incident, recalled)},
        ],
        response_format={"type": "json_object"},
        temperature=0.2,
    )
    return _parse_json(resp.choices[0].message.content)


def analyze(incident: dict, recalled: dict) -> dict:
    if not cfg.GROQ_API_KEY:
        result = _normalize(_mock(incident, recalled), recalled)
        result["engine"] = "mock"
        return result

    models = [cfg.GROQ_MODEL, cfg.GROQ_FALLBACK_MODEL]
    last_error = None
    for model in models:
        for attempt in range(cfg.LLM_RETRIES + 1):
            try:
                data = _call_groq(model, incident, recalled)
                result = _normalize(data, recalled)
                result["engine"] = model if model == cfg.GROQ_MODEL else f"{model} (fallback)"
                return result
            except Exception as e:  # noqa: BLE001 - malformed JSON, function-calling errors, timeouts, etc.
                last_error = e
                log.warning("Groq call failed (model=%s, attempt=%s): %s", model, attempt + 1, e)
    raise RuntimeError(f"All LLM attempts failed across {models}: {last_error}") from last_error
