import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Optional

import config as cfg

SCHEMA = """
CREATE TABLE IF NOT EXISTS incidents (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  service TEXT NOT NULL,
  environment TEXT NOT NULL,
  symptoms TEXT NOT NULL,
  logs TEXT NOT NULL DEFAULT '',
  severity TEXT,
  status TEXT NOT NULL DEFAULT 'open',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS analyses (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  incident_id INTEGER NOT NULL REFERENCES incidents(id),
  payload TEXT NOT NULL,
  memories TEXT NOT NULL,
  use_memory INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS resolutions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  incident_id INTEGER NOT NULL REFERENCES incidents(id),
  fix TEXT NOT NULL,
  result TEXT NOT NULL,
  engineer_feedback TEXT NOT NULL DEFAULT '',
  retained_in TEXT NOT NULL DEFAULT 'none',
  minutes INTEGER,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS memory_fallback (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  content TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
"""


def now(days_ago: int = 0) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat(timespec="seconds")


@contextmanager
def conn():
    c = sqlite3.connect(cfg.DB_PATH)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()


def _ensure_column(c, table: str, column: str, ddl: str):
    cols = [r["name"] for r in c.execute(f"PRAGMA table_info({table})")]
    if column not in cols:
        c.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def init_db():
    with conn() as c:
        c.executescript(SCHEMA)
        # migrate databases created by the earlier version
        _ensure_column(c, "resolutions", "minutes", "INTEGER")
        _ensure_column(c, "analyses", "use_memory", "INTEGER NOT NULL DEFAULT 1")


# ---- settings / bank ------------------------------------------------------------------------------------
def get_setting(key: str, default: Optional[str] = None) -> Optional[str]:
    with conn() as c:
        row = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(key: str, value: str):
    with conn() as c:
        c.execute("INSERT INTO settings(key, value) VALUES (?,?) "
                  "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))


def current_bank() -> str:
    return get_setting("bank_id") or cfg.HINDSIGHT_BANK_ID


def reset_all(new_bank_id: str):
    """Wipe local data and switch to a brand-new Hindsight bank."""
    with conn() as c:
        for t in ("analyses", "resolutions", "incidents", "memory_fallback"):
            c.execute(f"DELETE FROM {t}")
        c.execute("DELETE FROM sqlite_sequence")
    set_setting("bank_id", new_bank_id)


# ---- incidents ------------------------------------------------------------------------------------------
def code(incident_id: int) -> str:
    return f"INC-{incident_id:03d}"


def _incident(row) -> dict:
    d = dict(row)
    d["code"] = code(d["id"])
    return d


def create_incident(service, environment, symptoms, logs, created_at: Optional[str] = None) -> dict:
    with conn() as c:
        cur = c.execute(
            "INSERT INTO incidents(service, environment, symptoms, logs, created_at) VALUES (?,?,?,?,?)",
            (service, environment, symptoms, logs, created_at or now()),
        )
        row = c.execute("SELECT * FROM incidents WHERE id=?", (cur.lastrowid,)).fetchone()
    return _incident(row)


def find_open_duplicate(service: str, symptoms: str) -> Optional[dict]:
    with conn() as c:
        row = c.execute(
            "SELECT * FROM incidents WHERE lower(service)=? AND lower(symptoms)=? AND status!='resolved' "
            "ORDER BY id DESC LIMIT 1",
            (service.strip().lower(), symptoms.strip().lower()),
        ).fetchone()
    return _incident(row) if row else None


def get_incident(incident_id: int):
    with conn() as c:
        row = c.execute("SELECT * FROM incidents WHERE id=?", (incident_id,)).fetchone()
    return _incident(row) if row else None


def list_incidents() -> list:
    with conn() as c:
        rows = c.execute("SELECT * FROM incidents ORDER BY id DESC").fetchall()
    return [_incident(r) for r in rows]


def update_incident(incident_id: int, **fields):
    keys = ", ".join(f"{k}=?" for k in fields)
    with conn() as c:
        c.execute(f"UPDATE incidents SET {keys} WHERE id=?", (*fields.values(), incident_id))


def delete_incidents(ids: list):
    with conn() as c:
        for i in ids:
            for t in ("analyses", "resolutions"):
                c.execute(f"DELETE FROM {t} WHERE incident_id=?", (i,))
            c.execute("DELETE FROM incidents WHERE id=?", (i,))


# ---- analyses / resolutions -----------------------------------------------------------------------------
def save_analysis(incident_id: int, payload: dict, memories: dict, use_memory: bool = True):
    with conn() as c:
        c.execute(
            "INSERT INTO analyses(incident_id, payload, memories, use_memory, created_at) VALUES (?,?,?,?,?)",
            (incident_id, json.dumps(payload), json.dumps(memories), int(use_memory), now()),
        )


def latest_analysis(incident_id: int):
    with conn() as c:
        row = c.execute(
            "SELECT * FROM analyses WHERE incident_id=? ORDER BY id DESC LIMIT 1", (incident_id,)
        ).fetchone()
    if not row:
        return None
    return {"analysis": json.loads(row["payload"]), "memories": json.loads(row["memories"])}


def all_analyses() -> list:
    with conn() as c:
        rows = c.execute("SELECT * FROM analyses ORDER BY id").fetchall()
    return [
        {"id": r["id"], "incident_id": r["incident_id"], "use_memory": bool(r["use_memory"]),
         "analysis": json.loads(r["payload"]), "memories": json.loads(r["memories"])}
        for r in rows
    ]


def save_resolution(incident_id, fix, result, feedback, retained_in, minutes=None, created_at=None) -> dict:
    with conn() as c:
        cur = c.execute(
            "INSERT INTO resolutions(incident_id, fix, result, engineer_feedback, retained_in, minutes, created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (incident_id, fix, result, feedback, retained_in, minutes, created_at or now()),
        )
        row = c.execute("SELECT * FROM resolutions WHERE id=?", (cur.lastrowid,)).fetchone()
    return dict(row)


def list_resolutions(incident_id: int) -> list:
    with conn() as c:
        rows = c.execute(
            "SELECT * FROM resolutions WHERE incident_id=? ORDER BY id", (incident_id,)
        ).fetchall()
    return [dict(r) for r in rows]


def all_resolutions() -> list:
    with conn() as c:
        rows = c.execute("SELECT * FROM resolutions ORDER BY id").fetchall()
    return [dict(r) for r in rows]


# ---- local fallback memory (only used when USE_LOCAL_FALLBACK=true) --------------------------------------
def fallback_add(content: str):
    with conn() as c:
        c.execute("INSERT INTO memory_fallback(content, created_at) VALUES (?,?)", (content, now()))


def fallback_all() -> list:
    with conn() as c:
        rows = c.execute("SELECT content FROM memory_fallback ORDER BY id").fetchall()
    return [r["content"] for r in rows]
