"""Audited tool registry exposed to /chat and /mcp.

This module imports the aind-data-mcp server (which registers all its
tools on a shared FastMCP instance), then disables the NWB tools that
are not safe to expose:

- ``identify_nwb_contents_in_code_ocean``: reads from a hard-coded /data
  filesystem path; not meaningful outside Code Ocean.
- ``identify_nwb_contents_with_s3_link``: accepts an arbitrary S3 link
  and lists / loads its contents, which lets an external caller probe
  any S3 path our credentials can reach.

Every other registered tool is read-only and safe to expose.
"""

from __future__ import annotations

import json
import logging
from typing import Any

# Importing this module triggers the @mcp.tool() decorators across all
# the tool submodules in aind_data_mcp.
import aind_data_mcp.data_access_server  # noqa: F401

from aind_data_mcp.mcp_instance import mcp

logger = logging.getLogger(__name__)

DISABLED_TOOLS: frozenset[str] = frozenset(
    {
        "identify_nwb_contents_in_code_ocean",
        "identify_nwb_contents_with_s3_link",
    }
)

# Apply the disable transform exactly once at import time so it affects
# both the in-process chat agent and the mounted MCP HTTP endpoint.
mcp.disable(names=set(DISABLED_TOOLS))


async def list_allowed_tools() -> list:
    """Return FastMCP Tool objects that callers are permitted to use."""
    tools = await mcp.list_tools()
    return [t for t in tools if t.name not in DISABLED_TOOLS]


def to_bedrock_tool_spec(tool) -> dict:
    """Convert a FastMCP Tool to a Bedrock Converse toolSpec block."""
    schema = tool.parameters or {"type": "object", "properties": {}}
    # Bedrock rejects schemas with `additionalProperties: false` AND no
    # `properties`. Strip that combo defensively.
    if not schema.get("properties") and "additionalProperties" in schema:
        schema = dict(schema)
        schema.pop("additionalProperties", None)
    description = (tool.description or tool.name).strip()
    # Bedrock caps tool description at 1024 chars.
    if len(description) > 1024:
        description = description[:1021] + "..."
    return {
        "toolSpec": {
            "name": tool.name,
            "description": description,
            "inputSchema": {"json": schema},
        }
    }


def _serialize_tool_result(result, max_bytes: int) -> tuple[str, bool]:
    """Convert a FastMCP ToolResult to a text payload.

    Returns (text, is_error). Text is truncated to ``max_bytes`` so a
    chatty tool can't flood the model context.
    """
    is_error = bool(getattr(result, "is_error", False))
    parts: list[str] = []
    for block in getattr(result, "content", []) or []:
        text = getattr(block, "text", None)
        if text is not None:
            parts.append(text)
            continue
        parts.append(repr(block))
    text = "\n".join(parts) if parts else ""
    if not text and getattr(result, "structured_content", None) is not None:
        try:
            text = json.dumps(result.structured_content, default=str)
        except Exception:
            text = str(result.structured_content)
    if len(text) > max_bytes:
        text = text[:max_bytes] + f"\n...[truncated, {len(text)} bytes total]"
    return text, is_error


async def invoke_tool(
    name: str,
    arguments: dict[str, Any] | None,
    *,
    max_bytes: int,
) -> tuple[str, bool]:
    """Run a registered tool by name with the given arguments.

    Returns (text_payload, is_error). Raises ``KeyError`` if ``name`` is
    not in the allowlist.
    """
    if name in DISABLED_TOOLS:
        raise KeyError(f"Tool '{name}' is not available.")

    tool = await mcp.get_tool(name)
    if tool is None:
        raise KeyError(f"Unknown tool '{name}'.")

    args = arguments or {}
    try:
        result = await tool.run(args)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Tool '%s' raised", name)
        return (
            f"Tool '{name}' raised an exception: {type(exc).__name__}: {exc}",
            True,
        )
    return _serialize_tool_result(result, max_bytes)
