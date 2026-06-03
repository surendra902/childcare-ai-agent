"""Field-level encryption utilities for ChildCareAI Admin Agent.

Provides AES-256-GCM encryption for sensitive fields (PII) stored in the database.
Ensures data-at-rest protection for child names, parent contact details, etc.
"""

import base64
from typing import Any

from config import settings

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import os


def get_encryption_key() -> bytes:
    """Decode the base64-encoded encryption key from settings.

    Returns:
        Raw 32-byte encryption key.

    Raises:
        ValueError: If the key is not properly configured.

    TODO: Add key rotation support with key versioning.
    """
    if not settings.ENCRYPTION_KEY:
        raise ValueError("ENCRYPTION_KEY not configured")
    return base64.b64decode(settings.ENCRYPTION_KEY)


def encrypt_field(plaintext: str) -> str:
    """Encrypt a plaintext string for database storage.

    Args:
        plaintext: The sensitive value to encrypt.

    Returns:
        Base64-encoded ciphertext string (nonce + ciphertext + tag).
    """
    nonce = os.urandom(12)
    key = get_encryption_key()
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode('utf-8'), None)
    return f"ENC:{base64.b64encode(nonce + ciphertext).decode('ascii')}"


def decrypt_field(ciphertext: str) -> str:
    """Decrypt an encrypted field value from database storage.

    Args:
        ciphertext: Base64-encoded encrypted string.

    Returns:
        Decrypted plaintext string.

    Raises:
        ValueError: If decryption fails (tampered data or wrong key).

    TODO: Implement AES-256-GCM decryption:
    - Decode base64
    - Extract nonce (first 12 bytes)
    - Decrypt with AESGCM
    """
    if not ciphertext.startswith("ENC:"):
        raise ValueError("Invalid ciphertext format")
        
    try:
        raw_data = base64.b64decode(ciphertext[4:])
        nonce = raw_data[:12]
        encrypted_data = raw_data[12:]
        
        key = get_encryption_key()
        aesgcm = AESGCM(key)
        plaintext_bytes = aesgcm.decrypt(nonce, encrypted_data, None)
        return plaintext_bytes.decode('utf-8')
    except Exception as e:
        raise ValueError(f"Decryption failed: {e}")


def encrypt_dict_fields(
    data: dict[str, Any], sensitive_fields: list[str]
) -> dict[str, Any]:
    """Encrypt specified fields within a dictionary.

    Args:
        data: Dictionary containing fields to encrypt.
        sensitive_fields: List of field names to encrypt.

    Returns:
        New dictionary with specified fields encrypted.
    """
    result = data.copy()
    for field in sensitive_fields:
        if field in result and result[field] is not None:
            result[field] = encrypt_field(str(result[field]))
    return result


def decrypt_dict_fields(
    data: dict[str, Any], sensitive_fields: list[str]
) -> dict[str, Any]:
    """Decrypt specified fields within a dictionary.

    Args:
        data: Dictionary containing encrypted fields.
        sensitive_fields: List of field names to decrypt.

    Returns:
        New dictionary with specified fields decrypted.
    """
    result = data.copy()
    for field in sensitive_fields:
        if field in result and result[field] is not None:
            result[field] = decrypt_field(str(result[field]))
    return result
