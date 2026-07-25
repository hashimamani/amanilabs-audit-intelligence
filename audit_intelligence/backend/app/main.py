from fastapi import FastAPI

from app.api.router import api_router
from app.core.db import Base, engine

app = FastAPI(title="Audit Intelligence API", version="0.1.0")

# ORM classes are registered on Base.metadata as a side effect of importing
# app.api.router (which imports the route modules, which import app.db.models),
# so this must run after that import, not before.
Base.metadata.create_all(bind=engine)

app.include_router(api_router)


@app.get("/health")
def health():
    return {"status": "ok"}
