"""FastAPI route definitions for ChildCareAI Admin Agent.

Defines REST API endpoints for:
- Chat session management
- Staff roster queries
- Communication drafting
- Approval workflows
"""

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from models.database import get_db
from models.schemas import (
    ChatRequest,
    ChatResponse,
    RosterQuery,
    RosterResponse,
    RosterEntryResponse,
    ApprovalRequest,
    ApprovalResponse,
)
from security.rbac import require_role
from security.audit import log_action, AuditAction
from security.approval import approve_token, reject_token
from orchestrator.agent import AgentOrchestrator
from tools.roster import get_available_staff

router = APIRouter(tags=["admin"])


def _get_user(request: Request) -> dict[str, Any]:
    """Extract authenticated user from request state."""
    user = getattr(request.state, "user", None)
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


@router.post("/chat", response_model=ChatResponse)
async def chat_endpoint(
    request: ChatRequest,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_role(["admin", "director", "educator"])),
) -> ChatResponse:
    """Process a chat message through the AI orchestrator."""
    agent = AgentOrchestrator(
        session_id=request.session_id,
        user_id=user["id"],
        user_role=user["role"],
        centre_id=user.get("centre_id", ""),
        db=db,
    )

    result = await agent.process_message(request.content)

    # Log the chat interaction
    await log_action(
        db=db,
        action=AuditAction.DATA_ACCESS,
        actor_id=user["id"],
        actor_role=user["role"],
        centre_id=user.get("centre_id", ""),
        details={"endpoint": "chat", "session_id": request.session_id},
        session_id=request.session_id,
        ip_address=http_request.client.host if http_request.client else None,
    )

    return ChatResponse(
        session_id=request.session_id,
        content=result["content"],
        tool_calls=[],  # Simplified — tool details are in the response text
        requires_approval=result.get("requires_approval", False),
        approval_token=result.get("approval_token"),
    )


@router.get("/roster", response_model=RosterResponse)
async def get_roster(
    date_filter: date | None = None,
    room_id: str | None = None,
    http_request: Request = None,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_role(["admin", "director", "educator", "readonly"])),
) -> RosterResponse:
    """Retrieve current staff roster information."""
    from sqlalchemy import select, and_
    from models.orm import RosterEntry, Staff, Room
    from datetime import date as date_type

    centre_id = user.get("centre_id", "")
    target_date = date_filter or date_type.today()

    stmt = select(RosterEntry).where(
        and_(
            RosterEntry.centre_id == centre_id,
            RosterEntry.date == target_date,
        )
    )
    if room_id:
        stmt = stmt.where(RosterEntry.room_id == room_id)

    result = await db.execute(stmt)
    entries = result.scalars().all()

    # Enrich with staff and room names
    response_entries = []
    for entry in entries:
        # Get staff name
        staff_result = await db.execute(
            select(Staff.first_name, Staff.last_name).where(Staff.id == entry.staff_id)
        )
        staff_row = staff_result.one_or_none()
        staff_name = f"{staff_row[0]} {staff_row[1]}" if staff_row else "Unknown"

        # Get room name
        room_result = await db.execute(
            select(Room.name).where(Room.id == entry.room_id)
        )
        room_name = room_result.scalar_one_or_none() or "Unknown"

        response_entries.append(RosterEntryResponse(
            id=entry.id,
            centre_id=entry.centre_id,
            staff_id=entry.staff_id,
            staff_name=staff_name,
            room_id=entry.room_id,
            room_name=room_name,
            shift_date=entry.date,
            shift_start=entry.shift_start,
            shift_end=entry.shift_end,
            shift_type=entry.shift_type.value if hasattr(entry.shift_type, 'value') else entry.shift_type,
            status=entry.status.value if hasattr(entry.status, 'value') else entry.status,
            approved_by=entry.approved_by,
            approved_at=entry.approved_at,
            created_at=entry.created_at,
        ))

    # Log the access
    await log_action(
        db=db,
        action=AuditAction.ROSTER_VIEW,
        actor_id=user["id"],
        actor_role=user["role"],
        centre_id=centre_id,
        details={"date": str(target_date), "room_id": room_id},
        ip_address=http_request.client.host if http_request and http_request.client else None,
    )

    return RosterResponse(
        entries=response_entries,
        roster_date=target_date,
        total_staff=len(response_entries),
    )


@router.post("/approvals/{token}/approve", response_model=ApprovalResponse)
async def approve_action(
    token: str,
    request: ApprovalRequest,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_role(["director"])),
) -> ApprovalResponse:
    """Approve a pending action via approval token."""
    result = await approve_token(
        db=db,
        token_id=token,
        approver_id=request.approver_id,
        approver_role=user["role"],
    )

    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Token not found, expired, or already consumed",
        )

    return ApprovalResponse(
        token=result["id"],
        status=result["status"],
        action_type=result["action_type"],
        processed_at=result.get("approved_at"),
    )


@router.post("/approvals/{token}/reject", response_model=ApprovalResponse)
async def reject_action(
    token: str,
    request: ApprovalRequest,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_role(["director"])),
) -> ApprovalResponse:
    """Reject a pending action via approval token."""
    result = await reject_token(
        db=db,
        token_id=token,
        rejector_id=request.approver_id,
        rejector_role=user["role"],
        reason=request.reason or "",
    )

    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Token not found, expired, or already consumed",
        )

    return ApprovalResponse(
        token=result["id"],
        status=result["status"],
        action_type=result["action_type"],
        processed_at=None,
    )


@router.get("/ratios")
async def check_ratios_endpoint(
    target_date: date | None = None,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_role(["admin", "director"])),
) -> dict[str, Any]:
    """Check staff-to-child ratios for all rooms."""
    from tools.ratios import check_ratios
    from datetime import date as date_type

    result = await check_ratios(
        db=db,
        centre_id=user.get("centre_id", ""),
        target_date=target_date or date_type.today(),
    )
    return result


# ─── Demo / Public Chat Endpoint ─────────────────────────────────────────────

# Session-scoped agent cache for HTTP stateless requests
_demo_agents: dict[str, AgentOrchestrator] = {}


@router.post("/demo/chat")
async def demo_chat_endpoint(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Open chat endpoint for the deployed demo website.

    Does NOT require JWT authentication — uses default demo user context.
    Protected by rate-limiting middleware instead.
    """
    body = await request.json()
    message = body.get("message", "").strip()
    session_id = body.get("session_id", "demo-session")

    if not message:
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    # Reuse or create agent for this session
    if session_id not in _demo_agents:
        _demo_agents[session_id] = AgentOrchestrator(
            session_id=session_id,
            user_id="demo-user",
            user_role="director",
            centre_id="centre_1",
            db=db,
        )
    else:
        _demo_agents[session_id].db = db

    agent = _demo_agents[session_id]
    result = await agent.process_message(message)

    return {
        "content": result["content"],
        "session_id": session_id,
        "tool_calls": [
            {"tool": tc["tool"], "result": tc["result"]}
            for tc in result.get("tool_calls", [])
        ],
        "requires_approval": result.get("requires_approval", False),
    }

