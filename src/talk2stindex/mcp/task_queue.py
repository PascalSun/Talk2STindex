"""Persistent task queue backed by SQLite.

Tasks survive service restarts. On startup, any tasks left in 'running'
state (from a crash) are reset to 'pending' and reprocessed.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Coroutine

from talk2stindex.logging import get_logger

logger = get_logger(__name__)


class TaskQueue:
    """SQLite-backed persistent task queue with concurrency control."""

    def __init__(self, db_path: Path, max_concurrent: int = 2):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.max_concurrent = max_concurrent
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._new_task_event = asyncio.Event()
        self._shutdown = False
        self._conn = self._init_db()

    def _init_db(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                payload TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at REAL NOT NULL,
                started_at REAL,
                completed_at REAL,
                error TEXT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)")
        conn.commit()
        return conn

    def enqueue(self, payload: dict) -> str:
        """Insert a new pending task. Returns task ID."""
        task_id = str(uuid.uuid4())
        self._conn.execute(
            "INSERT INTO tasks (id, payload, status, created_at) VALUES (?, ?, 'pending', ?)",
            (task_id, json.dumps(payload), time.time()),
        )
        self._conn.commit()
        self._new_task_event.set()
        return task_id

    def recover_stale(self) -> int:
        """Reset any 'running' tasks back to 'pending' (crash recovery on startup)."""
        cur = self._conn.execute(
            "UPDATE tasks SET status='pending', started_at=NULL WHERE status='running'"
        )
        self._conn.commit()
        count = cur.rowcount
        if count:
            logger.info(f"Recovered {count} stale task(s) from previous run")
            self._new_task_event.set()
        return count

    def claim_next(self) -> tuple[str, dict] | None:
        """Claim the oldest pending task. Returns (task_id, payload) or None."""
        row = self._conn.execute(
            "SELECT id, payload FROM tasks WHERE status='pending' ORDER BY created_at LIMIT 1"
        ).fetchone()
        if not row:
            return None
        task_id, payload_json = row
        self._conn.execute(
            "UPDATE tasks SET status='running', started_at=? WHERE id=?",
            (time.time(), task_id),
        )
        self._conn.commit()
        return task_id, json.loads(payload_json)

    def mark_done(self, task_id: str):
        self._conn.execute(
            "UPDATE tasks SET status='done', completed_at=? WHERE id=?",
            (time.time(), task_id),
        )
        self._conn.commit()

    def mark_failed(self, task_id: str, error: str):
        self._conn.execute(
            "UPDATE tasks SET status='failed', completed_at=?, error=? WHERE id=?",
            (time.time(), error[:2000], task_id),
        )
        self._conn.commit()

    def pending_count(self) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) FROM tasks WHERE status='pending'"
        ).fetchone()
        return row[0] if row else 0

    def cleanup_old(self, max_age_days: int = 7):
        """Delete completed/failed tasks older than max_age_days."""
        cutoff = time.time() - (max_age_days * 86400)
        cur = self._conn.execute(
            "DELETE FROM tasks WHERE status IN ('done', 'failed') AND completed_at < ?",
            (cutoff,),
        )
        self._conn.commit()
        if cur.rowcount:
            logger.info(f"Cleaned up {cur.rowcount} old task(s)")

    def shutdown(self):
        self._shutdown = True
        self._new_task_event.set()

    async def run_worker(
        self,
        process_fn: Callable[[dict], Coroutine[Any, Any, None]],
    ):
        """Main worker loop. Runs until shutdown() is called."""
        logger.info(
            f"Task queue worker started (db={self.db_path}, max_concurrent={self.max_concurrent}, "
            f"pending={self.pending_count()})"
        )
        cleanup_counter = 0

        while not self._shutdown:
            try:
                await asyncio.wait_for(self._new_task_event.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                pass
            self._new_task_event.clear()

            # Dispatch pending tasks up to semaphore limit
            while not self._shutdown:
                claimed = self.claim_next()
                if not claimed:
                    break
                task_id, payload = claimed
                await self._semaphore.acquire()
                asyncio.create_task(self._execute(task_id, payload, process_fn))

            # Periodic cleanup
            cleanup_counter += 1
            if cleanup_counter >= 720:  # ~every hour at 5s interval
                cleanup_counter = 0
                self.cleanup_old()

        logger.info("Task queue worker stopped")

    async def _execute(
        self,
        task_id: str,
        payload: dict,
        process_fn: Callable[[dict], Coroutine[Any, Any, None]],
    ):
        """Run one task, update status, release semaphore."""
        pdf_id = payload.get("pdf_id", "?")
        try:
            await process_fn(payload)
            self.mark_done(task_id)
            logger.info(f"Task {task_id} (pdf_id={pdf_id}) completed")
        except Exception as e:
            logger.error(f"Task {task_id} (pdf_id={pdf_id}) failed: {e}", exc_info=True)
            self.mark_failed(task_id, str(e))
        finally:
            self._semaphore.release()
            self._new_task_event.set()
