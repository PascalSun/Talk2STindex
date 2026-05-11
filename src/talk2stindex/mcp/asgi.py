"""ASGI app factory for running Talk2STIndex MCP under Uvicorn workers."""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path

from talk2stindex.logging import get_logger
from talk2stindex.mcp.config import MCPConfig
from talk2stindex.mcp.server import build_server
from talk2stindex.mcp.task_queue import TaskQueue

logger = get_logger(__name__)


def create_app():
    from talk2stindex.logging import setup_logging

    log_level = os.getenv("MCP_LOG_LEVEL", "INFO")
    setup_logging(level=log_level)

    config_path = os.getenv("MCP_CONFIG_PATH")
    config_path_obj = Path(config_path) if config_path else None
    config = MCPConfig.load(config_path_obj)

    app, session_manager, _mcp_server = build_server(config)

    # Queue DB lives in the persistent data volume
    data_dir = Path(os.getenv("MCP_DATA_DIR", "./data"))
    queue_db = data_dir / "queue" / "tasks.db"

    @asynccontextmanager
    async def lifespan(_app):
        from talk2stindex.mcp import server as server_module
        from talk2stindex.mcp.tools.stindex import handle_extract_pdf

        logger.info(f"Worker PID {os.getpid()} starting lifespan")

        # Initialize persistent task queue
        task_queue = TaskQueue(queue_db, max_concurrent=2)
        task_queue.recover_stale()
        server_module._task_queue = task_queue

        # Processing function
        async def process_task(payload: dict):
            await handle_extract_pdf(payload)

        # Start queue worker
        worker_task = asyncio.create_task(task_queue.run_worker(process_task))

        async with session_manager.run():
            yield

        # Shutdown
        task_queue.shutdown()
        await worker_task
        server_module._task_queue = None
        logger.info(f"Worker PID {os.getpid()} lifespan ended cleanly")

    app.router.lifespan_context = lifespan
    return app
