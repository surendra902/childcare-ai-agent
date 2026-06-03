"""Roster management tools for ChildCareAI Admin Agent.

Provides functions for querying and managing staff rosters:
- get_available_staff: Query available staff for a given date/time/room
- draft_roster: Generate a draft roster based on constraints
"""

from datetime import date, time, datetime
from typing import Any

from sqlalchemy import select, and_, not_
from sqlalchemy.ext.asyncio import AsyncSession

from models.orm import Staff, StaffAvailability, RosterEntry, Room, StaffRole


async def get_available_staff(
    db: AsyncSession,
    centre_id: str,
    target_date: date,
    room: str | None = None,
    shift_time: time | None = None,
    qualifications: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Query available staff members for a given date and optional filters.

    Args:
        db: Async database session.
        centre_id: Centre to scope the query to.
        target_date: The date to check availability for.
        room: Optional room name filter.
        shift_time: Optional specific shift time to check.
        qualifications: Optional required qualifications filter.

    Returns:
        List of available staff dicts with id, name, role, room info.
    """
    # Get staff who are NOT marked unavailable on the target date
    unavailable_subq = (
        select(StaffAvailability.staff_id)
        .where(
            and_(
                StaffAvailability.date == target_date,
                StaffAvailability.is_available == False,
            )
        )
        .subquery()
    )

    # Get staff who are already rostered on the target date
    rostered_subq = (
        select(RosterEntry.staff_id)
        .where(RosterEntry.date == target_date)
        .subquery()
    )

    stmt = (
        select(Staff)
        .where(
            and_(
                Staff.centre_id == centre_id,
                Staff.is_active == True,
                Staff.id.notin_(select(unavailable_subq.c.staff_id)),
            )
        )
    )

    # Optionally filter by room assignment
    if room:
        room_result = await db.execute(
            select(Room.id).where(
                and_(Room.centre_id == centre_id, Room.name == room)
            )
        )
        room_id = room_result.scalar_one_or_none()
        if room_id:
            stmt = stmt.where(Staff.assigned_room_id == room_id)

    result = await db.execute(stmt)
    staff_list = result.scalars().all()

    # Check which staff are already rostered (to flag them)
    rostered_result = await db.execute(
        select(RosterEntry.staff_id).where(RosterEntry.date == target_date)
    )
    rostered_ids = {row for row in rostered_result.scalars().all()}

    output = []
    for s in staff_list:
        output.append({
            "id": s.id,
            "name": f"{s.first_name} {s.last_name}",
            "role": s.role.value if isinstance(s.role, StaffRole) else s.role,
            "room_id": s.assigned_room_id,
            "contracted_hours": s.contracted_hours,
            "already_rostered": s.id in rostered_ids,
        })

    return output


async def draft_roster(
    db: AsyncSession,
    centre_id: str,
    target_date: date,
    rooms: list[str] | None = None,
    constraints: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Generate a draft roster for a given date across specified rooms.

    Args:
        db: Async database session.
        centre_id: Centre to scope the query to.
        target_date: The date to generate roster for.
        rooms: List of room names to staff. If None, all active rooms.
        constraints: Optional constraints (min staff per room, etc.)

    Returns:
        List of draft roster entries (staff-to-room-to-shift assignments).
    """
    # Get rooms
    room_stmt = select(Room).where(
        and_(Room.centre_id == centre_id, Room.is_active == True)
    )
    if rooms:
        room_stmt = room_stmt.where(Room.name.in_(rooms))
    room_result = await db.execute(room_stmt)
    room_list = room_result.scalars().all()

    # Get available staff
    available = await get_available_staff(db, centre_id, target_date)
    available_staff = [s for s in available if not s["already_rostered"]]

    draft_entries = []
    staff_idx = 0

    for room in room_list:
        # Parse required ratio (e.g., "1:4" means 1 staff per 4 children)
        ratio_parts = room.required_ratio.split(":")
        staff_needed = max(1, int(ratio_parts[0])) if len(ratio_parts) == 2 else 1

        assigned = 0
        while assigned < staff_needed and staff_idx < len(available_staff):
            staff = available_staff[staff_idx]
            draft_entries.append({
                "staff_id": staff["id"],
                "staff_name": staff["name"],
                "room_id": room.id,
                "room_name": room.name,
                "date": target_date.isoformat(),
                "shift_start": "07:00",
                "shift_end": "15:00",
                "shift_type": "FULL",
                "status": "draft",
            })
            staff_idx += 1
            assigned += 1

    return draft_entries
