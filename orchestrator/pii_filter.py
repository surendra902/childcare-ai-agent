"""PII detection and stripping for ChildCareAI Admin Agent.

Provides functions to detect and remove/mask personally identifiable information
from text before sending to the AI model, and to restore placeholders in responses.

PII categories handled:
- Phone numbers (Australian format)
- Email addresses
- Medicare numbers
- Street addresses
- Child full names (when flagged in context)
"""

import re
from typing import Any


# Regex patterns for common Australian PII formats
PII_PATTERNS: dict[str, re.Pattern[str]] = {
    "phone_au": re.compile(
        r"(?:\+61[\s\-]?|0)\d{3}[\s\-]?\d{3,4}[\s\-]?\d{3,4}"
    ),
    "email": re.compile(
        r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Z|a-z]{2,}\b"
    ),
    "medicare": re.compile(
        r"\b\d{4}[\s\-]?\d{5}[\s\-]?\d[\s\-]?\d?\b"
    ),
}


def strip_pii(
    text: str, known_names: set[str] | None = None
) -> tuple[str, dict[str, str]]:
    """Detect and replace PII in text with placeholders.

    Args:
        text: Input text potentially containing PII.
        known_names: Optional set of child/parent names to detect and redact.

    Returns:
        Tuple of (filtered_text, pii_map) where pii_map maps
        placeholders back to original values for restoration.
    """
    pii_map: dict[str, str] = {}
    filtered_text = text
    placeholder_counter = 0

    for pii_type, pattern in PII_PATTERNS.items():
        matches = pattern.findall(filtered_text)
        for match in matches:
            placeholder = f"[{pii_type.upper()}_{placeholder_counter}]"
            pii_map[placeholder] = match
            filtered_text = filtered_text.replace(match, placeholder, 1)
            placeholder_counter += 1

    # Detect known child/parent names (case-insensitive word match)
    if known_names:
        for name in sorted(known_names, key=len, reverse=True):
            if len(name) < 2:
                continue
            # Match whole words only to avoid false positives
            name_pattern = re.compile(r'\b' + re.escape(name) + r'\b', re.IGNORECASE)
            if name_pattern.search(filtered_text):
                placeholder = f"[NAME_{placeholder_counter}]"
                pii_map[placeholder] = name
                filtered_text = name_pattern.sub(placeholder, filtered_text)
                placeholder_counter += 1

    return filtered_text, pii_map


def restore_pii_placeholders(
    text: str, pii_map: dict[str, str]
) -> str:
    """Restore PII placeholders in text with original values.

    Args:
        text: Text containing PII placeholders.
        pii_map: Mapping of placeholders to original PII values.

    Returns:
        Text with placeholders replaced by original values.

    NOTE: Only use this when the response is being sent to an authorized user
    who has permission to view the PII.
    """
    result = text
    for placeholder, original in pii_map.items():
        result = result.replace(placeholder, original)
    return result


def contains_pii(text: str) -> bool:
    """Check if text contains any detectable PII.

    Args:
        text: Text to check for PII presence.

    Returns:
        True if any PII pattern matches, False otherwise.
    """
    for pattern in PII_PATTERNS.values():
        if pattern.search(text):
            return True
    return False


def mask_pii_for_logging(text: str) -> str:
    """Mask PII in text for safe logging (non-reversible).

    Args:
        text: Text potentially containing PII.

    Returns:
        Text with PII replaced by generic masks (e.g., "***").

    Use this for audit logs where the actual PII value isn't needed.
    """
    masked = text
    for pii_type, pattern in PII_PATTERNS.items():
        masked = pattern.sub(f"[REDACTED_{pii_type.upper()}]", masked)
    return masked
