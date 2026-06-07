"""Authentication, RBAC, and rate limiting middleware for ChildCareAI Admin Agent.

Provides middleware components for:
- JWT token validation
- Role-based access control enforcement
- Per-user rate limiting
- Request/response audit logging
"""

import time
from collections import defaultdict
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from config import settings


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Simple in-memory rate limiter per IP address.

    TODO: Replace with Redis-backed rate limiter for production deployments.
    """

    def __init__(self, app, max_requests: int | None = None) -> None:
        super().__init__(app)
        self.max_requests = max_requests or settings.RATE_LIMIT_PER_MINUTE
        self._requests: dict[str, list[float]] = defaultdict(list)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Check rate limit before processing request."""
        client_ip = request.client.host if request.client else "unknown"
        now = time.time()
        window_start = now - 60.0

        # Clean old entries
        self._requests[client_ip] = [
            t for t in self._requests[client_ip] if t > window_start
        ]

        if len(self._requests[client_ip]) >= self.max_requests:
            return Response(
                content='{"detail": "Rate limit exceeded"}',
                status_code=429,
                media_type="application/json",
            )

        self._requests[client_ip].append(now)
        response = await call_next(request)
        return response


class AuthMiddleware(BaseHTTPMiddleware):
    """JWT authentication middleware.

    TODO: Implement full JWT validation with:
    - Token extraction from Authorization header
    - Signature verification using JWT_SECRET
    - Token expiry checking
    - User context injection into request state
    """

    def validate_jwt(self, token: str) -> dict:
        from jose import jwt, JWTError
        try:
            payload = jwt.decode(token, settings.JWT_SECRET, algorithms=["HS256"])
            return payload
        except JWTError:
            return None

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Validate JWT token and attach user context to request."""
        # Skip auth for health check, docs, frontend, demo endpoints, and static files
        skip_paths = ("/health", "/docs", "/redoc", "/openapi.json", "/", "/chat", "/favicon.ico")
        if (request.url.path in skip_paths
            or request.url.path.startswith("/static")
            or request.url.path.startswith("/api/v1/demo/")):
            return await call_next(request)

        token = request.headers.get("Authorization", "").replace("Bearer ", "")
        if token:
            user = self.validate_jwt(token)
            if user:
                request.state.user = user
            else:
                return Response(
                    content='{"detail": "Invalid or expired token"}',
                    status_code=401,
                    media_type="application/json",
                )
        else:
            if settings.DEBUG:
                # Dev-only fallback — NEVER active in production
                request.state.user = {"id": "dev-user", "role": "director", "name": "Dev User", "centre_id": "centre_1"}
            else:
                return Response(
                    content='{"detail": "Authentication required"}',
                    status_code=401,
                    media_type="application/json",
                )

        response = await call_next(request)
        return response
