"""
SQLAlchemy ORM models for persisting analysis runs and the cases they produce.

Deliberately NOT normalized down to individual flag/evidence rows: flags,
evidence, timeline and related_entities are stored as JSON blobs on the
Case row. They're forensic detail attached to a case (write-once per run,
read as a unit), not something the API needs to query independently of
their case - normalizing them now would be exactly the kind of ceremony
the project's working notes say to avoid until there's a real reason.
status/notes/assigned_auditor/outcome ARE first-class columns because
those are the fields the API actually mutates.
"""

from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, Integer, String, Float, DateTime, JSON, ForeignKey, Text
from sqlalchemy.orm import relationship

from app.core.db import Base


def utcnow():
    return datetime.now(timezone.utc)


class TenantORM(Base):
    __tablename__ = "tenants"

    id = Column(Integer, primary_key=True)
    slug = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, nullable=False)
    created_at = Column(DateTime, default=utcnow)


class UserORM(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    name = Column(String, nullable=False)
    role = Column(String, nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=utcnow)

    tenant = relationship("TenantORM")


class AnalysisRunORM(Base):
    __tablename__ = "analysis_runs"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    dataset_id = Column(String, nullable=False)
    dataset_dir = Column(String, nullable=False)
    created_at = Column(DateTime, default=utcnow)
    flag_count = Column(Integer, default=0)
    case_count = Column(Integer, default=0)

    cases = relationship("CaseORM", back_populates="run", cascade="all, delete-orphan")


class CaseORM(Base):
    __tablename__ = "cases"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    case_ref = Column(String, unique=True, index=True, nullable=False)
    run_id = Column(Integer, ForeignKey("analysis_runs.id"), nullable=False)

    subject_type = Column(String, nullable=False)
    subject_id = Column(String, nullable=False, index=True)
    subject_name = Column(String, nullable=False)
    risk_score = Column(Float, nullable=False)
    severity = Column(String, nullable=False, index=True)
    status = Column(String, nullable=False, default="Open", index=True)

    triggered_rules = Column(JSON, nullable=False, default=list)
    flags = Column(JSON, nullable=False, default=list)
    evidence = Column(JSON, nullable=False, default=list)
    timeline = Column(JSON, nullable=False, default=list)
    related_entities = Column(JSON, nullable=False, default=dict)
    recommended_actions = Column(JSON, nullable=False, default=list)

    assigned_auditor = Column(String, nullable=True)
    notes = Column(JSON, nullable=False, default=list)
    outcome = Column(String, nullable=True)
    ai_summary = Column(Text, nullable=True)

    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    run = relationship("AnalysisRunORM", back_populates="cases")
