from collections import Counter

from app.cases.builder import build_cases
from app.core import datasets
from app.db import repository as repo
from app.jobs.service import JobFailed
from app.rules.dataset import SaccoDataset
from app.rules.engine import RuleEngine


def run_analysis_job(tenant_slug: str, job: dict) -> dict:
    run_id = int(job["payload"]["run_id"])
    dataset_id = job["payload"].get("dataset_id") or datasets.DEFAULT_DATASET_ID
    repo.update_run(tenant_slug, run_id, status="running")
    try:
        path = datasets.materialize(tenant_slug, dataset_id)
    except (datasets.DatasetNotFoundError, datasets.DatasetNotReadyError) as e:
        repo.update_run(tenant_slug, run_id, status="failed", error=str(e))
        raise JobFailed(str(e)) from e
    try:
        dataset = SaccoDataset(str(path))
        flags = RuleEngine().run(dataset)
        cases = build_cases(flags, dataset=dataset)
        repo.put_cases(tenant_slug, run_id, [c.to_dict() for c in cases])
        severity_counts = Counter(c.severity.value for c in cases)
        rule_counts = Counter(rule for c in cases for rule in c.triggered_rules)
        return repo.update_run(
            tenant_slug, run_id, status="succeeded", flag_count=len(flags), case_count=len(cases),
            severity_counts=dict(severity_counts), rule_counts=dict(rule_counts), completed_at=repo.utcnow_iso(),
        )
    except Exception as e:
        repo.update_run(tenant_slug, run_id, status="failed", error=f"{type(e).__name__}: {e}"[:500])
        raise
    finally:
        datasets.discard_materialized(path)
