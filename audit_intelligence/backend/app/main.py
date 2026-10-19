from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.bootstrap import bootstrap_local
from app.core.settings import get_settings


@asynccontextmanager
async def lifespan(_app: FastAPI):
    bootstrap_local()
    yield


app = FastAPI(title="Audit Intelligence API", version="0.2.0", lifespan=lifespan)

settings = get_settings()
if settings.is_local:
    # Only the local Vite dev server is cross-origin. Deployed, CloudFront
    # serves the app and the API from one origin and no CORS exists at all.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(api_router)


@app.get("/health")
def health():
    return {"status": "ok"}
