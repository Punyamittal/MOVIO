"""
Bounded async request queue feeding a single loaded TTS model instance.

Phase 3: one GPU worker by default (QUEUE_WORKER_COUNT), structured to scale to N.
Includes backpressure, per-request timeout, and cancellation support.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger("server.queue")


class QueueFullError(Exception):
    """Raised when backpressure rejects a new request."""


class RequestCancelled(Exception):
    """Raised when a request is cancelled before completion."""


class RequestTimeout(Exception):
    """Raised when a request exceeds its timeout."""


@dataclass
class TTSJob:
    job_id: str
    text: str
    voice_style: str
    future: asyncio.Future
    skip_llm: bool = True
    chunked: bool = True
    backend: str | None = None
    target_lang: str | None = None
    enqueued_at: float = field(default_factory=time.perf_counter)
    cancelled: bool = False


class TTSQueue:
    def __init__(
        self,
        worker_fn: Callable[..., Any],
        max_size: int = 32,
        worker_count: int = 1,
        request_timeout_sec: float = 60.0,
    ):
        self.worker_fn = worker_fn
        self.max_size = max_size
        self.worker_count = worker_count
        self.request_timeout_sec = request_timeout_sec
        self._queue: asyncio.Queue[TTSJob | None] = asyncio.Queue(maxsize=max_size)
        self._workers: list[asyncio.Task] = []
        self._jobs: dict[str, TTSJob] = {}
        self._started = False

    async def start(self) -> None:
        if self._started:
            return
        self._started = True
        for i in range(self.worker_count):
            self._workers.append(asyncio.create_task(self._worker_loop(i)))
        logger.info(
            "TTSQueue started workers=%d max_size=%d timeout=%.1fs",
            self.worker_count,
            self.max_size,
            self.request_timeout_sec,
        )

    async def stop(self) -> None:
        for _ in self._workers:
            await self._queue.put(None)
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()
        self._started = False

    async def _worker_loop(self, worker_id: int) -> None:
        while True:
            job = await self._queue.get()
            try:
                if job is None:
                    return
                if job.cancelled:
                    if not job.future.done():
                        job.future.set_exception(RequestCancelled(job.job_id))
                    continue
                try:
                    result = await asyncio.to_thread(
                        self.worker_fn,
                        job.text,
                        job.voice_style,
                        job.skip_llm,
                        job.chunked,
                        job.backend,
                        job.target_lang,
                    )
                    if job.cancelled:
                        if not job.future.done():
                            job.future.set_exception(RequestCancelled(job.job_id))
                    elif not job.future.done():
                        job.future.set_result(result)
                except Exception as exc:  # noqa: BLE001
                    if not job.future.done():
                        job.future.set_exception(exc)
            finally:
                self._queue.task_done()
                self._jobs.pop(getattr(job, "job_id", ""), None)

    async def submit(
        self,
        text: str,
        voice_style: str,
        skip_llm: bool = True,
        chunked: bool = True,
        backend: str | None = None,
        target_lang: str | None = None,
    ) -> Any:
        if not self._started:
            await self.start()
        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        job_id = str(uuid.uuid4())
        job = TTSJob(
            job_id=job_id,
            text=text,
            voice_style=voice_style,
            future=fut,
            skip_llm=skip_llm,
            chunked=chunked,
            backend=backend,
            target_lang=target_lang,
        )
        if self._queue.full():
            raise QueueFullError(
                f"Queue full (max_size={self.max_size}); reject or retry later"
            )
        self._jobs[job_id] = job
        await self._queue.put(job)
        try:
            return await asyncio.wait_for(fut, timeout=self.request_timeout_sec)
        except asyncio.TimeoutError as exc:
            job.cancelled = True
            raise RequestTimeout(
                f"Request {job_id} timed out after {self.request_timeout_sec}s"
            ) from exc

    def cancel(self, job_id: str) -> bool:
        job = self._jobs.get(job_id)
        if not job:
            return False
        job.cancelled = True
        if not job.future.done():
            job.future.set_exception(RequestCancelled(job_id))
        return True

    def stats(self) -> dict:
        return {
            "queued": self._queue.qsize(),
            "max_size": self.max_size,
            "worker_count": self.worker_count,
            "inflight_jobs": len(self._jobs),
        }
