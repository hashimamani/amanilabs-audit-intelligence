"""
Every API test runs against moto's DynamoDB (and S3/SQS where a test needs
them), in local auth mode, with jobs executed inline. The environment is
fixed before anything imports the app, because settings are read once.
"""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_DIR.parents[1]
DATA_DIR = PROJECT_ROOT / "synthetic_sacco_data"

os.environ.update({
    "APP_ENV": "test",
    "AUTH_MODE": "local",
    "DATASET_STORE": "local",
    "JOB_RUNNER": "inline",
    "TABLE_NAME": "audit-intelligence-test",
    "AWS_DEFAULT_REGION": "eu-west-1",
    "AWS_REGION": "eu-west-1",
    "AWS_ACCESS_KEY_ID": "testing",
    "AWS_SECRET_ACCESS_KEY": "testing",
    "UPLOADS_DIR": tempfile.mkdtemp(prefix="audit-intelligence-uploads-"),
    "ANTHROPIC_API_KEY": "",
})

from moto import mock_aws  # noqa: E402

_moto = mock_aws()
_moto.start()

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.cases.builder import build_cases  # noqa: E402
from app.core.auth import DEFAULT_ADMIN_DEV_PASSWORD, DEFAULT_ADMIN_EMAIL  # noqa: E402
from app.main import app  # noqa: E402
from app.rules.dataset import SaccoDataset  # noqa: E402
from app.rules.engine import RuleEngine  # noqa: E402
from app.scripts.create_tenant import create_tenant  # noqa: E402


# --- rule engine fixtures (session-scoped: one full engine run) ------------

@pytest.fixture(scope="session")
def dataset():
    return SaccoDataset(str(DATA_DIR))


@pytest.fixture(scope="session")
def flags(dataset):
    return RuleEngine().run(dataset)


@pytest.fixture(scope="session")
def cases(flags, dataset):
    return build_cases(flags, dataset=dataset)


@pytest.fixture(scope="session")
def ground_truth():
    with open(DATA_DIR / "ground_truth.json") as f:
        return json.load(f)


# --- API fixtures ----------------------------------------------------------

@pytest.fixture(scope="session", autouse=True)
def _table_and_demo_tenant():
    """What the app does at startup, done once up front so a test file that
    never opens the API still has the table and the demo tenant."""
    from app.core.bootstrap import bootstrap_local

    bootstrap_local()


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


def _login(client, email, password):
    resp = client.post("/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _headers(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="session")
def login():
    return _login


@pytest.fixture(scope="session")
def headers():
    return _headers


@pytest.fixture(scope="session")
def default_token(client):
    return _login(client, DEFAULT_ADMIN_EMAIL, DEFAULT_ADMIN_DEV_PASSWORD)


@pytest.fixture(scope="session")
def provision_tenant(client):
    """Creates a tenant with an admin and returns a bearer token for it."""
    def _provision(slug: str, name: str = "Test SACCO"):
        admin, password = create_tenant(slug, name, f"admin@{slug}.example", f"{name} Admin")
        return _login(client, admin["email"], password)
    return _provision


@pytest.fixture(scope="session")
def run_demo_analysis(client, default_token):
    def _run(token=None):
        resp = client.post("/analysis/run", json={}, headers=_headers(token or default_token))
        assert resp.status_code == 202, resp.text
        body = resp.json()
        assert body["status"] == "succeeded", body
        return body
    return _run


@pytest.fixture(scope="session")
def default_case_ids(client, default_token, run_demo_analysis):
    run_demo_analysis()
    cases = client.get("/cases?limit=200", headers=_headers(default_token)).json()
    return [c["id"] for c in cases]


def fake_ai_client(text="placeholder", stop_reason="end_turn"):
    block = MagicMock(type="text", text=text)
    fake = MagicMock()
    fake.messages.create.return_value = MagicMock(content=[block], stop_reason=stop_reason)
    return fake


@pytest.fixture
def mock_ai(monkeypatch):
    """Swaps the one Anthropic client provider both routes and jobs use."""
    def _install(fake):
        monkeypatch.setattr("app.core.ai._client_provider", lambda: fake)
        return fake
    return _install
