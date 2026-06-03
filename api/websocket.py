"""WebSocket handler for real-time chat streaming.

Manages WebSocket connections for the floating chat panel,
enabling streaming AI responses back to the client.
"""

import json
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

from config import settings
from models.database import get_db
from orchestrator.agent import AgentOrchestrator

router = APIRouter()


class ConnectionManager:
    """Manage active WebSocket connections."""

    def __init__(self) -> None:
        self._active_connections: dict[str, WebSocket] = {}
        self._agents: dict[str, AgentOrchestrator] = {}

    async def connect(self, websocket: WebSocket, session_id: str) -> None:
        """Accept and register a new WebSocket connection."""
        await websocket.accept()
        self._active_connections[session_id] = websocket

    def disconnect(self, session_id: str) -> None:
        """Remove a WebSocket connection from the active pool."""
        self._active_connections.pop(session_id, None)
        self._agents.pop(session_id, None)

    def get_agent(
        self, session_id: str, user_id: str, user_role: str,
        centre_id: str, db=None,
    ) -> AgentOrchestrator:
        """Get or create an AgentOrchestrator for a session."""
        if session_id not in self._agents:
            self._agents[session_id] = AgentOrchestrator(
                session_id=session_id,
                user_id=user_id,
                user_role=user_role,
                centre_id=centre_id,
                db=db,
            )
        else:
            # Update the DB session (it may have changed between requests)
            self._agents[session_id].db = db
        return self._agents[session_id]

    async def send_message(self, session_id: str, message: dict[str, Any]) -> None:
        """Send a JSON message to a specific connected client."""
        ws = self._active_connections.get(session_id)
        if ws:
            await ws.send_json(message)

    async def broadcast(self, message: dict[str, Any]) -> None:
        """Broadcast a message to all connected clients."""
        for ws in self._active_connections.values():
            await ws.send_json(message)


manager = ConnectionManager()


@router.websocket("/ws/chat/{session_id}")
async def websocket_chat(websocket: WebSocket, session_id: str) -> None:
    """WebSocket endpoint for streaming chat interactions.

    Protocol:
    - Client sends JSON: {"type": "message", "content": "..."}
    - Server sends JSON: {"type": "complete", "content": "...", "tool_calls": [...]}
    - Server sends JSON: {"type": "approval_required", "token": "...", "action": "..."}
    - Server sends JSON: {"type": "error", "content": "..."}
    """
    await manager.connect(websocket, session_id)

    # Determine user context — in production, extract from JWT in query params
    # For now, use dev defaults when DEBUG is true
    user_id = "dev-user"
    user_role = "director"
    centre_id = "centre_1"

    # Try to extract auth from query params
    token = websocket.query_params.get("token", "")
    if token and settings.JWT_SECRET:
        try:
            from jose import jwt
            payload = jwt.decode(token, settings.JWT_SECRET, algorithms=["HS256"])
            user_id = payload.get("id", user_id)
            user_role = payload.get("role", user_role)
            centre_id = payload.get("centre_id", centre_id)
        except Exception:
            pass  # Fall back to defaults
    elif not settings.DEBUG:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    try:
        while True:
            data = await websocket.receive_text()
            try:
                message = json.loads(data)
            except json.JSONDecodeError:
                await manager.send_message(session_id, {
                    "type": "error",
                    "content": "Invalid JSON format",
                })
                continue

            content = message.get("content", "").strip()
            if not content:
                continue

            # Get a DB session for this request
            from models.database import _session_factory
            if _session_factory:
                async with _session_factory() as db:
                    try:
                        agent = manager.get_agent(
                            session_id, user_id, user_role, centre_id, db=db
                        )
                        result = await agent.process_message(content)
                        await db.commit()

                        # Send response
                        response = {
                            "type": "complete",
                            "content": result["content"],
                            "session_id": session_id,
                        }

                        if result.get("tool_calls"):
                            response["tool_calls"] = [
                                {"tool": tc["tool"], "result": tc["result"]}
                                for tc in result["tool_calls"]
                            ]

                        if result.get("requires_approval"):
                            await manager.send_message(session_id, {
                                "type": "approval_required",
                                "token": result.get("approval_token", ""),
                                "action": "Action requires director approval",
                            })

                        await manager.send_message(session_id, response)

                    except Exception as e:
                        await db.rollback()
                        await manager.send_message(session_id, {
                            "type": "error",
                            "content": f"An error occurred processing your request.",
                        })
            else:
                # No DB — run in mock mode
                agent = manager.get_agent(
                    session_id, user_id, user_role, centre_id
                )
                result = await agent.process_message(content)
                await manager.send_message(session_id, {
                    "type": "complete",
                    "content": result["content"],
                    "session_id": session_id,
                })

    except WebSocketDisconnect:
        manager.disconnect(session_id)
