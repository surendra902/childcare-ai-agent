"""Escalation tools for ChildCareAI Admin Agent.

Provides functions for escalating actions that require director approval:
- escalate_to_director: Create an approval request for sensitive actions
"""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from security.approval import generate_approval_token


async def escalate_to_director(
    db: AsyncSession,
    centre_id: str,
    action_type: str,
    description: str,
    context: dict[str, Any],
    urgency: str = "normal",
    requested_by: str | None = None,
    actor_role: str = "unknown",
) -> dict[str, Any]:
    """Escalate an action to the centre director for approval.

    Used when the AI agent determines an action requires human oversight,
    such as:
    - Roster changes affecting ratios
    - Sending communications about sensitive topics
    - Accessing restricted staff information
    - Any action flagged by guardrails

    Args:
        db: Async database session.
        centre_id: Centre the action belongs to.
        action_type: Type of action requiring approval.
        description: Human-readable description of what is being requested.
        context: Structured context data relevant to the decision.
        urgency: Urgency level ("low", "normal", "high", "critical").
        requested_by: Staff member who initiated the request.
        actor_role: Role of the requesting user.

    Returns:
        Dict with 'approval_token', 'status', and 'expires_at' keys.
    """
    approval = await generate_approval_token(
        db=db,
        action_type=action_type,
        action_details={"description": description, "context": context, "urgency": urgency},
        requested_by=requested_by or "system",
        centre_id=centre_id,
        actor_role=actor_role,
    )

    return {
        "approval_token": approval["token"],
        "status": approval["status"],
        "expires_at": approval["expires_at"],
        "action_type": action_type,
        "description": description,
    }
