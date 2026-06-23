"""Audit log helpers — append-only event records on a Job."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List

from sqlalchemy.orm import Session

from ..db import Job


def append_event(
    db: Session,
    job: Job,
    *,
    event: str,
    detail: Dict[str, Any] | None = None,
) -> None:
    entries: List[Dict[str, Any]] = list(job.audit or [])
    entries.append(
        {
            "at": datetime.utcnow().isoformat(),
            "event": event,
            "detail": detail or {},
        }
    )
    job.audit = entries
    db.add(job)
    db.commit()
