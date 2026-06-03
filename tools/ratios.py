"""Ratio-checking tools for ChildCareAI Admin Agent.

Provides functions for checking staff-to-child ratios:
- check_ratios: Compare rostered staff per room against required ratios
"""

from datetime import date
from typing import Any

from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from models.orm import Room, Child, RosterEntry


async def check_ratios(
    db: AsyncSession,
    centre_id: str,
    target_date: date,
) -> dict[str, Any]:
    """Check staff-to-child ratios for all rooms on a given date.

    Compares the number of rostered staff per room against:
    - The room's required ratio (e.g., "1:4" = 1 staff per 4 children)
    - The number of active children enrolled in that room

    Args:
        db: Async database session.
        centre_id: Centre to check ratios for.
        target_date: Date to check ratios on.

    Returns:
        Dict with overall compliance status and per-room breakdown.
    """
    # Get all active rooms for the centre
    room_result = await db.execute(
        select(Room).where(
            and_(Room.centre_id == centre_id, Room.is_active == True)
        )
    )
    rooms = room_result.scalars().all()

    room_reports = []
    has_breach = False

    for room in rooms:
        # Count enrolled children in the room
        child_count_result = await db.execute(
            select(func.count()).select_from(Child).where(
                and_(
                    Child.room_id == room.id,
                    Child.is_active == True,
                )
            )
        )
        child_count = child_count_result.scalar() or 0

        # Count rostered staff for this room on the target date
        staff_count_result = await db.execute(
            select(func.count()).select_from(RosterEntry).where(
                and_(
                    RosterEntry.room_id == room.id,
                    RosterEntry.date == target_date,
                )
            )
        )
        staff_count = staff_count_result.scalar() or 0

        # Parse required ratio (e.g., "1:4")
        ratio_parts = room.required_ratio.split(":")
        if len(ratio_parts) == 2:
            staff_per = int(ratio_parts[0])
            children_per = int(ratio_parts[1])
        else:
            staff_per, children_per = 1, 4  # Default fallback

        # Calculate required staff
        if child_count > 0:
            required_staff = max(1, -(-child_count * staff_per // children_per))  # Ceiling division
        else:
            required_staff = 0

        is_compliant = staff_count >= required_staff
        if not is_compliant and child_count > 0:
            has_breach = True

        room_reports.append({
            "room_id": room.id,
            "room_name": room.name,
            "age_group": room.age_group,
            "required_ratio": room.required_ratio,
            "children_enrolled": child_count,
            "staff_rostered": staff_count,
            "staff_required": required_staff,
            "compliant": is_compliant,
            "gap": max(0, required_staff - staff_count),
        })

    return {
        "date": target_date.isoformat(),
        "centre_id": centre_id,
        "overall_compliant": not has_breach,
        "rooms": room_reports,
        "breaches": [r for r in room_reports if not r["compliant"] and r["children_enrolled"] > 0],
    }
