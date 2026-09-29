import importlib
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture()
def app_modules(tmp_path, monkeypatch):
    """Fresh config/database/services wired to an isolated temp SQLite file for each test."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("HINDSIGHT_BASE_URL", "")  # Hindsight disabled unless a test turns it on
    monkeypatch.setenv("USE_LOCAL_FALLBACK", "false")
    monkeypatch.setenv("GROQ_API_KEY", "")  # mock LLM engine
    monkeypatch.setenv("STALE_DAYS", "90")

    for name in ("config", "database", "services.hindsight_service", "services.llm_service", "api.routes", "main"):
        sys.modules.pop(name, None)

    import config as cfg
    import database as db

    importlib.reload(cfg)
    importlib.reload(db)
    db.init_db()

    import services.hindsight_service as memory
    import services.llm_service as llm

    importlib.reload(memory)
    importlib.reload(llm)
    return {"cfg": cfg, "db": db, "memory": memory, "llm": llm}


@pytest.fixture()
def client(app_modules, monkeypatch):
    from fastapi.testclient import TestClient

    import api.routes as routes
    import main

    importlib.reload(routes)
    importlib.reload(main)
    return TestClient(main.app)
