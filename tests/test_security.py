"""Tests for the security module (RBAC, encryption, audit, approvals).

Validates security infrastructure components.
"""

import os
import base64
import pytest
import pytest_asyncio
from datetime import datetime, timezone

from security.rbac import Role, has_permission, require_role, PERMISSIONS
from security.encryption import encrypt_field, decrypt_field, encrypt_dict_fields, decrypt_dict_fields
from security.audit import log_action, AuditAction


# Ensure encryption key is set for tests
os.environ.setdefault("ENCRYPTION_KEY", base64.b64encode(os.urandom(32)).decode())


class TestRBAC:
    """Tests for role-based access control."""

    def test_director_has_all_permissions(self) -> None:
        """Director role should have the most permissions."""
        assert has_permission(Role.DIRECTOR, "roster.read")
        assert has_permission(Role.DIRECTOR, "roster.write")
        assert has_permission(Role.DIRECTOR, "approvals.manage")

    def test_educator_limited_permissions(self) -> None:
        """Educator role should have limited permissions."""
        assert has_permission(Role.EDUCATOR, "roster.read")
        assert not has_permission(Role.EDUCATOR, "roster.write")
        assert not has_permission(Role.EDUCATOR, "approvals.manage")

    def test_readonly_minimal_permissions(self) -> None:
        """Readonly role should only have read permissions."""
        assert has_permission(Role.READONLY, "roster.read")
        assert not has_permission(Role.READONLY, "roster.write")
        assert not has_permission(Role.READONLY, "comms.draft")

    def test_require_role_returns_callable(self) -> None:
        """require_role should return a dependency function."""
        dependency = require_role(["admin", "director"])
        assert callable(dependency)


class TestEncryption:
    """Tests for field-level encryption utilities."""

    def test_encrypt_decrypt_roundtrip(self) -> None:
        """Encrypting then decrypting should return original value."""
        original = "sensitive-data-123"
        encrypted = encrypt_field(original)
        decrypted = decrypt_field(encrypted)
        assert decrypted == original

    def test_encrypted_differs_from_plaintext(self) -> None:
        """Encrypted value should not equal plaintext."""
        original = "sensitive-data-123"
        encrypted = encrypt_field(original)
        assert encrypted != original

    def test_encrypted_has_prefix(self) -> None:
        """Encrypted value should start with ENC: prefix."""
        encrypted = encrypt_field("test")
        assert encrypted.startswith("ENC:")

    def test_encrypt_dict_fields(self) -> None:
        """encrypt_dict_fields should only encrypt specified fields."""
        data = {"name": "Alice", "phone": "0412345678", "role": "educator"}
        encrypted = encrypt_dict_fields(data, ["phone"])
        assert encrypted["phone"] != "0412345678"
        assert encrypted["name"] == "Alice"
        assert encrypted["role"] == "educator"

    def test_decrypt_dict_fields(self) -> None:
        """decrypt_dict_fields should restore specified fields."""
        data = {"name": "Alice", "phone": "0412345678", "role": "educator"}
        encrypted = encrypt_dict_fields(data, ["phone"])
        decrypted = decrypt_dict_fields(encrypted, ["phone"])
        assert decrypted["phone"] == "0412345678"


class TestAudit:
    """Tests for audit trail logging."""

    @pytest.mark.asyncio
    async def test_log_action_returns_entry(self) -> None:
        """log_action should return a complete audit entry even without DB."""
        entry = await log_action(
            db=None,  # No DB session — uses fallback logging
            action=AuditAction.ROSTER_VIEW,
            actor_id="user-001",
            actor_role="admin",
            details={"room": "Toddlers"},
        )
        assert isinstance(entry, dict)
        assert entry["action"] == "roster.view"
        assert entry["actor_id"] == "user-001"
        assert "timestamp" in entry
        assert "hash" in entry

    @pytest.mark.asyncio
    async def test_log_action_has_hash(self) -> None:
        """log_action should include a SHA-256 hash for tamper detection."""
        entry = await log_action(
            db=None,
            action=AuditAction.STAFF_QUERY,
            actor_id="user-002",
            actor_role="director",
        )
        assert len(entry["hash"]) == 64  # SHA-256 hex digest length
