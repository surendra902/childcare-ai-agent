"""Staffing tools for ChildCareAI Admin Agent.

Provides functions for finding replacement cover when staff are unavailable:
- find_cover: Locate available staff to cover a shift gap
"""

from datetime import date, time
from typing import Any

from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from models.orm import Staff, StaffAvailability, RosterEntry, Room


async def find_cover(
    db: AsyncSession,
    centre_id: str,
    target_date: date,
    room: str,
    shift_start: time,
    shift_end: time,
    absent_staff_id: str | None = None,
    preferred_qualifications: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Find available cover staff for a shift gap.

    Ranks candidates by suitability:
    1. Staff assigned to the same room (most familiar)
    2. Staff who have previously been rostered to the room
    3. Any other available staff

    Args:
        db: Async database session.
        centre_id: Centre to scope the query to.
        target_date: Date the cover is needed.
        room: Room name requiring cover.
        shift_start: Start time of the shift to cover.
        shift_end: End time of the shift to cover.
        absent_staff_id: ID of the absent staff member (excluded from results).
        preferred_qualifications: Preferred qualifications for cover staff.

    Returns:
        List of cover options ranked by suitability.
    """
    # Find the room record
    room_result = await db.execute(
        select(Room).where(
            and_(Room.centre_id == centre_id, Room.name == room)
        )
    )
    room_record = room_result.scalar_one_or_none()
    if not room_record:
        return []

    # Get staff who are unavailable on the target date
    unavailable_result = await db.execute(
        select(StaffAvailability.staff_id).where(
            and_(
                StaffAvailability.date == target_date,
                StaffAvailability.is_available == False,
            )
        )
    )
    unavailable_ids = set(unavailable_result.scalars().all())

    # Get staff who are already rostered at overlapping times
    rostered_result = await db.execute(
        select(RosterEntry.staff_id).where(
            and_(
                RosterEntry.date == target_date,
                RosterEntry.shift_start < shift_end,
                RosterEntry.shift_end > shift_start,
            )
        )
    )
    rostered_ids = set(rostered_result.scalars().all())

    # Exclude absent staff
    exclude_ids = unavailable_ids | rostered_ids
    if absent_staff_id:
        exclude_ids.add(absent_staff_id)

    # Get all active staff in the centre
    staff_result = await db.execute(
        select(Staff).where(
            and_(
                Staff.centre_id == centre_id,
                Staff.is_active == True,
                Staff.id.notin_(exclude_ids) if exclude_ids else True,
            )
        )
    )
    candidates = staff_result.scalars().all()

    # Count previous shifts in this room for familiarity scoring
    prev_shifts = {}
    for candidate in candidates:
        shift_count_result = await db.execute(
            select(func.count()).select_from(RosterEntry).where(
                and_(
                    RosterEntry.staff_id == candidate.id,
                    RosterEntry.room_id == room_record.id,
                )
            )
        )
        prev_shifts[candidate.id] = shift_count_result.scalar() or 0

    # Score and rank candidates
    cover_options = []
    for candidate in candidates:
        familiarity = prev_shifts.get(candidate.id, 0)

        # Suitability score: assigned to room > familiar > unknown
        if candidate.assigned_room_id == room_record.id:
            score = 1.0
            notes = "Assigned to this room"
        elif familiarity > 0:
            score = min(0.5 + (familiarity * 0.05), 0.9)
            notes = f"Previously rostered {familiarity} times in this room"
        else:
            score = 0.3
            notes = "Available but unfamiliar with this room"

        cover_options.append({
            "staff_id": candidate.id,
            "name": f"{candidate.first_name} {candidate.last_name}",
            "role": candidate.role.value if hasattr(candidate.role, 'value') else candidate.role,
            "suitability_score": round(score, 2),
            "notes": notes,
        })

    # Sort by suitability score descending
    cover_options.sort(key=lambda x: x["suitability_score"], reverse=True)
    return cover_options
