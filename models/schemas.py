"""Pydantic schemas for API request/response validation.

Defines all data transfer objects used by the API endpoints and WebSocket handlers.
Uses Pydantic v2 model_config for serialization settings.
"""


from datetime import date, datetime, time
from typing import Any, Optional

from pydantic import BaseModel, Field, ConfigDict


# ─── Staff Schemas ────────────────────────────────────────────────────────────


class StaffBrief(BaseModel):
    """Brief staff summary for lists and dropdowns."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    first_name: str
    last_name: str
    role: str
    assigned_room_id: Optional[str] = None
    room_name: Optional[str] = None

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"


class StaffResponse(BaseModel):
    """Full staff detail response."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    centre_id: str
    first_name: str
    last_name: str
    email: str
    phone: Optional[str] = None
    role: str
    assigned_room_id: Optional[str] = None
    is_active: bool
    contracted_hours: Optional[float] = None
    created_at: datetime


# ─── Roster Schemas ───────────────────────────────────────────────────────────


class RosterEntryResponse(BaseModel):
    """Roster entry response with staff and room details."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    centre_id: str
    staff_id: str
    staff_name: Optional[str] = None
    room_id: str
    room_name: Optional[str] = None
    shift_date: date
    shift_start: time
    shift_end: time
    shift_type: str
    status: str
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None
    created_at: datetime


class RosterDraftRequest(BaseModel):
    """Request to create a draft roster entry."""

    staff_id: str = Field(..., description="Staff member to assign")
    room_id: str = Field(..., description="Room for the shift")
    shift_date: date = Field(..., description="Date of the shift")
    shift_start: time = Field(..., description="Shift start time")
    shift_end: time = Field(..., description="Shift end time")
    shift_type: str = Field(..., pattern="^(AM|PM|FULL)$", description="Shift type")


# ─── Availability / Cover Schemas ────────────────────────────────────────────


class AvailableStaffQuery(BaseModel):
    """Query parameters for finding available staff."""

    target_date: date = Field(..., description="Date to check availability")
    shift_type: Optional[str] = Field(
        None, pattern="^(AM|PM|FULL)$", description="Shift type filter"
    )
    room_id: Optional[str] = Field(None, description="Room preference filter")


class CoverRequest(BaseModel):
    """Request to find cover for an absent staff member."""

    absent_staff_id: str = Field(..., description="ID of the absent staff member")
    target_date: date = Field(..., description="Date cover is needed")


class CoverOption(BaseModel):
    """A potential cover option for a shift gap."""

    staff: StaffBrief
    suitability_score: float = Field(ge=0.0, le=1.0)
    reason: str = ""
    conflicts: list[str] = Field(default_factory=list)


# ─── Communication Schemas ───────────────────────────────────────────────────


class ParentMessageRequest(BaseModel):
    """Request to draft a parent communication."""

    child_id: str = Field(..., description="Child the message is about")
    message_type: str = Field(
        ...,
        description="Type of message (daily_update, incident_report, general, event_invite)",
    )
    context: Optional[str] = Field(None, description="Additional context for the message")
    tone: str = Field(default="warm_professional", description="Desired tone")


class NewsletterRequest(BaseModel):
    """Request to generate a room newsletter."""

    room_id: str = Field(..., description="Room to generate newsletter for")
    period: str = Field(
        ..., description="Period to cover (e.g., 'this_week', 'last_fortnight')"
    )
    highlights: Optional[list[str]] = Field(
        None, description="Specific highlights to include"
    )


# ─── Escalation Schema ───────────────────────────────────────────────────────


class EscalationRequest(BaseModel):
    """Request to escalate an issue to management."""

    issue_summary: str = Field(..., min_length=10, max_length=1000)
    urgency: str = Field(
        ..., pattern="^(low|medium|high|critical)$", description="Urgency level"
    )
    related_child_id: Optional[str] = None
    related_staff_id: Optional[str] = None


# ─── Chat Schemas ─────────────────────────────────────────────────────────────


class ChatMessageRequest(BaseModel):
    """Incoming chat message from the staff panel."""

    session_id: str = Field(..., description="Active chat session identifier")
    content: str = Field(..., min_length=1, max_length=2000, description="User message")
    context: Optional[dict[str, Any]] = Field(
        default=None, description="Optional context (current page, selected staff, etc.)"
    )


class ToolCallResult(BaseModel):
    """Result of a tool call executed by the agent."""

    tool_name: str
    arguments: dict[str, Any]
    result: dict[str, Any]
    requires_approval: bool = False
    approval_token: Optional[str] = None


class ChatMessageResponse(BaseModel):
    """Response from the AI agent."""

    session_id: str
    content: str = Field(..., description="Agent's text response")
    tool_calls: list[ToolCallResult] = Field(default_factory=list)
    requires_approval: bool = False
    approval_token: Optional[str] = None


# ─── Approval Schemas ─────────────────────────────────────────────────────────


class ActionConfirmation(BaseModel):
    """Confirmation or rejection of a pending action."""

    token_id: str = Field(..., description="The approval token ID")
    approved: bool = Field(..., description="Whether the action is approved")
    reason: Optional[str] = Field(None, description="Optional reason for decision")


class ApprovalCardResponse(BaseModel):
    """Card shown to approver for a pending action."""

    model_config = ConfigDict(from_attributes=True)

    token_id: str
    action_type: str
    action_summary: str
    expires_at: datetime
    requested_by: Optional[str] = None
    created_at: Optional[datetime] = None


# ─── Audit Schemas ────────────────────────────────────────────────────────────


class AuditLogResponse(BaseModel):
    """Audit log entry response."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    timestamp: datetime
    staff_id: str
    role: str
    centre_id: str
    action_type: str
    data_accessed: Optional[str] = None
    approval_status: str
    approver_id: Optional[str] = None
    ip_address: Optional[str] = None
    session_id: Optional[str] = None
    details: Optional[dict[str, Any]] = None


# ─── Legacy compatibility aliases ────────────────────────────────────────────

# These maintain backward compatibility with existing code that may reference
# the original schema names.
ChatRequest = ChatMessageRequest
ChatResponse = ChatMessageResponse
StaffMember = StaffBrief
RosterEntry = RosterEntryResponse
RosterQuery = AvailableStaffQuery


class RosterResponse(BaseModel):
    """Response containing roster data."""

    entries: list[RosterEntryResponse] = Field(default_factory=list)
    roster_date: Optional[date] = None
    total_staff: int = 0


class ApprovalRequest(BaseModel):
    """Request body for approval/rejection actions (legacy)."""

    approver_id: str
    reason: Optional[str] = None


class ApprovalResponse(BaseModel):
    """Response after processing an approval/rejection (legacy)."""

    token: str
    status: str
    action_type: str
    processed_at: Optional[datetime] = None


class DraftMessageRequest(BaseModel):
    """Request to draft a parent message (legacy)."""

    recipient_name: str
    subject: str
    context: str
    tone: str = "warm_professional"


class DraftMessageResponse(BaseModel):
    """Response containing a drafted message (legacy)."""

    subject: str
    body: str
    requires_approval: bool = False
    approval_token: Optional[str] = None
