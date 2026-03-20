"""ASGI app factory for running Talk2STIndex MCP under Uvicorn workers."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from talk2stindex.logging import get_logger
from talk2stindex.mcp.config import MCPConfig
from talk2stindex.mcp.server import build_server

logger = get_logger(__name__)


def create_app():
    from talk2stindex.logging import setup_logging

    log_level = os.getenv("MCP_LOG_LEVEL", "INFO")
    setup_logging(level=log_level)

    config_path = os.getenv("MCP_CONFIG_PATH")
    config_path_obj = Path(config_path) if config_path else None
    config = MCPConfig.load(config_path_obj)

    app, session_manager, _mcp_server = build_server(config)

    @asynccontextmanager
    async def lifespan(_app):
        logger.info(f"Worker PID {os.getpid()} starting lifespan")
        async with session_manager.run():
            yield
        logger.info(f"Worker PID {os.getpid()} lifespan ended cleanly")

    app.router.lifespan_context = lifespan
    return app
