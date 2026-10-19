"""
Every environment-dependent value, read once from the environment.

Three modes matter:
- local: a developer laptop or docker compose. DynamoDB Local, passwords
  checked by this app, datasets on disk, jobs run inline in the request.
- tests: the same as local but moto stands in for DynamoDB/S3/SQS.
- dev/prod (Lambda): the real table, Cognito-issued tokens, S3 datasets,
  jobs dispatched through SQS to the worker function.
"""

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND_DIR.parents[1]


@dataclass(frozen=True)
class Settings:
    app_env: str
    aws_region: str
    table_name: str
    dynamodb_endpoint: str | None

    auth_mode: str
    local_jwt_secret: str
    cognito_user_pool_id: str | None
    cognito_client_id: str | None

    dataset_store: str
    datasets_bucket: str | None
    uploads_dir: Path
    demo_dataset_dir: Path
    upload_url_ttl_seconds: int

    job_runner: str
    jobs_queue_url: str | None

    anthropic_api_key: str | None
    cors_origins: tuple[str, ...]

    @property
    def is_local(self) -> bool:
        """local = a laptop or docker compose; test = the pytest suite under
        moto. Both self-bootstrap the table and the demo tenant."""
        return self.app_env in ("local", "test")


def _env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    return value if value not in (None, "") else default


def _anthropic_api_key() -> str | None:
    """The key comes from the environment locally and from Secrets Manager
    when deployed (a Lambda environment variable cannot hold a secret
    reference). The secret is created holding "unset" so a fresh deployment
    degrades to "AI features are not configured" rather than failing."""
    direct = _env("ANTHROPIC_API_KEY")
    if direct:
        return direct
    secret_arn = _env("ANTHROPIC_API_KEY_SECRET_ARN")
    if not secret_arn:
        return None
    import boto3

    try:
        value = boto3.client("secretsmanager").get_secret_value(SecretId=secret_arn).get("SecretString", "")
    except Exception:
        return None
    return value if value and value != "unset" else None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    app_env = _env("APP_ENV", "local")
    is_local = app_env in ("local", "test")
    return Settings(
        app_env=app_env,
        aws_region=_env("AWS_REGION", _env("AWS_DEFAULT_REGION", "eu-west-1")),
        table_name=_env("TABLE_NAME", f"audit-intelligence-{app_env}"),
        dynamodb_endpoint=_env("DYNAMODB_ENDPOINT", "http://localhost:8000" if app_env == "local" else None),
        auth_mode=_env("AUTH_MODE", "local" if is_local else "cognito"),
        local_jwt_secret=_env("LOCAL_JWT_SECRET", "local-dev-only-not-a-secret-32-bytes-min"),
        cognito_user_pool_id=_env("COGNITO_USER_POOL_ID"),
        cognito_client_id=_env("COGNITO_CLIENT_ID"),
        dataset_store=_env("DATASET_STORE", "local" if is_local else "s3"),
        datasets_bucket=_env("DATASETS_BUCKET"),
        uploads_dir=Path(_env("UPLOADS_DIR", str(BACKEND_DIR / "data" / "uploads"))),
        demo_dataset_dir=Path(_env("DEMO_DATASET_DIR", str(PROJECT_ROOT / "synthetic_sacco_data"))),
        upload_url_ttl_seconds=int(_env("UPLOAD_URL_TTL_SECONDS", "900")),
        job_runner=_env("JOB_RUNNER", "inline" if is_local else "sqs"),
        jobs_queue_url=_env("JOBS_QUEUE_URL"),
        anthropic_api_key=_anthropic_api_key(),
        cors_origins=tuple(
            o.strip() for o in _env("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if o.strip()
        ),
    )
