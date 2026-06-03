"""Tests for the orchestrator module (agent, prompts, PII filter).

Validates orchestrator behavior, prompt generation, and PII detection.
"""

import os
import base64
import pytest

# Ensure encryption key is set for tests
os.environ.setdefault("ENCRYPTION_KEY", base64.b64encode(os.urandom(32)).decode())

from orchestrator.agent import AgentOrchestrator
from orchestrator.prompts import get_system_prompt, get_tool_definitions, ROLE_PROMPTS
from orchestrator.pii_filter import strip_pii, restore_pii_placeholders, contains_pii, mask_pii_for_logging


class TestPrompts:
    """Tests for system prompt generation."""

    def test_get_system_prompt_director(self) -> None:
        """Director prompt should include director-specific context."""
        prompt = get_system_prompt("director")
        assert "CRITICAL GUARDRAILS" in prompt
        assert "Director" in prompt

    def test_get_system_prompt_educator(self) -> None:
        """Educator prompt should include educator-specific context."""
        prompt = get_system_prompt("educator")
        assert "Educator" in prompt
        assert "cannot modify rosters" in prompt

    def test_get_system_prompt_unknown_role_defaults_readonly(self) -> None:
        """Unknown role should default to readonly prompt."""
        prompt = get_system_prompt("unknown_role")
        assert "Read-Only" in prompt

    def test_get_tool_definitions_returns_list(self) -> None:
        """get_tool_definitions should return a non-empty list."""
        tools = get_tool_definitions()
        assert isinstance(tools, list)
        assert len(tools) > 0

    def test_tool_definitions_have_required_fields(self) -> None:
        """Each tool definition should have name, description, input_schema."""
        tools = get_tool_definitions()
        for tool in tools:
            assert "name" in tool
            assert "description" in tool
            assert "input_schema" in tool

    def test_all_tools_defined(self) -> None:
        """All 7 tools should be defined."""
        tools = get_tool_definitions()
        names = {t["name"] for t in tools}
        assert "get_available_staff" in names
        assert "draft_roster" in names
        assert "find_cover" in names
        assert "draft_parent_message" in names
        assert "draft_newsletter" in names
        assert "escalate_to_director" in names
        assert "check_ratios" in names


class TestPIIFilter:
    """Tests for PII detection and stripping."""

    def test_strip_phone_number(self) -> None:
        """Should detect and strip Australian phone numbers."""
        text = "Call me on 0412 3456 7890"
        filtered, pii_map = strip_pii(text)
        assert "0412" not in filtered
        assert len(pii_map) > 0

    def test_strip_email(self) -> None:
        """Should detect and strip email addresses."""
        text = "Send to parent@example.com please"
        filtered, pii_map = strip_pii(text)
        assert "parent@example.com" not in filtered
        assert len(pii_map) > 0

    def test_restore_pii(self) -> None:
        """Should restore PII placeholders to original values."""
        text = "Email is test@example.com"
        filtered, pii_map = strip_pii(text)
        restored = restore_pii_placeholders(filtered, pii_map)
        assert "test@example.com" in restored

    def test_contains_pii_positive(self) -> None:
        """Should detect presence of PII."""
        assert contains_pii("Contact: john@example.com")
        assert contains_pii("Phone: 0412 345 678")

    def test_contains_pii_negative(self) -> None:
        """Should return False for text without PII."""
        assert not contains_pii("Please check the roster for Monday")

    def test_mask_pii_for_logging(self) -> None:
        """Should mask PII non-reversibly for logging."""
        text = "Email: parent@example.com, Phone: 0412 345 678"
        masked = mask_pii_for_logging(text)
        assert "parent@example.com" not in masked
        assert "0412" not in masked
        assert "REDACTED" in masked

    def test_strip_known_names(self) -> None:
        """Should detect and strip known child/parent names."""
        names = {"Oliver Brown", "Charlotte"}
        text = "Oliver Brown had a great day. Charlotte played nicely."
        filtered, pii_map = strip_pii(text, known_names=names)
        assert "Oliver Brown" not in filtered
        assert "Charlotte" not in filtered
        assert len(pii_map) >= 2

    def test_restore_known_names(self) -> None:
        """Should restore name placeholders to original values."""
        names = {"Oliver"}
        text = "Oliver is doing well today."
        filtered, pii_map = strip_pii(text, known_names=names)
        restored = restore_pii_placeholders(filtered, pii_map)
        assert "Oliver" in restored


class TestAgentOrchestrator:
    """Tests for the agent orchestrator."""

    def test_orchestrator_initialization(self) -> None:
        """AgentOrchestrator should initialize with session context."""
        agent = AgentOrchestrator(
            session_id="test-session",
            user_id="user-001",
            user_role="admin",
        )
        assert agent.session_id == "test-session"
        assert agent.user_id == "user-001"
        assert agent.user_role == "admin"

    @pytest.mark.asyncio
    async def test_process_message_returns_response(self) -> None:
        """process_message should return a structured response dict."""
        agent = AgentOrchestrator(
            session_id="test-session",
            user_id="user-001",
            user_role="admin",
        )
        result = await agent.process_message("Who is available tomorrow?")
        assert isinstance(result, dict)
        assert "content" in result
        assert "tool_calls" in result
