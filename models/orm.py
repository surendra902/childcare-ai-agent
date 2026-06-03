"""SQLAlchemy ORM models for ChildCareAI Admin Agent.

Defines database table mappings for all domain entities including:
- Centres, Rooms, Staff
- Children, Parents, Consent records
- Roster entries and staff availability
- Observations (daily updates, learning stories)
- Chat sessions and messages
- Audit logs and approval tokens
"""

from __future__ import annotations

import enum
from datetime import date, datetime, time
from typing import Optional
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Table,
    Text,
    Time,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.database import Base


# ─── Enums ────────────────────────────────────────────────────────────────────


class StaffRole(str, enum.Enum):
    centre_manager = "centre_manager"
    room_leader = "room_leader"
    educator = "educator"
    administrator = "administrator"


class ShiftType(str, enum.Enum):
    AM = "AM"
    PM = "PM"
    FULL = "FULL"


class RosterStatus(str, enum.Enum):
    draft = "draft"
    approved = "approved"
    published = "published"


class ConsentType(str, enum.Enum):
    daily_observations = "daily_observations"
    photo_media = "photo_media"
    health_data_access = "health_data_access"
    newsletter_inclusion = "newsletter_inclusion"


class ObservationType(str, enum.Enum):
    daily_update = "daily_update"
    learning_story = "learning_story"
    incident = "incident"
    milestone = "milestone"


class ChatRole(str, enum.Enum):
    user = "user"
    assistant = "assistant"
    system = "system"


class ApprovalStatus(str, enum.Enum):
    not_required = "not_required"
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    expired = "expired"


# ─── Helper ───────────────────────────────────────────────────────────────────


def _uuid() -> str:
    return str(uuid4())


# ─── Association Table ────────────────────────────────────────────────────────


child_parent_association = Table(
    "child_parent",
    Base.metadata,
    Column("child_id", String(36), ForeignKey("children.id"), primary_key=True),
    Column("parent_id", String(36), ForeignKey("parents.id"), primary_key=True),
)


# ─── Models ───────────────────────────────────────────────────────────────────


class Centre(Base):
    """Childcare centre."""

    __tablename__ = "centres"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    address: Mapped[str] = mapped_column(String(500), nullable=False)
    phone: Mapped[str] = mapped_column(String(50), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    # Relationships
    rooms: Mapped[list["Room"]] = relationship(back_populates="centre", cascade="all, delete-orphan")
    staff: Mapped[list["Staff"]] = relationship(back_populates="centre", cascade="all, delete-orphan")
    children: Mapped[list["Child"]] = relationship(back_populates="centre", cascade="all, delete-orphan")
    parents: Mapped[list["Parent"]] = relationship(back_populates="centre", cascade="all, delete-orphan")
    roster_entries: Mapped[list["RosterEntry"]] = relationship(back_populates="centre", cascade="all, delete-orphan")
    observations: Mapped[list["Observation"]] = relationship(back_populates="centre", cascade="all, delete-orphan")
    chat_sessions: Mapped[list["ChatSession"]] = relationship(back_populates="centre", cascade="all, delete-orphan")

    approval_tokens: Mapped[list["ApprovalToken"]] = relationship(back_populates="centre", cascade="all, delete-orphan")


class Room(Base):
    """A room within a centre (e.g., babies, toddlers, preschool)."""

    __tablename__ = "rooms"
    __table_args__ = (
        Index("ix_rooms_centre_id", "centre_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    centre_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("centres.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    capacity: Mapped[int] = mapped_column(Integer, nullable=False)
    age_group: Mapped[str] = mapped_column(String(50), nullable=False)  # babies, toddlers, preschool
    required_ratio: Mapped[str] = mapped_column(String(10), nullable=False)  # e.g. "1:4"
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Relationships
    centre: Mapped["Centre"] = relationship(back_populates="rooms")
    staff: Mapped[list["Staff"]] = relationship(back_populates="assigned_room")
    children: Mapped[list["Child"]] = relationship(back_populates="room")
    roster_entries: Mapped[list["RosterEntry"]] = relationship(back_populates="room")
    observations: Mapped[list["Observation"]] = relationship(back_populates="room")


class Staff(Base):
    """Staff member record."""

    __tablename__ = "staff"
    __table_args__ = (
        Index("ix_staff_centre_id", "centre_id"),
        Index("ix_staff_assigned_room_id", "assigned_room_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    centre_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("centres.id"), nullable=False
    )
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    phone: Mapped[Optional[str]] = mapped_column(String(50))
    role: Mapped[StaffRole] = mapped_column(Enum(StaffRole), nullable=False)
    assigned_room_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("rooms.id"), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    contracted_hours: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    # Relationships
    centre: Mapped["Centre"] = relationship(back_populates="staff")
    assigned_room: Mapped[Optional["Room"]] = relationship(back_populates="staff")
    roster_entries: Mapped[list["RosterEntry"]] = relationship(
        back_populates="staff", foreign_keys="[RosterEntry.staff_id]"
    )
    approved_rosters: Mapped[list["RosterEntry"]] = relationship(
        back_populates="approver", foreign_keys="[RosterEntry.approved_by]"
    )
    observations: Mapped[list["Observation"]] = relationship(back_populates="staff")
    chat_sessions: Mapped[list["ChatSession"]] = relationship(back_populates="staff")
    availability: Mapped[list["StaffAvailability"]] = relationship(back_populates="staff")



class Child(Base):
    """Child enrolled at a centre."""

    __tablename__ = "children"
    __table_args__ = (
        Index("ix_children_centre_id", "centre_id"),
        Index("ix_children_room_id", "room_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    centre_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("centres.id"), nullable=False
    )
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    date_of_birth: Mapped[date] = mapped_column(Date, nullable=False)
    room_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("rooms.id"), nullable=True
    )
    enrolment_date: Mapped[date] = mapped_column(Date, nullable=False)
    medical_info_encrypted: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    allergies_encrypted: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    custody_notes_encrypted: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    special_needs_encrypted: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    # Relationships
    centre: Mapped["Centre"] = relationship(back_populates="children")
    room: Mapped[Optional["Room"]] = relationship(back_populates="children")
    parents: Mapped[list["Parent"]] = relationship(
        secondary=child_parent_association, back_populates="children"
    )
    observations: Mapped[list["Observation"]] = relationship(back_populates="child")
    consent_records: Mapped[list["ConsentRecord"]] = relationship(back_populates="child")


class Parent(Base):
    """Parent or guardian of a child."""

    __tablename__ = "parents"
    __table_args__ = (
        Index("ix_parents_centre_id", "centre_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    centre_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("centres.id"), nullable=False
    )
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str] = mapped_column(String(50), nullable=False)
    address: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    relationship_to_child: Mapped[str] = mapped_column(String(50), nullable=False)
    is_primary_contact: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    # Relationships
    centre: Mapped["Centre"] = relationship(back_populates="parents")
    children: Mapped[list["Child"]] = relationship(
        secondary=child_parent_association, back_populates="parents"
    )
    consent_records: Mapped[list["ConsentRecord"]] = relationship(back_populates="granting_parent")


class ConsentRecord(Base):
    """Consent granted by a parent for a child."""

    __tablename__ = "consent_records"
    __table_args__ = (
        Index("ix_consent_records_child_id", "child_id"),
        Index("ix_consent_records_parent_id", "parent_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    child_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("children.id"), nullable=False
    )
    parent_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("parents.id"), nullable=False
    )
    consent_type: Mapped[ConsentType] = mapped_column(Enum(ConsentType), nullable=False)
    is_granted: Mapped[bool] = mapped_column(Boolean, default=True)
    granted_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    expiry_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relationships
    child: Mapped["Child"] = relationship(back_populates="consent_records")
    granting_parent: Mapped["Parent"] = relationship(back_populates="consent_records")



class RosterEntry(Base):
    """Roster shift assignment for a staff member."""

    __tablename__ = "roster_entries"
    __table_args__ = (
        Index("ix_roster_entries_centre_id", "centre_id"),
        Index("ix_roster_entries_staff_id", "staff_id"),
        Index("ix_roster_entries_room_id", "room_id"),
        Index("ix_roster_entries_date", "date"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    centre_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("centres.id"), nullable=False
    )
    staff_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("staff.id"), nullable=False
    )
    room_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("rooms.id"), nullable=False
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)
    shift_start: Mapped[time] = mapped_column(Time, nullable=False)
    shift_end: Mapped[time] = mapped_column(Time, nullable=False)
    shift_type: Mapped[ShiftType] = mapped_column(Enum(ShiftType), nullable=False)
    status: Mapped[RosterStatus] = mapped_column(
        Enum(RosterStatus), nullable=False, default=RosterStatus.draft
    )
    approved_by: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("staff.id"), nullable=True
    )
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    # Relationships
    centre: Mapped["Centre"] = relationship(back_populates="roster_entries")
    staff: Mapped["Staff"] = relationship(
        back_populates="roster_entries", foreign_keys=[staff_id]
    )
    room: Mapped["Room"] = relationship(back_populates="roster_entries")
    approver: Mapped[Optional["Staff"]] = relationship(
        back_populates="approved_rosters", foreign_keys=[approved_by]
    )


class Observation(Base):
    """Observation record for a child (daily updates, incidents, milestones)."""

    __tablename__ = "observations"
    __table_args__ = (
        Index("ix_observations_child_id", "child_id"),
        Index("ix_observations_staff_id", "staff_id"),
        Index("ix_observations_centre_id", "centre_id"),
        Index("ix_observations_room_id", "room_id"),
        Index("ix_observations_date", "observation_date"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    child_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("children.id"), nullable=False
    )
    staff_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("staff.id"), nullable=False
    )
    centre_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("centres.id"), nullable=False
    )
    room_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("rooms.id"), nullable=False
    )
    observation_date: Mapped[date] = mapped_column(Date, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    observation_type: Mapped[ObservationType] = mapped_column(
        Enum(ObservationType), nullable=False
    )
    is_shared_with_parents: Mapped[bool] = mapped_column(Boolean, default=False)
    shared_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    # Relationships
    child: Mapped["Child"] = relationship(back_populates="observations")
    staff: Mapped["Staff"] = relationship(back_populates="observations")
    centre: Mapped["Centre"] = relationship(back_populates="observations")
    room: Mapped["Room"] = relationship(back_populates="observations")


class ChatSession(Base):
    """Chat session between staff and the AI assistant."""

    __tablename__ = "chat_sessions"
    __table_args__ = (
        Index("ix_chat_sessions_staff_id", "staff_id"),
        Index("ix_chat_sessions_centre_id", "centre_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    staff_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("staff.id"), nullable=False
    )
    centre_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("centres.id"), nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    message_count: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Relationships
    staff: Mapped["Staff"] = relationship(back_populates="chat_sessions")
    centre: Mapped["Centre"] = relationship(back_populates="chat_sessions")
    messages: Mapped[list["ChatMessage"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )



class ChatMessage(Base):
    """Individual message within a chat session."""

    __tablename__ = "chat_messages"
    __table_args__ = (
        Index("ix_chat_messages_session_id", "session_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("chat_sessions.id"), nullable=False
    )
    role: Mapped[ChatRole] = mapped_column(Enum(ChatRole), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    tool_calls: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    # Relationships
    session: Mapped["ChatSession"] = relationship(back_populates="messages")


class AuditLog(Base):
    """Immutable audit log entry for compliance tracking."""

    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_staff_id", "staff_id"),
        Index("ix_audit_logs_centre_id", "centre_id"),
        Index("ix_audit_logs_timestamp", "timestamp"),
        Index("ix_audit_logs_session_id", "session_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    staff_id: Mapped[str] = mapped_column(
        String(36), nullable=False
    )
    role: Mapped[str] = mapped_column(String(50), nullable=False)
    centre_id: Mapped[str] = mapped_column(
        String(36), nullable=False
    )
    action_type: Mapped[str] = mapped_column(String(50), nullable=False)
    data_accessed: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    approval_status: Mapped[ApprovalStatus] = mapped_column(
        Enum(ApprovalStatus), nullable=False, default=ApprovalStatus.not_required
    )
    approver_id: Mapped[Optional[str]] = mapped_column(
        String(36), nullable=True
    )
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    session_id: Mapped[Optional[str]] = mapped_column(
        String(36), nullable=True
    )
    details: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)


class ApprovalToken(Base):
    """Stored approval token for pending high-risk actions."""

    __tablename__ = "approval_tokens"
    __table_args__ = (
        Index("ix_approval_tokens_staff_id", "staff_id"),
        Index("ix_approval_tokens_centre_id", "centre_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    action_type: Mapped[str] = mapped_column(String(50), nullable=False)
    action_payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    staff_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("staff.id"), nullable=False
    )
    centre_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("centres.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    is_consumed: Mapped[bool] = mapped_column(Boolean, default=False)
    consumed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    consumed_by: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("staff.id"), nullable=True
    )

    # Relationships
    centre: Mapped["Centre"] = relationship(back_populates="approval_tokens")


class StaffAvailability(Base):
    """Staff availability or leave record."""

    __tablename__ = "staff_availability"
    __table_args__ = (
        Index("ix_staff_availability_staff_id", "staff_id"),
        Index("ix_staff_availability_date", "date"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    staff_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("staff.id"), nullable=False
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)
    is_available: Mapped[bool] = mapped_column(Boolean, default=True)
    reason: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    # Relationships
    staff: Mapped["Staff"] = relationship(back_populates="availability")
