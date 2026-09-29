"""Run this against real Hindsight Cloud (or a local Hindsight server) before the demo, to confirm the
retain -> recall -> reflect loop actually talks to Hindsight and not just the local fallback.

Usage:
    cd backend && python ../scripts/smoke_hindsight.py
Requires HINDSIGHT_BASE_URL (and usually HINDSIGHT_API_KEY) set in backend/.env.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import config as cfg  # noqa: E402

if not cfg.HINDSIGHT_BASE_URL:
    print("HINDSIGHT_BASE_URL is not set - nothing to smoke test. Fill in backend/.env first.")
    raise SystemExit(1)

from hindsight_client import Hindsight  # noqa: E402

client = Hindsight(base_url=cfg.HINDSIGHT_BASE_URL, api_key=cfg.HINDSIGHT_API_KEY or None)
bank = f"{cfg.HINDSIGHT_BANK_ID}-smoke"

print(f"Bank: {bank}")
print("1) create_bank (create-or-update, safe to repeat) ...")
client.create_bank(
    bank_id=bank,
    retain_mission="Record incident-response resolution attempts, including failed ones, precisely.",
    reflect_mission="Incident-response memory: prefer verified outcomes; flag failed fixes.",
    enable_observations=True,
)
print("   ok")

print("2) retain (with tags for service-based filtering) ...")
client.retain(
    bank_id=bank, context="incident resolution record", retain_async=False,
    content=(
        "Incident INC-999 resolution record\nService: redis-cache\nEnvironment: Production\n"
        "Symptoms: Redis timeout\nFix attempted: Restarting Redis\nResult: FAILED\n"
        "Engineer feedback: did not help\nDate: 2026-01-01\n\n"
        "Incident INC-998 resolution record\nService: redis-cache\nEnvironment: Production\n"
        "Symptoms: Redis timeout\nFix attempted: Increasing maxclients and fixing the connection pool leak\n"
        "Result: SUCCESS\nEngineer feedback: fixed immediately\nDate: 2026-01-02"
    ),
    metadata={"incident": "INC-999", "service": "redis-cache", "result": "failed"},
    tags=["service:redis-cache", "result:failed"],
)
print("   ok")

print("3) recall (filtered by tag) ...")
res = client.recall(bank_id=bank, query="Redis connection timeouts", budget="mid",
                     tags=["service:redis-cache"], tags_match="any")
for r in res.results:
    print(f"   [{r.type}] {r.text[:160]}")
if not res.results:
    print("   (no results - if unexpected, check the query/budget or wait a moment for indexing)")

print("4) reflect (default budget is 'low'; using 'mid' here) ...")
refl = client.reflect(bank_id=bank, query="What should I avoid for Redis timeouts?", budget="mid")
print("  ", (refl.text or "(empty)")[:400])

print("\nSmoke test finished. If steps 3-4 returned real content, Hindsight is wired up correctly.")
