"""Main agent orchestrator for ChildCareAI Admin Agent.

Coordinates between:
- User input (via chat panel)
- Anthropic Claude API (for reasoning)
- Tool functions (for actions)
- Security layer (for approvals and audit)
- PII filter (for data protection)
"""

import json
from datetime import date, time
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from orchestrator.prompts import get_system_prompt, get_tool_definitions
from orchestrator.pii_filter import strip_pii, restore_pii_placeholders
from security.audit import log_action, AuditAction
from security.rbac import has_permission, Role


# Tool registry: maps tool names to their module-level import paths
TOOL_REGISTRY: dict[str, Any] = {}


def register_tools() -> None:
    """Register all available tools in the tool registry."""
    from tools import roster, staffing, comms, escalation, ratios

    TOOL_REGISTRY["get_available_staff"] = roster.get_available_staff
    TOOL_REGISTRY["draft_roster"] = roster.draft_roster
    TOOL_REGISTRY["find_cover"] = staffing.find_cover
    TOOL_REGISTRY["draft_parent_message"] = comms.draft_parent_message
    TOOL_REGISTRY["draft_newsletter"] = comms.draft_newsletter
    TOOL_REGISTRY["escalate_to_director"] = escalation.escalate_to_director
    TOOL_REGISTRY["check_ratios"] = ratios.check_ratios


# Permission mapping: which RBAC permission is needed for each tool
TOOL_PERMISSIONS: dict[str, str] = {
    "get_available_staff": "roster.read",
    "draft_roster": "roster.write",
    "find_cover": "staff.read",
    "draft_parent_message": "comms.draft",
    "draft_newsletter": "comms.draft",
    "escalate_to_director": "roster.read",  # Anyone who can read can escalate
    "check_ratios": "roster.read",
}


def _parse_tool_arg(value: Any, param_name: str) -> Any:
    """Convert string arguments from Claude into proper Python types."""
    if param_name in ("target_date", "date") and isinstance(value, str):
        return date.fromisoformat(value)
    if param_name in ("shift_start", "shift_end", "shift_time") and isinstance(value, str):
        parts = value.split(":")
        return time(int(parts[0]), int(parts[1]))
    return value


class AgentOrchestrator:
    """Main agent orchestrator managing AI interactions and tool execution.

    Responsibilities:
    - Accept user messages and maintain conversation context
    - Send messages to Claude API with system prompt and tools
    - Execute tool calls with appropriate security checks
    - Filter PII from inputs and outputs
    - Handle approval workflows for sensitive actions
    - Stream responses back to the client
    """

    def __init__(
        self, session_id: str, user_id: str, user_role: str,
        centre_id: str = "", db: AsyncSession | None = None,
        known_names: set[str] | None = None,
    ) -> None:
        """Initialize the orchestrator for a chat session.

        Args:
            session_id: Unique identifier for this chat session.
            user_id: Authenticated user's ID.
            user_role: User's role for RBAC checks.
            centre_id: Centre ID for data isolation.
            db: Async database session for tool execution.
            known_names: Set of child/parent names for PII detection.
        """
        self.session_id = session_id
        self.user_id = user_id
        self.user_role = user_role
        self.centre_id = centre_id
        self.db = db
        self.known_names = known_names or set()
        self._conversation_history: list[dict[str, Any]] = []
        from datetime import date as _date
        self._system_prompt = get_system_prompt(user_role) + f"\n\nCURRENT DATE: {_date.today().isoformat()} (Always use this current date to parse relative date terms like 'today', 'tomorrow', 'Monday', or 'this week' to their correct calendar dates)."

        # Ensure tools are registered
        if not TOOL_REGISTRY:
            register_tools()

    async def process_message(self, user_message: str) -> dict[str, Any]:
        """Process a user message and return the agent's response.

        Implements the full agentic loop:
        1. Strip PII from user message
        2. Add to conversation history
        3. Call Claude API with tools
        4. If Claude requests tool calls, execute them (with RBAC + audit)
        5. Feed tool results back to Claude
        6. Repeat until Claude gives a text response
        7. Restore PII in final response
        8. Return structured response

        Args:
            user_message: The user's input text.

        Returns:
            Dict containing the agent's response, tool calls made,
            and whether approval is required for pending actions.
        """
        # Step 1: PII filtering on input
        filtered_message, pii_map = strip_pii(user_message, self.known_names)

        # Load history first if DB is active and history is empty
        if self.db and not self._conversation_history:
            await self._load_conversation_history()

        # Step 2: Add to history
        self._conversation_history.append({
            "role": "user",
            "content": filtered_message,
        })
        if self.db:
            await self._save_message("user", filtered_message)

        # Step 3-6: Agentic loop — call Claude, execute tools, repeat
        all_tool_calls = []
        requires_approval = False
        approval_token = None
        max_iterations = 5  # Safety limit to prevent infinite loops

        for _ in range(max_iterations):
            response_data = await self._call_anthropic()

            tool_calls = response_data.get("tool_calls", [])
            text_content = response_data.get("content", "")

            if not tool_calls:
                # Claude gave a text response — we're done
                break

            # Execute each tool call
            tool_results = []
            for call in tool_calls:
                result = await self._execute_tool(call["name"], call.get("input", {}))
                all_tool_calls.append({
                    "tool": call["name"],
                    "input": call.get("input", {}),
                    "result": result,
                })

                if result.get("requires_approval"):
                    requires_approval = True
                    approval_token = result.get("approval_token")

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": call["id"],
                    "content": json.dumps(result, default=str),
                })

            # Add assistant message with tool use + tool results to history
            self._conversation_history.append({
                "role": "assistant",
                "content": response_data.get("raw_content", []),
            })
            self._conversation_history.append({
                "role": "user",
                "content": tool_results,
            })
            if self.db:
                await self._save_message("assistant", response_data.get("raw_content", []))
                await self._save_message("user", tool_results)

        # Step 7: Restore PII in response
        response_text = text_content
        response_text = restore_pii_placeholders(response_text, pii_map)

        # Add final assistant response to history
        self._conversation_history.append({
            "role": "assistant",
            "content": response_text,
        })
        if self.db:
            await self._save_message("assistant", response_text)

        return {
            "content": response_text,
            "tool_calls": all_tool_calls,
            "requires_approval": requires_approval,
            "approval_token": approval_token,
        }

    async def _call_anthropic(self) -> dict[str, Any]:
        """Send conversation to Anthropic Claude API."""
        if not settings.ANTHROPIC_API_KEY:
            # Mock mode — return helpful message
            return {
                "role": "assistant",
                "content": "I'm running in mock mode (no ANTHROPIC_API_KEY). "
                           "I can help with scheduling, roster management, and parent communications. "
                           "Set ANTHROPIC_API_KEY in .env to enable full AI capabilities.",
                "tool_calls": [],
                "raw_content": [],
            }

        api_key = settings.ANTHROPIC_API_KEY
        is_openrouter = api_key.startswith("sk-or-")
        is_nvidia = api_key.startswith("nvapi-")

        if is_openrouter:
            return await self._call_openrouter(api_key)
        elif is_nvidia:
            return await self._call_nvidia(api_key)

        # Direct Anthropic API call
        import anthropic
        client = anthropic.AsyncAnthropic(api_key=api_key)

        clean_messages = []
        for msg in self._conversation_history:
            if isinstance(msg.get("content"), str) or isinstance(msg.get("content"), list):
                clean_messages.append(msg)

        try:
            message = await client.messages.create(
                model="claude-3-5-haiku-20241022",
                max_tokens=1500,
                system=self._system_prompt,
                messages=clean_messages,
                tools=get_tool_definitions(),
            )

            tool_calls = []
            text_content = ""
            raw_content = []

            for block in message.content:
                if block.type == "text":
                    text_content += block.text
                    raw_content.append({"type": "text", "text": block.text})
                elif block.type == "tool_use":
                    tool_calls.append({
                        "id": block.id,
                        "name": block.name,
                        "input": block.input,
                    })
                    raw_content.append({
                        "type": "tool_use",
                        "id": block.id,
                        "name": block.name,
                        "input": block.input,
                    })

            return {
                "role": "assistant",
                "content": text_content,
                "tool_calls": tool_calls,
                "raw_content": raw_content,
            }
        except Exception as e:
            import traceback
            print(f"\n[AGENT ERROR] {type(e).__name__}: {e}")
            traceback.print_exc()
            return {
                "role": "assistant",
                "content": f"I encountered an error: {e}",
                "tool_calls": [],
                "raw_content": [],
            }

    async def _call_openrouter(self, api_key: str) -> dict[str, Any]:
        """Call OpenRouter using the OpenAI-compatible API (officially supported)."""
        import httpx

        clean_messages = []
        for msg in self._conversation_history:
            role = msg["role"]
            content = msg.get("content")

            if isinstance(content, str):
                clean_messages.append({
                    "role": role,
                    "content": content,
                })
            elif isinstance(content, list):
                if role == "assistant":
                    text_parts = []
                    tool_calls = []
                    for block in content:
                        if block.get("type") == "text":
                            text_parts.append(block.get("text", ""))
                        elif block.get("type") == "tool_use":
                            tool_calls.append({
                                "id": block["id"],
                                "type": "function",
                                "function": {
                                    "name": block["name"],
                                    "arguments": json.dumps(block["input"]) if isinstance(block["input"], dict) else block["input"],
                                }
                            })
                    msg_obj = {
                        "role": "assistant",
                        "content": " ".join(text_parts) if text_parts else None,
                    }
                    if tool_calls:
                        msg_obj["tool_calls"] = tool_calls
                    clean_messages.append(msg_obj)
                elif role == "user":
                    for block in content:
                        if block.get("type") == "tool_result":
                            clean_messages.append({
                                "role": "tool",
                                "tool_call_id": block["tool_use_id"],
                                "content": block.get("content", ""),
                            })

        # Build OpenAI-format tool definitions
        openai_tools = []
        for tool_def in get_tool_definitions():
            openai_tools.append({
                "type": "function",
                "function": {
                    "name": tool_def["name"],
                    "description": tool_def.get("description", ""),
                    "parameters": tool_def.get("input_schema", {}),
                },
            })

        print(f"\n[OR-MODEL]: {settings.OPENROUTER_MODEL}")
        payload = {
            "model": settings.OPENROUTER_MODEL,
            "max_tokens": 1500,
            "messages": [
                {"role": "system", "content": self._system_prompt},
                *clean_messages,
            ],
        }
        if openai_tools:
            payload["tools"] = openai_tools

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://genaimakers.com",
            "X-Title": "ChildCareAI Admin Agent",
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    json=payload,
                    headers=headers,
                )

                if resp.status_code != 200:
                    error_body = resp.text
                    print(f"\n[OPENROUTER ERROR] Status {resp.status_code}: {error_body}")
                    return {
                        "role": "assistant",
                        "content": f"API error ({resp.status_code}): {error_body[:200]}",
                        "tool_calls": [],
                        "raw_content": [],
                    }

                data = resp.json()
                choice = data["choices"][0]
                message = choice["message"]
                text_content = message.get("content", "") or ""

                tool_calls = []
                raw_content = []

                if message.get("tool_calls"):
                    for tc in message["tool_calls"]:
                        func = tc["function"]
                        import json as _json
                        tool_calls.append({
                            "id": tc["id"],
                            "name": func["name"],
                            "input": _json.loads(func["arguments"]) if isinstance(func["arguments"], str) else func["arguments"],
                        })
                        raw_content.append({
                            "type": "tool_use",
                            "id": tc["id"],
                            "name": func["name"],
                            "input": _json.loads(func["arguments"]) if isinstance(func["arguments"], str) else func["arguments"],
                        })

                if text_content:
                    raw_content.insert(0, {"type": "text", "text": text_content})

                return {
                    "role": "assistant",
                    "content": text_content,
                    "tool_calls": tool_calls,
                    "raw_content": raw_content,
                }
        except Exception as e:
            import traceback
            print(f"\n[OPENROUTER ERROR] {type(e).__name__}: {e}")
            traceback.print_exc()
            return {
                "role": "assistant",
                "content": f"Connection error: {e}",
                "tool_calls": [],
                "raw_content": [],
            }

    async def _call_nvidia(self, api_key: str) -> dict[str, Any]:
        """Call NVIDIA NIM API using OpenAI-compatible interface."""
        import httpx

        clean_messages = []
        for msg in self._conversation_history:
            role = msg["role"]
            content = msg.get("content")

            if isinstance(content, str):
                clean_messages.append({
                    "role": role,
                    "content": content,
                })
            elif isinstance(content, list):
                if role == "assistant":
                    text_parts = []
                    tool_calls = []
                    for block in content:
                        if block.get("type") == "text":
                            text_parts.append(block.get("text", ""))
                        elif block.get("type") == "tool_use":
                            tool_calls.append({
                                "id": block["id"],
                                "type": "function",
                                "function": {
                                    "name": block["name"],
                                    "arguments": json.dumps(block["input"]) if isinstance(block["input"], dict) else block["input"],
                                }
                            })
                    msg_obj = {
                        "role": "assistant",
                        "content": " ".join(text_parts) if text_parts else None,
                    }
                    if tool_calls:
                        msg_obj["tool_calls"] = tool_calls
                    clean_messages.append(msg_obj)
                elif role == "user":
                    for block in content:
                        if block.get("type") == "tool_result":
                            clean_messages.append({
                                "role": "tool",
                                "tool_call_id": block["tool_use_id"],
                                "content": block.get("content", ""),
                            })

        # Build OpenAI-format tool definitions
        openai_tools = []
        for tool_def in get_tool_definitions():
            openai_tools.append({
                "type": "function",
                "function": {
                    "name": tool_def["name"],
                    "description": tool_def.get("description", ""),
                    "parameters": tool_def.get("input_schema", {}),
                },
            })

        print(f"\n[NVIDIA-MODEL]: {settings.OPENROUTER_MODEL}")
        payload = {
            "model": settings.OPENROUTER_MODEL,
            "max_tokens": 1500,
            "messages": [
                {"role": "system", "content": self._system_prompt},
                *clean_messages,
            ],
        }
        if openai_tools:
            payload["tools"] = openai_tools

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    "https://integrate.api.nvidia.com/v1/chat/completions",
                    json=payload,
                    headers=headers,
                )

                if resp.status_code != 200:
                    error_body = resp.text
                    print(f"\n[NVIDIA ERROR] Status {resp.status_code}: {error_body}")
                    return {
                        "role": "assistant",
                        "content": f"API error ({resp.status_code}): {error_body[:200]}",
                        "tool_calls": [],
                        "raw_content": [],
                    }

                data = resp.json()
                choice = data["choices"][0]
                message = choice["message"]
                text_content = message.get("content", "") or ""

                tool_calls = []
                raw_content = []

                if message.get("tool_calls"):
                    for tc in message["tool_calls"]:
                        func = tc["function"]
                        import json as _json
                        tool_calls.append({
                            "id": tc["id"],
                            "name": func["name"],
                            "input": _json.loads(func["arguments"]) if isinstance(func["arguments"], str) else func["arguments"],
                        })
                        raw_content.append({
                            "type": "tool_use",
                            "id": tc["id"],
                            "name": func["name"],
                            "input": _json.loads(func["arguments"]) if isinstance(func["arguments"], str) else func["arguments"],
                        })

                if text_content:
                    raw_content.insert(0, {"type": "text", "text": text_content})

                return {
                    "role": "assistant",
                    "content": text_content,
                    "tool_calls": tool_calls,
                    "raw_content": raw_content,
                }
        except Exception as e:
            import traceback
            print(f"\n[NVIDIA ERROR] {type(e).__name__}: {e}")
            traceback.print_exc()
            return {
                "role": "assistant",
                "content": f"Connection error: {e}",
                "tool_calls": [],
                "raw_content": [],
            }

    async def _execute_tool(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        """Execute a tool call with security checks.

        1. RBAC permission check
        2. Input sanitisation / type conversion
        3. Tool execution with centre_id injection
        4. Audit logging
        5. Returns result dict

        Args:
            tool_name: Name of the tool to execute.
            arguments: Arguments from Claude's tool_use block.

        Returns:
            Tool result dict.
        """
        # 1. RBAC check
        required_perm = TOOL_PERMISSIONS.get(tool_name, "")
        if required_perm:
            try:
                role_enum = Role(self.user_role)
            except ValueError:
                role_enum = Role.READONLY

            if not has_permission(role_enum, required_perm):
                return {
                    "error": f"Permission denied: role '{self.user_role}' cannot execute '{tool_name}'",
                    "status": "forbidden",
                }

        # 2. Get tool function
        tool_fn = TOOL_REGISTRY.get(tool_name)
        if not tool_fn:
            return {"error": f"Unknown tool: {tool_name}", "status": "not_found"}

        # 3. Prepare arguments — inject db and centre_id, convert types
        call_args = {}
        for key, value in arguments.items():
            call_args[key] = _parse_tool_arg(value, key)

        # Inject db session and centre_id for all DB-backed tools
        call_args["db"] = self.db
        call_args["centre_id"] = self.centre_id

        # 4. Execute
        try:
            result = await tool_fn(**call_args)
        except TypeError as e:
            # Handle unexpected arguments gracefully
            return {"error": f"Tool argument error: {str(e)}", "status": "error"}
        except Exception as e:
            return {"error": f"Tool execution failed: {str(e)}", "status": "error"}

        # 5. Audit log
        if self.db:
            await log_action(
                db=self.db,
                action=AuditAction.TOOL_EXECUTE,
                actor_id=self.user_id,
                actor_role=self.user_role,
                centre_id=self.centre_id,
                details={"tool": tool_name, "args": {k: str(v) for k, v in arguments.items()}},
            )

        # Wrap result
        if isinstance(result, dict):
            return result
        elif isinstance(result, list):
            return {"results": result, "count": len(result)}
        else:
            return {"result": str(result)}

    async def _load_conversation_history(self) -> None:
        """Load conversation history from database for this session."""
        from sqlalchemy import select
        from models.orm import ChatSession, ChatMessage, ChatRole

        # Find or create session
        stmt = select(ChatSession).where(ChatSession.id == self.session_id)
        result = await self.db.execute(stmt)
        session = result.scalar_one_or_none()

        if not session:
            # Create session (fall back to user_id as staff_id if it exists)
            from sqlalchemy import select as _select
            from models.orm import Staff
            staff_check = await self.db.execute(_select(Staff).where(Staff.id == self.user_id))
            staff_exists = staff_check.scalar_one_or_none()
            
            staff_id = self.user_id if staff_exists else "dev-user"
            
            session = ChatSession(
                id=self.session_id,
                staff_id=staff_id,
                centre_id=self.centre_id or "centre_1",
            )
            self.db.add(session)
            await self.db.flush()
            return

        # Load messages ordered by creation time
        msg_stmt = select(ChatMessage).where(ChatMessage.session_id == self.session_id).order_by(ChatMessage.created_at)
        msg_result = await self.db.execute(msg_stmt)
        messages = msg_result.scalars().all()

        self._conversation_history = []
        for msg in messages:
            role_str = msg.role.value if hasattr(msg.role, "value") else str(msg.role)
            self._conversation_history.append({
                "role": role_str,
                "content": msg.tool_calls if msg.tool_calls is not None else msg.content,
            })

    async def _save_message(self, role: str, content: Any) -> None:
        """Save a message to the database."""
        if not self.db:
            return
            
        from models.orm import ChatMessage, ChatRole
        
        chat_role = ChatRole.user if role == "user" else ChatRole.assistant
        
        if isinstance(content, str):
            msg = ChatMessage(
                session_id=self.session_id,
                role=chat_role,
                content=content,
                tool_calls=None,
            )
        else:
            msg = ChatMessage(
                session_id=self.session_id,
                role=chat_role,
                content="",
                tool_calls=content,
            )
        self.db.add(msg)
        await self.db.flush()
