"""MCP tools registration."""

from __future__ import annotations

import json
from typing import Any

from mcp.server import Server
from mcp.types import TextContent, Tool

from talk2stindex.logging import get_logger

from . import stindex

logger = get_logger(__name__)

TOOL_SPECS = stindex.TOOL_SPECS

TOOL_HANDLERS = {
    "extract_text": stindex.handle_extract_text,
}


def register_tools(server: Server, *, config=None) -> None:
    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [Tool(**spec) for spec in TOOL_SPECS]

    @server.call_tool()
    async def call_tool(name: str, arguments: Any) -> list[TextContent]:
        handler = TOOL_HANDLERS.get(name)
        if not handler:
            return [
                TextContent(
                    type="text", text=json.dumps({"error": f"Unknown tool: {name}"})
                )
            ]
        try:
            return await handler(arguments or {})
        except Exception as e:
            logger.error(f"Error executing tool {name}: {e}", exc_info=True)
            return [
                TextContent(
                    type="text", text=json.dumps({"error": str(e), "tool": name})
                )
            ]
