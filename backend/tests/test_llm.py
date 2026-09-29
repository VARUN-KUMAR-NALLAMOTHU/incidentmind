import json


def test_mock_engine_prefers_successful_fix(app_modules):
    llm = app_modules["llm"]
    incident = {"service": "redis-cache", "environment": "Production",
                "symptoms": "Redis timeout, 504", "logs": "ERROR timeout"}
    recalled = {"source": "local", "count": 2, "error": None, "memories": [
        {"incident": "INC-001", "service": "redis-cache", "fix": "Increase pool size", "result": "success",
         "feedback": "worked", "date": "2026-01-01", "conflict": False, "stale": False},
        {"incident": "INC-002", "service": "redis-cache", "fix": "Restart Redis", "result": "failed",
         "feedback": "no effect", "date": "2026-01-02", "conflict": False, "stale": False},
    ]}
    result = llm.analyze(incident, recalled)
    assert result["engine"] == "mock"
    assert "Increase pool size" in result["recommendation"]
    assert "Restart Redis" in result["avoid"]
    assert "INC-001" in result["memories_used"]


def test_mock_engine_handles_no_memory(app_modules):
    llm = app_modules["llm"]
    incident = {"service": "kafka", "environment": "Production",
                "symptoms": "Consumer disconnecting", "logs": "ERROR disconnect"}
    recalled = {"source": "none", "count": 0, "error": None, "memories": []}
    result = llm.analyze(incident, recalled)
    assert result["memory_influenced"] is False
    assert result["memories_used"] == []


def test_normalize_drops_hallucinated_memory_codes(app_modules):
    llm = app_modules["llm"]
    recalled = {"memories": [{"incident": "INC-001"}]}
    data = {"severity": "high", "detected_symptoms": [], "root_cause": "x", "confidence": "high",
            "recommendation": "y", "reasoning": "z", "memory_influenced": True,
            "memories_used": ["INC-001", "INC-999"], "avoid": []}
    result = llm._normalize(data, recalled)
    assert result["memories_used"] == ["INC-001"]


def test_prompt_separates_current_evidence_from_historical_context(app_modules):
    llm = app_modules["llm"]
    incident = {
        "service": "payment-api", "environment": "Production",
        "symptoms": "Duplicate webhook", "logs": "ERROR duplicate notification",
    }
    recalled = {"memories": [{
        "incident": "INC-001", "service": "database", "fix": "Restart database",
        "result": "success", "feedback": "worked", "date": "2026-01-01",
        "conflict": False, "stale": False,
    }]}

    prompt = json.loads(llm._user_prompt(incident, recalled))

    assert prompt["CURRENT_EVIDENCE"]["logs"] == "ERROR duplicate notification"
    assert prompt["HISTORICAL_CONTEXT"][0]["service"] == "database"
