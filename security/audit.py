"""Audit trail logging for ChildCareAI Admin Agent.

Provides immutable audit logging for all significant actions performed
by the system. Compliant with childcare regulatory requirements
(7-year retention minimum).
"""

import json
import hashlib
from datetime import datetime, timezone
from typing import Any
from enum import Enum

from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession


class AuditAction(str, Enum):
    """Categories of auditable actions."""

    ROSTER_VIEW = "roster.view"
    ROSTER_MODIFY = "roster.modify"
    ROSTER_APPROVE = "roster.approve"
    STAFF_QUERY = "staff.query"
    COMMS_DRAFT = "comms.draft"
    COMMS_SEND = "comms.send"
    APPROVAL_REQUEST = "approval.request"
    APPROVAL_GRANTED = "approval.granted"
    APPROVAL_DENIED = "approval.denied"
    ESCALATION = "escalation"
    LOGIN = "auth.login"
    LOGOUT = "auth.logout"
    DATA_ACCESS = "data.access"
    DATA_EXPORT = "data.export"
    PII_ACCESS = "pii.access"
    RATIO_CHECK = "ratio.check"
    TOOL_EXECUTE = "tool.execute"


async def log_action(
    db: AsyncSession | None,
    action: AuditAction | str,
    actor_id: str,
    actor_role: str,
    centre_id: str = "",
    details: dict[str, Any] | None = None,
    target_id: str | None = None,
    target_type: str | None = None,
    ip_address: str | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Log an auditable action to the audit trail.

    Args:
        db: Async database session. If None, logs to stdout (fallback).
        action: The type of action being logged.
        actor_id: ID of the user performing the action.
        actor_role: Role of the user at time of action.
        centre_id: Centre the action belongs to.
        details: Additional context about the action.
        target_id: ID of the entity being acted upon.
        target_type: Type of the target entity.
        ip_address: Client IP address.
        session_id: Active session identifier.

    Returns:
        Dict containing the audit log entry with generated ID and timestamp.
    """
    from models.orm import AuditLog, ApprovalStatus

    action_val = action if isinstance(action, str) else action.value
    timestamp = datetime.now(timezone.utc)

    audit_entry = {
        "action": action_val,
        "actor_id": actor_id,
        "actor_role": actor_role,
        "centre_id": centre_id,
        "details": details or {},
        "target_id": target_id,
        "target_type": target_type,
        "ip_address": ip_address,
        "session_id": session_id,
        "timestamp": timestamp.isoformat(),
    }

    # Cryptographic hash for tamper detection
    entry_string = json.dumps(audit_entry, sort_keys=True, default=str)
    entry_hash = hashlib.sha256(entry_string.encode('utf-8')).hexdigest()

    if db is not None:
        log_record = AuditLog(
            staff_id=actor_id,
            role=actor_role,
            centre_id=centre_id or "system",
            action_type=action_val,
            data_accessed=json.dumps(details or {}),
            approval_status=ApprovalStatus.not_required,
            ip_address=ip_address,
            session_id=session_id,
            details={"hash": entry_hash, **(details or {})},
        )
        db.add(log_record)
        await db.flush()
        audit_entry["id"] = log_record.id
    else:
        # Fallback: print to stdout when no DB session is available
        import logging
        logging.getLogger("audit").warning(
            "No DB session for audit log: %s", json.dumps(audit_entry, default=str)
        )

    audit_entry["hash"] = entry_hash
    return audit_entry


async def query_audit_log(
    db: AsyncSession,
    centre_id: str,
    actor_id: str | None = None,
    action: str | None = None,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Query the audit log with filters.

    Args:
        db: Async database session.
        centre_id: Centre to query logs for (required for isolation).
        actor_id: Filter by actor.
        action: Filter by action type.
        start_date: Start of date range.
        end_date: End of date range.
        limit: Maximum number of entries to return.
        offset: Pagination offset.

    Returns:
        List of matching audit log entries.
    """
    from models.orm import AuditLog

    stmt = select(AuditLog).where(AuditLog.centre_id == centre_id)

    if actor_id:
        stmt = stmt.where(AuditLog.staff_id == actor_id)
    if action:
        stmt = stmt.where(AuditLog.action_type == action)
    if start_date:
        stmt = stmt.where(AuditLog.timestamp >= start_date)
    if end_date:
        stmt = stmt.where(AuditLog.timestamp <= end_date)

    stmt = stmt.order_by(desc(AuditLog.timestamp)).offset(offset).limit(limit)

    result = await db.execute(stmt)
    rows = result.scalars().all()

    return [
        {
            "id": row.id,
            "timestamp": row.timestamp.isoformat() if row.timestamp else None,
            "action": row.action_type,
            "actor_id": row.staff_id,
            "role": row.role,
            "details": row.details,
            "ip_address": row.ip_address,
            "session_id": row.session_id,
        }
        for row in rows
    ]
