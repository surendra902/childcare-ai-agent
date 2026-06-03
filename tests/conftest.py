"""Pytest fixtures for ChildCareAI Admin Agent test suite.

Provides shared fixtures for:
- Test database setup/teardown
- FastAPI test client
- Mock authentication
- Sample data factories
"""

import os
import base64
import asyncio
from typing import AsyncGenerator, Generator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Ensure test encryption key is set before imports
os.environ.setdefault("ENCRYPTION_KEY", base64.b64encode(os.urandom(32)).decode())
os.environ.setdefault("DEBUG", "true")
os.environ.setdefault("JWT_SECRET", "test-secret")

from models.database import Base, get_session


# Test database URL (in-memory SQLite)
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    """Create an event loop for the test session."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def test_db() -> AsyncGenerator[AsyncSession, None]:
    """Provide a clean test database session.

    Creates all tables before the test and drops them after.
    """
    import models.orm  # noqa: F401 — register ORM models

    engine = create_async_engine(TEST_DATABASE_URL, echo=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """Provide an async HTTP test client for the FastAPI app."""
    import models.orm  # noqa: F401

    # Create test database
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async def override_get_session():
        async with session_factory() as session:
            yield session

    from main import app

    app.dependency_overrides[get_session] = override_get_session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
def sample_staff_data() -> dict:
    """Provide sample staff member data for testing."""
    return {
        "id": "staff-001",
        "name": "Jane Smith",
        "email": "jane@example.com",
        "role": "educator",
        "qualifications": ["Cert III", "First Aid"],
        "rooms": ["Toddlers"],
        "active": True,
    }


@pytest.fixture
def mock_user_director() -> dict:
    """Provide mock director user context."""
    return {
        "id": "user-director-001",
        "role": "director",
        "name": "Dr. Sarah Director",
    }


@pytest.fixture
def mock_user_admin() -> dict:
    """Provide mock admin user context."""
    return {
        "id": "user-admin-001",
        "role": "admin",
        "name": "Admin Alice",
    }


@pytest.fixture
def mock_user_educator() -> dict:
    """Provide mock educator user context."""
    return {
        "id": "user-educator-001",
        "role": "educator",
        "name": "Educator Emma",
    }
