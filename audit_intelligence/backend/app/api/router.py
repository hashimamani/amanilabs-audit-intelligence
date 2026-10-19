from fastapi import APIRouter

from app.api.routes import analysis, analytics, auth, cases, datasets, jobs, reports, users

api_router = APIRouter()
api_router.include_router(datasets.router)
api_router.include_router(analysis.router)
api_router.include_router(cases.router)
api_router.include_router(jobs.router)
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(analytics.router)
api_router.include_router(reports.router)
