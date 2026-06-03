"""Database connection and session management for ChildCareAI Admin Agent.

Provides async SQLAlchemy engine, session factory, and lifecycle hooks
for the FastAPI application. Includes demo data seeding for development.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import AsyncGenerator
from uuid import uuid4

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from config import settings


class Base(DeclarativeBase):
    """SQLAlchemy declarative base for all ORM models."""

    pass


# Module-level engine and session factory (initialized at startup)
_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


async def init_db() -> None:
    """Initialize the database engine and create tables.

    Called during application startup via the lifespan context manager.
    In production, use Alembic migrations instead of create_all.
    """
    global _engine, _session_factory

    _engine = create_async_engine(
        settings.DATABASE_URL,
        echo=settings.DEBUG,
        pool_pre_ping=True,
    )

    _session_factory = async_sessionmaker(
        bind=_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    # Import ORM models to ensure they are registered with Base.metadata
    import models.orm  # noqa: F401

    # Create tables (development only)
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_db() -> None:
    """Close the database engine and release connections.

    Called during application shutdown via the lifespan context manager.
    """
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency providing a database session.

    Yields:
        An async SQLAlchemy session. Automatically closed after request.

    Raises:
        RuntimeError: If database has not been initialized.
    """
    if _session_factory is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")

    async with _session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# Alias for backward compatibility
get_session = get_db


async def seed_demo_data() -> None:
    """Populate the database with demo data for testing.

    Creates:
    - 1 centre (Sunshine Early Learning Centre)
    - 2 rooms (Koalas for babies, Possums for toddlers)
    - 5 staff members
    - 8 children
    - 6 parents (linked to children)
    - Sample roster entries for current week
    - Sample observations
    """
    from models.orm import (
        Centre,
        Child,
        ChatSession,
        ConsentRecord,
        ConsentType,
        Observation,
        ObservationType,
        Parent,
        Room,
        RosterEntry,
        RosterStatus,
        ShiftType,
        Staff,
        StaffAvailability,
        StaffRole,
        child_parent_association,
    )

    if _session_factory is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")

    async with _session_factory() as session:
        from sqlalchemy import select

        # Check if data already exists
        result = await session.execute(select(Centre).limit(1))
        if result.scalar_one_or_none() is not None:
            return  # Already seeded

        now = datetime.utcnow()
        today = date.today()

        # ─── Centre ──────────────────────────────────────────────────────
        centre_id = str(uuid4())
        centre = Centre(
            id=centre_id,
            name="Sunshine Early Learning Centre",
            address="42 Wattle Street, Melbourne VIC 3000",
            phone="+61 3 9876 5432",
            email="admin@sunshinelc.com.au",
            is_active=True,
            created_at=now,
        )
        session.add(centre)

        # ─── Rooms ───────────────────────────────────────────────────────
        room_koalas_id = str(uuid4())
        room_possums_id = str(uuid4())

        room_koalas = Room(
            id=room_koalas_id,
            centre_id=centre_id,
            name="Koalas",
            capacity=12,
            age_group="babies",
            required_ratio="1:4",
            is_active=True,
        )
        room_possums = Room(
            id=room_possums_id,
            centre_id=centre_id,
            name="Possums",
            capacity=16,
            age_group="toddlers",
            required_ratio="1:5",
            is_active=True,
        )
        session.add_all([room_koalas, room_possums])

        # ─── Staff ───────────────────────────────────────────────────────
        staff_ids = [str(uuid4()) for _ in range(5)]

        staff_data = [
            {
                "id": staff_ids[0],
                "first_name": "Sarah",
                "last_name": "Mitchell",
                "email": "sarah.mitchell@sunshinelc.com.au",
                "phone": "+61 400 111 001",
                "role": StaffRole.centre_manager,
                "assigned_room_id": None,
                "contracted_hours": 38.0,
            },
            {
                "id": staff_ids[1],
                "first_name": "Emma",
                "last_name": "Chen",
                "email": "emma.chen@sunshinelc.com.au",
                "phone": "+61 400 111 002",
                "role": StaffRole.room_leader,
                "assigned_room_id": room_koalas_id,
                "contracted_hours": 38.0,
            },
            {
                "id": staff_ids[2],
                "first_name": "James",
                "last_name": "Wilson",
                "email": "james.wilson@sunshinelc.com.au",
                "phone": "+61 400 111 003",
                "role": StaffRole.room_leader,
                "assigned_room_id": room_possums_id,
                "contracted_hours": 38.0,
            },
            {
                "id": staff_ids[3],
                "first_name": "Priya",
                "last_name": "Sharma",
                "email": "priya.sharma@sunshinelc.com.au",
                "phone": "+61 400 111 004",
                "role": StaffRole.educator,
                "assigned_room_id": room_koalas_id,
                "contracted_hours": 30.0,
            },
            {
                "id": staff_ids[4],
                "first_name": "Tom",
                "last_name": "Nguyen",
                "email": "tom.nguyen@sunshinelc.com.au",
                "phone": "+61 400 111 005",
                "role": StaffRole.educator,
                "assigned_room_id": room_possums_id,
                "contracted_hours": 30.0,
            },
        ]

        staff_objects = []
        for s in staff_data:
            staff_obj = Staff(
                centre_id=centre_id,
                is_active=True,
                created_at=now,
                **s,
            )
            staff_objects.append(staff_obj)
        session.add_all(staff_objects)

        # ─── Children ────────────────────────────────────────────────────
        child_ids = [str(uuid4()) for _ in range(8)]

        children_data = [
            {"id": child_ids[0], "first_name": "Oliver", "last_name": "Brown", "dob": date(2024, 3, 15), "room_id": room_koalas_id},
            {"id": child_ids[1], "first_name": "Charlotte", "last_name": "Smith", "dob": date(2024, 5, 22), "room_id": room_koalas_id},
            {"id": child_ids[2], "first_name": "Noah", "last_name": "Johnson", "dob": date(2024, 1, 8), "room_id": room_koalas_id},
            {"id": child_ids[3], "first_name": "Amelia", "last_name": "Williams", "dob": date(2023, 7, 11), "room_id": room_possums_id},
            {"id": child_ids[4], "first_name": "Liam", "last_name": "Taylor", "dob": date(2023, 9, 3), "room_id": room_possums_id},
            {"id": child_ids[5], "first_name": "Isla", "last_name": "Anderson", "dob": date(2023, 4, 19), "room_id": room_possums_id},
            {"id": child_ids[6], "first_name": "Jack", "last_name": "Thomas", "dob": date(2023, 11, 28), "room_id": room_possums_id},
            {"id": child_ids[7], "first_name": "Mia", "last_name": "Garcia", "dob": date(2024, 2, 14), "room_id": room_koalas_id},
        ]

        child_objects = []
        for c in children_data:
            child_obj = Child(
                id=c["id"],
                centre_id=centre_id,
                first_name=c["first_name"],
                last_name=c["last_name"],
                date_of_birth=c["dob"],
                room_id=c["room_id"],
                enrolment_date=today - timedelta(days=90),
                is_active=True,
                created_at=now,
            )
            child_objects.append(child_obj)
        session.add_all(child_objects)

        # ─── Parents ─────────────────────────────────────────────────────
        parent_ids = [str(uuid4()) for _ in range(6)]

        parents_data = [
            {"id": parent_ids[0], "first_name": "Michael", "last_name": "Brown", "email": "michael.brown@email.com", "phone": "+61 400 200 001", "relationship": "father", "primary": True},
            {"id": parent_ids[1], "first_name": "Jessica", "last_name": "Brown", "email": "jessica.brown@email.com", "phone": "+61 400 200 002", "relationship": "mother", "primary": False},
            {"id": parent_ids[2], "first_name": "David", "last_name": "Smith", "email": "david.smith@email.com", "phone": "+61 400 200 003", "relationship": "father", "primary": True},
            {"id": parent_ids[3], "first_name": "Karen", "last_name": "Johnson", "email": "karen.johnson@email.com", "phone": "+61 400 200 004", "relationship": "mother", "primary": True},
            {"id": parent_ids[4], "first_name": "Robert", "last_name": "Williams", "email": "robert.williams@email.com", "phone": "+61 400 200 005", "relationship": "father", "primary": True},
            {"id": parent_ids[5], "first_name": "Lisa", "last_name": "Taylor", "email": "lisa.taylor@email.com", "phone": "+61 400 200 006", "relationship": "mother", "primary": True},
        ]

        parent_objects = []
        for p in parents_data:
            parent_obj = Parent(
                id=p["id"],
                centre_id=centre_id,
                first_name=p["first_name"],
                last_name=p["last_name"],
                email=p["email"],
                phone=p["phone"],
                relationship_to_child=p["relationship"],
                is_primary_contact=p["primary"],
                created_at=now,
            )
            parent_objects.append(parent_obj)
        session.add_all(parent_objects)

        await session.flush()

        # ─── Child-Parent Links ──────────────────────────────────────────
        links = [
            {"child_id": child_ids[0], "parent_id": parent_ids[0]},  # Oliver -> Michael Brown
            {"child_id": child_ids[0], "parent_id": parent_ids[1]},  # Oliver -> Jessica Brown
            {"child_id": child_ids[1], "parent_id": parent_ids[2]},  # Charlotte -> David Smith
            {"child_id": child_ids[2], "parent_id": parent_ids[3]},  # Noah -> Karen Johnson
            {"child_id": child_ids[3], "parent_id": parent_ids[4]},  # Amelia -> Robert Williams
            {"child_id": child_ids[4], "parent_id": parent_ids[5]},  # Liam -> Lisa Taylor
            {"child_id": child_ids[5], "parent_id": parent_ids[5]},  # Isla -> Lisa Taylor
            {"child_id": child_ids[6], "parent_id": parent_ids[3]},  # Jack -> Karen Johnson
            {"child_id": child_ids[7], "parent_id": parent_ids[1]},  # Mia -> Jessica Brown
        ]
        for link in links:
            await session.execute(
                child_parent_association.insert().values(**link)
            )

        # ─── Roster Entries (current week) ───────────────────────────────
        monday = today - timedelta(days=today.weekday())

        roster_data = [
            # Emma (room leader Koalas) - full week AM
            {"staff_id": staff_ids[1], "room_id": room_koalas_id, "day_offset": 0, "start": time(7, 0), "end": time(15, 0), "shift": ShiftType.AM},
            {"staff_id": staff_ids[1], "room_id": room_koalas_id, "day_offset": 1, "start": time(7, 0), "end": time(15, 0), "shift": ShiftType.AM},
            {"staff_id": staff_ids[1], "room_id": room_koalas_id, "day_offset": 2, "start": time(7, 0), "end": time(15, 0), "shift": ShiftType.AM},
            {"staff_id": staff_ids[1], "room_id": room_koalas_id, "day_offset": 3, "start": time(7, 0), "end": time(15, 0), "shift": ShiftType.AM},
            {"staff_id": staff_ids[1], "room_id": room_koalas_id, "day_offset": 4, "start": time(7, 0), "end": time(15, 0), "shift": ShiftType.AM},
            # James (room leader Possums) - full week
            {"staff_id": staff_ids[2], "room_id": room_possums_id, "day_offset": 0, "start": time(8, 0), "end": time(16, 0), "shift": ShiftType.FULL},
            {"staff_id": staff_ids[2], "room_id": room_possums_id, "day_offset": 1, "start": time(8, 0), "end": time(16, 0), "shift": ShiftType.FULL},
            {"staff_id": staff_ids[2], "room_id": room_possums_id, "day_offset": 2, "start": time(8, 0), "end": time(16, 0), "shift": ShiftType.FULL},
            {"staff_id": staff_ids[2], "room_id": room_possums_id, "day_offset": 3, "start": time(8, 0), "end": time(16, 0), "shift": ShiftType.FULL},
            # Priya (educator Koalas) - 3 days
            {"staff_id": staff_ids[3], "room_id": room_koalas_id, "day_offset": 0, "start": time(9, 0), "end": time(15, 0), "shift": ShiftType.PM},
            {"staff_id": staff_ids[3], "room_id": room_koalas_id, "day_offset": 2, "start": time(9, 0), "end": time(15, 0), "shift": ShiftType.PM},
            {"staff_id": staff_ids[3], "room_id": room_koalas_id, "day_offset": 4, "start": time(9, 0), "end": time(15, 0), "shift": ShiftType.PM},
            # Tom (educator Possums) - 3 days
            {"staff_id": staff_ids[4], "room_id": room_possums_id, "day_offset": 1, "start": time(10, 0), "end": time(18, 0), "shift": ShiftType.PM},
            {"staff_id": staff_ids[4], "room_id": room_possums_id, "day_offset": 3, "start": time(10, 0), "end": time(18, 0), "shift": ShiftType.PM},
            {"staff_id": staff_ids[4], "room_id": room_possums_id, "day_offset": 4, "start": time(10, 0), "end": time(18, 0), "shift": ShiftType.PM},
        ]

        for r in roster_data:
            entry = RosterEntry(
                id=str(uuid4()),
                centre_id=centre_id,
                staff_id=r["staff_id"],
                room_id=r["room_id"],
                date=monday + timedelta(days=r["day_offset"]),
                shift_start=r["start"],
                shift_end=r["end"],
                shift_type=r["shift"],
                status=RosterStatus.published,
                approved_by=staff_ids[0],
                approved_at=now - timedelta(days=3),
                created_at=now - timedelta(days=5),
            )
            session.add(entry)

        # ─── Observations ────────────────────────────────────────────────
        observations_data = [
            {
                "child_id": child_ids[0],
                "staff_id": staff_ids[1],
                "room_id": room_koalas_id,
                "obs_date": today - timedelta(days=1),
                "content": "Oliver had a wonderful day today. He was very engaged during tummy time and showed great head control. He smiled and cooed when we sang nursery rhymes during group time.",
                "obs_type": ObservationType.daily_update,
                "shared": True,
            },
            {
                "child_id": child_ids[3],
                "staff_id": staff_ids[2],
                "room_id": room_possums_id,
                "obs_date": today - timedelta(days=1),
                "content": "Amelia built a tall block tower today (8 blocks high!) and was delighted when it fell. She repeated the activity 3 times, showing persistence and fine motor development.",
                "obs_type": ObservationType.learning_story,
                "shared": True,
            },
            {
                "child_id": child_ids[4],
                "staff_id": staff_ids[4],
                "room_id": room_possums_id,
                "obs_date": today,
                "content": "Liam bumped his head on the corner of the bookshelf while running. Ice pack applied. Small red mark, no swelling. Parents notified at pickup.",
                "obs_type": ObservationType.incident,
                "shared": True,
            },
            {
                "child_id": child_ids[1],
                "staff_id": staff_ids[3],
                "room_id": room_koalas_id,
                "obs_date": today,
                "content": "Charlotte rolled from tummy to back for the first time today! She seemed surprised and then very pleased with herself. Milestone recorded.",
                "obs_type": ObservationType.milestone,
                "shared": False,
            },
        ]

        for obs in observations_data:
            observation = Observation(
                id=str(uuid4()),
                child_id=obs["child_id"],
                staff_id=obs["staff_id"],
                centre_id=centre_id,
                room_id=obs["room_id"],
                observation_date=obs["obs_date"],
                content=obs["content"],
                observation_type=obs["obs_type"],
                is_shared_with_parents=obs["shared"],
                shared_at=now if obs["shared"] else None,
                created_at=now,
            )
            session.add(observation)

        # ─── Staff Availability (mark one staff sick) ────────────────────
        sick_entry = StaffAvailability(
            id=str(uuid4()),
            staff_id=staff_ids[3],  # Priya is sick tomorrow
            date=today + timedelta(days=1),
            is_available=False,
            reason="sick leave",
            created_at=now,
        )
        session.add(sick_entry)

        await session.commit()
