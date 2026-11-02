"""Bug / suggestion reports: validation, persistence and review lifecycle.

Kept service-level so the HTTP layer stays thin and the rules are unit-testable
without spinning up the API.
"""

from __future__ import annotations

import base64
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app import models

MAX_TEXT = 2000
MAX_ATTACHMENTS = 3
MAX_ATTACHMENT_BYTES = 4 * 1024 * 1024
STATUS_NEW = "NEW"
STATUS_IN_PROGRESS = "IN_PROGRESS"
STATUS_RESOLVED = "RESOLVED"
STATUSES = (STATUS_NEW, STATUS_IN_PROGRESS, STATUS_RESOLVED)


class BugReportError(Exception):
    """Business-rule violation; ``status`` maps 1:1 onto an HTTP status code."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _decode_attachment(item: Dict[str, Any]) -> Dict[str, Any]:
    filename = str(item.get("filename") or "attachment")[:255]
    mime = str(item.get("mime") or "application/octet-stream")[:100]
    b64 = item.get("data_base64") or ""
    try:
        data = base64.b64decode(b64, validate=True)
    except Exception as exc:  # noqa: BLE001
        raise BugReportError(422, f"attachment '{filename}' is not valid base64") from exc
    if not data:
        raise BugReportError(422, f"attachment '{filename}' is empty")
    if len(data) > MAX_ATTACHMENT_BYTES:
        raise BugReportError(422, f"attachment '{filename}' exceeds 4 MB")
    return {"filename": filename, "mime": mime, "size_bytes": len(data), "data": data}


def create(
    db: Session,
    user: Optional[models.User],
    text: str,
    source: Optional[str],
    attachments: Optional[List[Dict[str, Any]]],
) -> models.BugReport:
    text = (text or "").strip()
    if not text:
        raise BugReportError(422, "Report text is required")
    if len(text) > MAX_TEXT:
        raise BugReportError(422, f"Report text exceeds {MAX_TEXT} characters")
    if attachments and len(attachments) > MAX_ATTACHMENTS:
        raise BugReportError(422, f"At most {MAX_ATTACHMENTS} attachments are allowed")

    report = models.BugReport(
        user_id=user.id if user is not None else None,
        username=user.username if user is not None else "anonymous",
        source=(source or "web")[:20],
        text=text,
    )
    db.add(report)
    db.flush()
    for item in attachments or []:
        db.add(models.BugReportAttachment(bug_report_id=report.id, **_decode_attachment(item)))
    return report


def list_reports(db: Session) -> List[models.BugReport]:
    return db.query(models.BugReport).order_by(models.BugReport.created_at.desc()).all()


def resolve(
    db: Session,
    report: models.BugReport,
    user: models.User,
    status: Optional[str],
    note: Optional[str],
) -> models.BugReport:
    status = (status or STATUS_RESOLVED).upper()
    if status not in (STATUS_IN_PROGRESS, STATUS_RESOLVED):
        raise BugReportError(422, f"status must be one of {STATUS_IN_PROGRESS}, {STATUS_RESOLVED}")
    report.status = status
    if status == STATUS_RESOLVED:
        report.resolved_by = user.username
        report.resolved_at = _utcnow()
        report.resolution_note = (note or "").strip()[:MAX_TEXT] or None
    else:
        report.resolution_note = (note or "").strip()[:MAX_TEXT] or report.resolution_note
    return report
