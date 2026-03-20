"""STIndex extraction tool for MCP."""

from __future__ import annotations

import json

from mcp.types import TextContent

EXTRACT_TEXT_SPEC = {
    "name": "extract_text",
    "description": (
        "Extract spatial and temporal entities from plain text. "
        "Returns structured entities with locations and dates/times found in the text."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "Raw text to extract spatial and temporal information from.",
            },
            "temporal_reference": {
                "type": "string",
                "description": (
                    "ISO 8601 date/datetime used as the reference point for resolving "
                    "relative temporal expressions (e.g. 'last week', 'yesterday'). "
                    "Defaults to the current date if not provided."
                ),
            },
            "spatial_reference": {
                "type": "string",
                "description": (
                    "Geographic context used as the reference for spatial disambiguation "
                    "(e.g. 'Perth, Western Australia'). Helps resolve ambiguous place names."
                ),
            },
        },
        "required": ["text"],
    },
}

TOOL_SPECS = [EXTRACT_TEXT_SPEC]


async def handle_extract_text(arguments: dict) -> list[TextContent]:
    from talk2stindex.core.extraction import extract_text

    result = extract_text(
        text=arguments.get("text", ""),
        temporal_reference=arguments.get("temporal_reference"),
        spatial_reference=arguments.get("spatial_reference"),
    )
    return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]
