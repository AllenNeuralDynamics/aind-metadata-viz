"""Shared security helpers for the LLM-backed endpoints.

Three protections, applied to ``/chat``, ``/summary`` and the mounted
``/mcp`` server:

1. Origin allow-listing — only browsers on ``*.allenneuraldynamics.org``
   (plus localhost for development) may make cross-origin calls. Requests
   with no ``Origin`` header (same-origin or non-browser clients) are not
   blocked here; rate limiting is the backstop for those.
2. Rate limiting — configured by the callers to 1 request/second.
3. Structured output — model responses are required to be JSON and the
   answer is pulled out of a known field, so a prompt-injection attempt
   cannot change the *shape* of what we return to the caller.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Allowed browser origins: any subdomain of allenneuraldynamics.org (and
# the apex), with an optional port, plus localhost / 127.0.0.1 for local
# development. Matched with ``re.fullmatch`` (case-insensitive).
ALLOWED_ORIGIN_REGEX = (
    r"https?://"
    r"(([a-z0-9-]+\.)*allenneuraldynamics\.org|localhost|127\.0\.0\.1)"
    r"(:\d+)?"
)

_ORIGIN_RE = re.compile(ALLOWED_ORIGIN_REGEX, re.IGNORECASE)


def is_origin_allowed(origin: Optional[str]) -> bool:
    """Return True if ``origin`` may call the LLM endpoints.

    A missing/blank Origin (same-origin requests, server-to-server, curl)
    is allowed through — CORS only governs cross-origin *browser*
    traffic, and rate limiting protects against non-browser abuse.
    """
    if not origin:
        return True
    return bool(_ORIGIN_RE.fullmatch(origin.strip()))


def origin_error(headers) -> Optional[str]:
    """Return an error message if the request Origin is disallowed."""
    origin = headers.get("origin") if hasattr(headers, "get") else None
    if is_origin_allowed(origin):
        return None
    return "Origin not allowed."


def extract_json_field(text: str, field: str) -> Optional[str]:
    """Pull ``field`` (a string value) out of a JSON object in ``text``.

    The model is instructed to reply with a JSON object such as
    ``{"response": "..."}``. We first try to parse the whole string, then
    fall back to the substring between the first ``{`` and last ``}`` so
    incidental prose around the JSON does not break extraction.

    Returns the field value, or ``None`` if the text is not valid JSON or
    the field is missing / not a string.
    """
    if not text:
        return None

    candidates = [text.strip()]
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidates.append(text[start : end + 1])

    for candidate in candidates:
        try:
            parsed: Any = json.loads(candidate)
        except (ValueError, TypeError):
            continue
        if isinstance(parsed, dict):
            value = parsed.get(field)
            if isinstance(value, str):
                return value.strip()
    return None
