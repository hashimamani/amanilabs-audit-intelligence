from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.db import Base, SessionLocal, engine
from app.core.auth import ensure_default_tenant_and_admin

app = FastAPI(title="Audit Intelligence API", version="0.1.0")

# Single-tenant, pre-pilot: wide open to localhost dev ports is fine for now.
# Tighten this to a real allowlist before this is ever deployed anywhere.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ORM classes are registered on Base.metadata as a side effect of importing
# app.api.router (which imports the route modules, which import app.db.models),
# so this must run after that import, not before.
Base.metadata.create_all(bind=engine)

with SessionLocal() as _startup_db:
    ensure_default_tenant_and_admin(_startup_db)

app.include_router(api_router)


@app.get("/health")
def health():
    return {"status": "ok"}
