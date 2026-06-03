"""Communication tools for ChildCareAI Admin Agent.

Provides functions for drafting parent-facing communications:
- draft_parent_message: Generate personalised messages to parents
- draft_newsletter: Generate newsletter content for the centre
"""

from typing import Any

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from models.orm import Child, Parent, Room, Observation, child_parent_association


async def draft_parent_message(
    db: AsyncSession,
    centre_id: str,
    recipient_name: str,
    subject: str,
    context: str,
    tone: str = "warm_professional",
    include_action_items: bool = False,
) -> dict[str, Any]:
    """Draft a message to a parent/guardian.

    Fetches child and parent context from the database to enrich the draft.

    Args:
        db: Async database session.
        centre_id: Centre to scope the query to.
        recipient_name: Name of the parent/guardian.
        subject: Subject/topic of the message.
        context: Background context for the AI to use when drafting.
        tone: Desired tone (warm_professional, formal, casual).
        include_action_items: Whether to include action items at the end.

    Returns:
        Dict with 'subject', 'body', 'recipient_info', and 'tone' keys.
    """
    # Try to find the parent in the DB for context enrichment
    parent_info = None
    child_info = []

    # Search for parent by name (first name match)
    first_name = recipient_name.split()[0] if recipient_name else ""
    if first_name:
        parent_result = await db.execute(
            select(Parent).where(
                and_(
                    Parent.centre_id == centre_id,
                    Parent.first_name.ilike(f"%{first_name}%"),
                )
            )
        )
        parent = parent_result.scalar_one_or_none()

        if parent:
            parent_info = {
                "id": parent.id,
                "name": f"{parent.first_name} {parent.last_name}",
                "relationship": parent.relationship_to_child,
                "is_primary": parent.is_primary_contact,
            }

            # Get linked children
            children_result = await db.execute(
                select(Child)
                .join(child_parent_association)
                .where(child_parent_association.c.parent_id == parent.id)
            )
            children = children_result.scalars().all()
            for child in children:
                room_name = None
                if child.room_id:
                    room_result = await db.execute(
                        select(Room.name).where(Room.id == child.room_id)
                    )
                    room_name = room_result.scalar_one_or_none()

                child_info.append({
                    "name": f"{child.first_name} {child.last_name}",
                    "room": room_name,
                })

    return {
        "subject": subject,
        "body": f"[Draft message to {recipient_name} about: {subject}]",
        "context": context,
        "tone": tone,
        "recipient_info": parent_info,
        "children": child_info,
        "include_action_items": include_action_items,
    }


async def draft_newsletter(
    db: AsyncSession,
    centre_id: str,
    period: str,
    highlights: list[str],
    upcoming_events: list[dict[str, Any]] | None = None,
    room_id: str | None = None,
    tone: str = "warm_professional",
) -> dict[str, Any]:
    """Draft a newsletter for parents/families.

    Fetches recent observations and room context from the database.

    Args:
        db: Async database session.
        centre_id: Centre to scope the query to.
        period: Time period the newsletter covers (e.g., "Week of Jan 15").
        highlights: Key highlights/activities to include.
        upcoming_events: Optional list of upcoming events with dates.
        room_id: Optional room to generate newsletter for.
        tone: Desired tone for the newsletter.

    Returns:
        Dict with 'subject', 'body', 'sections', and context data.
    """
    # Get recent shared observations for context
    obs_stmt = (
        select(Observation)
        .where(
            and_(
                Observation.centre_id == centre_id,
                Observation.is_shared_with_parents == True,
            )
        )
        .order_by(Observation.observation_date.desc())
        .limit(5)
    )
    if room_id:
        obs_stmt = obs_stmt.where(Observation.room_id == room_id)

    obs_result = await db.execute(obs_stmt)
    observations = obs_result.scalars().all()

    recent_activities = [
        {
            "type": obs.observation_type.value if hasattr(obs.observation_type, 'value') else obs.observation_type,
            "content": obs.content[:100] + "..." if len(obs.content) > 100 else obs.content,
            "date": obs.observation_date.isoformat(),
        }
        for obs in observations
    ]

    # Get rooms info
    room_stmt = select(Room).where(
        and_(Room.centre_id == centre_id, Room.is_active == True)
    )
    if room_id:
        room_stmt = room_stmt.where(Room.id == room_id)
    room_result = await db.execute(room_stmt)
    rooms = room_result.scalars().all()

    return {
        "subject": f"Newsletter — {period}",
        "body": f"[Draft newsletter for {period}]",
        "period": period,
        "highlights": highlights,
        "upcoming_events": upcoming_events or [],
        "recent_activities": recent_activities,
        "rooms": [{"id": r.id, "name": r.name, "age_group": r.age_group} for r in rooms],
        "tone": tone,
    }
