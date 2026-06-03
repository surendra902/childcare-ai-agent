"""Role-based access control for ChildCareAI Admin Agent.

Defines roles, permissions, and access control decorators/dependencies
for protecting API endpoints based on staff roles.

Roles:
- director: Full access to all features including approvals
- admin: Roster management, communications, staff queries
- educator: Limited access — own schedule, parent comms for their room
- readonly: View-only access to non-sensitive information
"""

from enum import Enum
from typing import Any, Callable

from fastapi import Depends, HTTPException, Request, status


class Role(str, Enum):
    """Staff roles within the childcare centre."""

    DIRECTOR = "director"
    ADMIN = "admin"
    EDUCATOR = "educator"
    READONLY = "readonly"


# Permission matrix: role -> set of allowed actions
PERMISSIONS: dict[Role, set[str]] = {
    Role.DIRECTOR: {
        "roster.read",
        "roster.write",
        "roster.approve",
        "staff.read",
        "staff.write",
        "comms.draft",
        "comms.send",
        "comms.approve",
        "reports.read",
        "settings.manage",
        "approvals.manage",
    },
    Role.ADMIN: {
        "roster.read",
        "roster.write",
        "staff.read",
        "comms.draft",
        "comms.send",
        "reports.read",
    },
    Role.EDUCATOR: {
        "roster.read",
        "staff.read_own",
        "comms.draft",
    },
    Role.READONLY: {
        "roster.read",
        "reports.read",
    },
}


def has_permission(role: Role, permission: str) -> bool:
    """Check if a role has a specific permission."""
    return permission in PERMISSIONS.get(role, set())


def require_role(allowed_roles: list[str]) -> Callable:
    """FastAPI dependency that enforces role-based access.

    Args:
        allowed_roles: List of role names that are permitted to access the endpoint.

    Returns:
        A dependency function for use with FastAPI's Depends().

    TODO: Extract user role from JWT claims in request state.
    """

    async def _check_role(request: Request) -> dict[str, Any]:
        """Verify the current user has one of the allowed roles."""
        user = getattr(request.state, "user", None)
        if user is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
        if user.get("role") not in allowed_roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
        return user

    return _check_role
