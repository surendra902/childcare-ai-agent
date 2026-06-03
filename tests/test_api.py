"""Tests for the API layer (routes, middleware, WebSocket).

Validates HTTP endpoints and WebSocket behavior.
"""

import pytest
import pytest_asyncio
from httpx import AsyncClient


class TestHealthEndpoint:
    """Tests for the health check endpoint."""

    @pytest.mark.asyncio
    async def test_health_returns_200(self, client: AsyncClient) -> None:
        """Health endpoint should return 200 with status healthy."""
        response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "childcare-ai-admin"


class TestSecurityHeaders:
    """Tests for security headers middleware."""

    @pytest.mark.asyncio
    async def test_hsts_header_present(self, client: AsyncClient) -> None:
        """Response should include Strict-Transport-Security header."""
        response = await client.get("/health")
        assert "strict-transport-security" in response.headers

    @pytest.mark.asyncio
    async def test_x_content_type_options(self, client: AsyncClient) -> None:
        """Response should include X-Content-Type-Options: nosniff."""
        response = await client.get("/health")
        assert response.headers.get("x-content-type-options") == "nosniff"

    @pytest.mark.asyncio
    async def test_x_frame_options(self, client: AsyncClient) -> None:
        """Response should include X-Frame-Options: DENY."""
        response = await client.get("/health")
        assert response.headers.get("x-frame-options") == "DENY"

    @pytest.mark.asyncio
    async def test_csp_header_present(self, client: AsyncClient) -> None:
        """Response should include Content-Security-Policy header."""
        response = await client.get("/health")
        assert "content-security-policy" in response.headers


class TestChatEndpoint:
    """Tests for the chat API endpoint."""

    @pytest.mark.asyncio
    async def test_chat_returns_response(self, client: AsyncClient) -> None:
        """Chat endpoint should return a response (mock mode)."""
        response = await client.post(
            "/api/v1/chat",
            json={"session_id": "test-session", "content": "Hello"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "content" in data
        assert data["session_id"] == "test-session"


class TestRosterEndpoint:
    """Tests for the roster API endpoint."""

    @pytest.mark.asyncio
    async def test_roster_returns_200(self, client: AsyncClient) -> None:
        """Roster endpoint should return 200 with empty list."""
        response = await client.get("/api/v1/roster")
        assert response.status_code == 200
        data = response.json()
        assert "entries" in data
