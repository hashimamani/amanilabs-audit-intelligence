FROM python:3.12-slim

# app/core/datasets.py resolves the "default" dataset_id relative to the
# repo layout (backend two levels under the repo root, synthetic_sacco_data
# a sibling of audit_intelligence/) - mirror that layout here rather than
# flattening it, so the path arithmetic in datasets.py needs no special-casing
# for docker.
WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY audit_intelligence/backend/app ./audit_intelligence/backend/app
COPY synthetic_sacco_data ./synthetic_sacco_data

WORKDIR /app/audit_intelligence/backend

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
