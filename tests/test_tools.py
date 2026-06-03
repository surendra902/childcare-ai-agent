"""Tests for the tools module (roster, staffing, comms, escalation, ratios).

Validates tool function signatures and basic behavior.
These are unit tests using mock DB sessions.
"""

import os
import base64
import pytest
from datetime import date, time
from unittest.mock import AsyncMock, MagicMock

# Ensure encryption key is set for tests
os.environ.setdefault("ENCRYPTION_KEY", base64.b64encode(os.urandom(32)).decode())

from tools.comms import draft_parent_message, draft_newsletter
from orchestrator.agent import AgentOrchestrator, register_tools, TOOL_REGISTRY


class TestToolRegistry:
    """Tests for the tool registry."""

    def test_register_tools_populates_registry(self) -> None:
        """register_tools should populate the TOOL_REGISTRY."""
        TOOL_REGISTRY.clear()
        register_tools()
        assert "get_available_staff" in TOOL_REGISTRY
        assert "draft_roster" in TOOL_REGISTRY
        assert "find_cover" in TOOL_REGISTRY
        assert "draft_parent_message" in TOOL_REGISTRY
        assert "draft_newsletter" in TOOL_REGISTRY
        assert "escalate_to_director" in TOOL_REGISTRY
        assert "check_ratios" in TOOL_REGISTRY

    def test_all_tools_are_callable(self) -> None:
        """All registered tools should be callable."""
        if not TOOL_REGISTRY:
            register_tools()
        for name, fn in TOOL_REGISTRY.items():
            assert callable(fn), f"Tool '{name}' is not callable"


class TestCommsTools:
    """Tests for communication tools (these can be tested with mock DB)."""

    @pytest.mark.asyncio
    async def test_draft_parent_message_returns_dict(self) -> None:
        """draft_parent_message should return a dict with subject and body."""
        # Create a mock DB session that returns None for queries
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        result = await draft_parent_message(
            db=mock_db,
            centre_id="test-centre",
            recipient_name="Mrs. Johnson",
            subject="Pick-up time change",
            context="Child will be picked up by grandparent today",
        )
        assert isinstance(result, dict)
        assert "subject" in result
        assert "body" in result

    @pytest.mark.asyncio
    async def test_draft_newsletter_returns_dict(self) -> None:
        """draft_newsletter should return a dict with expected keys."""
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result

        result = await draft_newsletter(
            db=mock_db,
            centre_id="test-centre",
            period="Week of March 15",
            highlights=["Art day", "New playground equipment"],
        )
        assert isinstance(result, dict)
        assert "subject" in result
        assert "body" in result


class TestAgentToolExecution:
    """Tests for agent tool permission checking."""

    @pytest.mark.asyncio
    async def test_forbidden_tool_for_readonly(self) -> None:
        """Readonly role should not be able to execute write tools."""
        agent = AgentOrchestrator(
            session_id="test",
            user_id="user-001",
            user_role="readonly",
        )
        result = await agent._execute_tool("draft_roster", {"target_date": "2024-03-15"})
        assert result.get("status") == "forbidden"

    @pytest.mark.asyncio
    async def test_unknown_tool_returns_not_found(self) -> None:
        """Requesting an unknown tool should return not_found status."""
        agent = AgentOrchestrator(
            session_id="test",
            user_id="user-001",
            user_role="director",
        )
        result = await agent._execute_tool("nonexistent_tool", {})
        assert result.get("status") == "not_found"
