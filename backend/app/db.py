"""SQLite via SQLAlchemy.

The schema is small and stores enough to drive idempotency, audit, and recovery.
Heavy intermediate objects (parser output, LLM payloads, normalized result) are
stored as JSON blobs.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Iterator

from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    JSON,
    String,
    Text,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings

_settings = get_settings()
engine = create_engine(
    _settings.database_url,
    connect_args={"check_same_thread": False} if _settings.database_url.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


class Job(Base):
    __tablename__ = "jobs"

    id = Column(String, primary_key=True)
    status = Column(String, nullable=False, default="uploaded")
    progress = Column(Integer, nullable=False, default=0)

    file_name = Column(String, nullable=False)
    file_path = Column(String, nullable=False)
    file_type = Column(String, nullable=True)
    file_checksum = Column(String, nullable=False, index=True)

    options = Column(JSON, nullable=False, default=dict)

    parser_version = Column(String, nullable=False)
    prompt_version = Column(String, nullable=False)
    openai_model = Column(String, nullable=True)
    extraction_mode = Column(String, nullable=False, default="auto")

    ir = Column(JSON, nullable=True)
    raw_llm_request = Column(JSON, nullable=True)
    raw_llm_response = Column(Text, nullable=True)

    result = Column(JSON, nullable=True)
    edited_result = Column(JSON, nullable=True)

    warnings = Column(JSON, nullable=False, default=list)
    errors = Column(JSON, nullable=False, default=list)
    sheet_summary = Column(JSON, nullable=False, default=list)

    export_path = Column(String, nullable=True)
    audit = Column(JSON, nullable=False, default=list)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def public_status(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "status": self.status,
            "progress": self.progress,
            "fileName": self.file_name,
            "fileType": self.file_type,
            "warnings": self.warnings or [],
            "errors": self.errors or [],
            "sheetSummary": self.sheet_summary or [],
            "options": self.options or {},
            "createdAt": self.created_at.isoformat(),
            "updatedAt": self.updated_at.isoformat(),
        }


def init_db() -> None:
    Base.metadata.create_all(bind=engine)


def get_session() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def dump_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)
