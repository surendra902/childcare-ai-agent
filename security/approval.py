"""Approval token management for ChildCareAI Admin Agent.

Manages time-limited approval tokens for actions requiring director sign-off.
Tokens are cryptographically secure, single-use, and expire after a configurable period.
Persisted to database for durability across restarts.
"""

import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from security.audit import log_action, AuditAction


async def generate_approval_token(
    db: AsyncSession,
    action_type: str,
    action_details: dict[str, Any],
    requested_by: str,
    centre_id: str,
    actor_role: str = "unknown",
    approved_by_role: str = "director",
) -> dict[str, Any]:
    """Generate a time-limited approval token for a pending action.

    Args:
        db: Async database session.
        action_type: Type of action requiring approval.
        action_details: Full details of the action to be approved.
        requested_by: ID of the staff member requesting the action.
        centre_id: Centre the action belongs to.
        actor_role: Role of the requesting user.
        approved_by_role: Role required to approve (default: director).

    Returns:
        Dict with token, expiry, and action metadata.
    """
    from models.orm import ApprovalToken

    token_value = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(
        minutes=settings.APPROVAL_TOKEN_EXPIRY_MINUTES
    )

    token_record = ApprovalToken(
        action_type=action_type,
        action_payload={
            "details": action_details,
            "approved_by_role": approved_by_role,
        },
        staff_id=requested_by,
        centre_id=centre_id,
        expires_at=expires_at,
    )
    db.add(token_record)
    await db.flush()

    # Log approval request
    await log_action(
        db=db,
        action=AuditAction.APPROVAL_REQUEST,
        actor_id=requested_by,
        actor_role=actor_role,
        centre_id=centre_id,
        details={"action_type": action_type},
        target_id=token_record.id,
        target_type="approval_token",
    )

    return {
        "token": token_record.id,
        "expires_at": expires_at.isoformat(),
        "action_type": action_type,
        "status": "pending",
    }


async def validate_token(db: AsyncSession, token_id: str) -> dict[str, Any] | None:
    """Validate an approval token and return its associated action.

    Args:
        db: Async database session.
        token_id: The approval token ID to validate.

    Returns:
        Dict with token data if valid, None if expired/consumed/not found.
    """
    from models.orm import ApprovalToken

    result = await db.execute(
        select(ApprovalToken).where(ApprovalToken.id == token_id)
    )
    record = result.scalar_one_or_none()

    if record is None:
        return None

    # Check expiry
    if datetime.now(timezone.utc) > record.expires_at:
        return None

    # Check if already consumed
    if record.is_consumed:
        return None

    return {
        "id": record.id,
        "action_type": record.action_type,
        "action_payload": record.action_payload,
        "staff_id": record.staff_id,
        "centre_id": record.centre_id,
        "expires_at": record.expires_at.isoformat(),
    }


async def approve_token(
    db: AsyncSession, token_id: str, approver_id: str, approver_role: str = "director"
) -> dict[str, Any] | None:
    """Mark an approval token as approved.

    Args:
        db: Async database session.
        token_id: The approval token ID to approve.
        approver_id: ID of the staff member granting approval.
        approver_role: Role of the approver.

    Returns:
        Updated token data, or None if token invalid.
    """
    from models.orm import ApprovalToken

    record_data = await validate_token(db, token_id)
    if record_data is None:
        return None

    result = await db.execute(
        select(ApprovalToken).where(ApprovalToken.id == token_id)
    )
    record = result.scalar_one()

    record.is_consumed = True
    record.consumed_at = datetime.now(timezone.utc)
    record.consumed_by = approver_id
    await db.flush()

    # Log approval granted
    await log_action(
        db=db,
        action=AuditAction.APPROVAL_GRANTED,
        actor_id=approver_id,
        actor_role=approver_role,
        centre_id=record.centre_id,
        details={"action_type": record.action_type},
        target_id=token_id,
        target_type="approval_token",
    )

    return {
        "id": record.id,
        "action_type": record.action_type,
        "status": "approved",
        "approved_by": approver_id,
        "approved_at": record.consumed_at.isoformat(),
    }


async def reject_token(
    db: AsyncSession,
    token_id: str,
    rejector_id: str,
    rejector_role: str = "director",
    reason: str = "",
) -> dict[str, Any] | None:
    """Mark an approval token as rejected.

    Args:
        db: Async database session.
        token_id: The approval token ID to reject.
        rejector_id: ID of the staff member rejecting.
        rejector_role: Role of the rejector.
        reason: Optional reason for rejection.

    Returns:
        Updated token data, or None if token invalid.
    """
    from models.orm import ApprovalToken

    record_data = await validate_token(db, token_id)
    if record_data is None:
        return None

    result = await db.execute(
        select(ApprovalToken).where(ApprovalToken.id == token_id)
    )
    record = result.scalar_one()

    record.is_consumed = True
    record.consumed_at = datetime.now(timezone.utc)
    record.consumed_by = rejector_id
    # Store rejection reason in the payload
    payload = record.action_payload or {}
    payload["rejection_reason"] = reason
    record.action_payload = payload
    await db.flush()

    # Log approval denied
    await log_action(
        db=db,
        action=AuditAction.APPROVAL_DENIED,
        actor_id=rejector_id,
        actor_role=rejector_role,
        centre_id=record.centre_id,
        details={"action_type": record.action_type, "reason": reason},
        target_id=token_id,
        target_type="approval_token",
    )

    return {
        "id": record.id,
        "action_type": record.action_type,
        "status": "rejected",
        "rejected_by": rejector_id,
        "rejection_reason": reason,
    }
