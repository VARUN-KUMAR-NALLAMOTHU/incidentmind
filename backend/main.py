from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import database as db
from api.routes import router
import config as cfg

db.init_db()
app = FastAPI(title="IncidentMind")
app.add_middleware(CORSMiddleware, allow_origins=cfg.CORS_ORIGINS, allow_methods=["*"], allow_headers=["*"])
app.include_router(router)
