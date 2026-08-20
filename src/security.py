"""Security helpers for untrusted third-party listing data.

All data received from public APIs is untrusted. These helpers provide the
single approved way to put text, URLs, and JSON-derived values into HTML.
"""

from __future__ import annotations

import html
import json
from typing import Any
from urllib.parse import urlparse


# Start strict. Add a hostname only after verifying that it is a real source
# WatchLedger is willing to send visitors to.
ALLOWED_EXTERNAL_SCHEMES = {"https"}


def safe_text(value: Any) -> str:
    """Return a value that is safe to place inside HTML text or attributes."""
    if value is None:
        return ""
    return html.escape(str(value), quote=True)


def safe_external_url(value: Any) -> str:
    """Return an approved external HTTPS URL, or an empty string.

    Never return arbitrary strings to an href or src attribute.
    The empty string means: do not render that link or image.
    """
    if not isinstance(value, str):
        return ""

    value = value.strip()
    if not value or len(value) > 2_048:
        return ""

    try:
        parsed = urlparse(value)
    except ValueError:
        return ""

    # Reject relative URLs, javascript:, data:, file:, and malformed URLs.
    if parsed.scheme.lower() not in ALLOWED_EXTERNAL_SCHEMES:
        return ""
    if not parsed.netloc:
        return ""
    if parsed.username or parsed.password:
        return ""

    return value


def safe_json_script(value: Any) -> str:
    """Serialize data safely for a <script type="application/json"> element.

    Escaping <, >, and & prevents a listing title containing </script> from
    terminating the script element and injecting executable markup.
    """
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return (
        encoded.replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def safe_slug(value: str) -> str:
    """Allow only canonical WatchLedger slugs used in URL routing."""
    if not isinstance(value, str):
        return ""
    if len(value) > 160:
        return ""
    allowed = set("abcdefghijklmnopqrstuvwxyz0123456789-_")
    return value if value and all(char in allowed for char in value) else ""