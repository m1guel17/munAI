"""Per-session serial processing queues to prevent concurrent JSONL corruption."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

log = logging.getLogger(__name__)


class LaneQueue:
    """Ensures messages for the same session are processed one at a time.

    Each session gets its own asyncio.Queue and a dedicated consumer task.
    Work items submitted to the same session_key are executed serially,
    even if multiple messages arrive simultaneously.

    This guarantees:
    - No two turns for the same session run concurrently.
    - JSONL session files are never written from two coroutines at once.
    """

    def __init__(self) -> None:
        self._queues: dict[str, asyncio.Queue[Callable[[], Awaitable[Any]]]] = {}
        self._consumers: dict[str, asyncio.Task[None]] = {}

    async def submit(
        self,
        session_key: str,
        work: Callable[[], Awaitable[Any]],
    ) -> None:
        """Submit a coroutine factory to be executed serially for session_key.

        The work callable must be a zero-argument async function (coroutine factory).
        It will be called by the consumer task, not by the caller of submit().
        """
        if session_key not in self._queues:
            self._queues[session_key] = asyncio.Queue()
            self._consumers[session_key] = asyncio.create_task(
                self._consume(session_key),
                name=f"lane-consumer:{session_key}",
            )
        await self._queues[session_key].put(work)

    async def _consume(self, session_key: str) -> None:
        """Consumer loop: pull and execute work items one at a time."""
        queue = self._queues[session_key]
        while True:
            work = await queue.get()
            try:
                await work()
            except Exception:
                log.exception("Unhandled error in lane consumer for %s", session_key)
            finally:
                queue.task_done()

    async def shutdown(self) -> None:
        """Cancel all consumer tasks (call on gateway shutdown)."""
        for task in self._consumers.values():
            task.cancel()
        if self._consumers:
            await asyncio.gather(*self._consumers.values(), return_exceptions=True)
        self._consumers.clear()
        self._queues.clear()
