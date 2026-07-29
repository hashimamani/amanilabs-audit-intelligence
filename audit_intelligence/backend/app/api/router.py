from fastapi import APIRouter

from app.api.routes import upload, analysis, cases, tenant

api_router = APIRouter()
api_router.include_router(upload.router)
api_router.include_router(analysis.router)
api_router.include_router(cases.router)
api_router.include_router(tenant.router)
