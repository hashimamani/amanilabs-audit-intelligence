from app.core.logging import logger
from app.db import repository as repo
from app.jobs.service import TERMINAL, JobFailed


def execute_job(tenant_slug: str, job_id: str) -> dict | None:
    from app.jobs.analysis import run_analysis_job
    from app.jobs.analytics import run_analytics_job
    from app.jobs.report import run_report_job

    handlers = {"analysis": run_analysis_job, "analytics": run_analytics_job, "report": run_report_job}

    job = repo.get_job(tenant_slug, job_id)
    if job is None:
        logger.warning("job not found", tenant_slug=tenant_slug, job_id=job_id)
        return None
    # A redelivered message for a finished job is a no-op; a job left
    # "running" by a crashed worker is retried.
    if job["status"] in TERMINAL:
        return job

    job = repo.update_job(tenant_slug, job_id, status="running", started_at=repo.utcnow_iso())
    logger.info("job started", job_id=job_id, kind=job["kind"], tenant_slug=tenant_slug)
    try:
        result = handlers[job["kind"]](tenant_slug, job)
    except JobFailed as e:
        logger.warning("job failed", job_id=job_id, kind=job["kind"], error=str(e))
        return repo.update_job(tenant_slug, job_id, status="failed", error=str(e))
    except Exception:
        logger.exception("job crashed", job_id=job_id, kind=job["kind"])
        return repo.update_job(tenant_slug, job_id, status="failed", error="The job failed unexpectedly. Try again, or contact support if it persists.")
    logger.info("job succeeded", job_id=job_id, kind=job["kind"])
    return repo.update_job(tenant_slug, job_id, status="succeeded", result=result)
