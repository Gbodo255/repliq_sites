"""In-process progress event bus used to stream job progress over WebSockets.

Each replication job gets a :class:`JobChannel` that keeps a bounded history of
events (so a client that connects mid-run still sees recent progress) and fans
out new events to any number of async subscribers.
"""
from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from typing import AsyncIterator


@dataclass
class ProgressEvent:
    job_id: str
    phase: str                     # e.g. "crawl", "assets", "build", "compare"
    message: str
    progress: float = 0.0          # 0..100 overall
    level: str = "info"            # info | warn | error | success
    data: dict = field(default_factory=dict)
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return asdict(self)


class JobChannel:
    def __init__(self, job_id: str, history: int = 500) -> None:
        self.job_id = job_id
        self._history: deque[ProgressEvent] = deque(maxlen=history)
        self._subscribers: set[asyncio.Queue] = set()
        self._closed = False

    @property
    def history(self) -> list[ProgressEvent]:
        return list(self._history)

    def publish(self, event: ProgressEvent) -> None:
        self._history.append(event)
        for q in list(self._subscribers):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:  # pragma: no cover - defensive
                pass

    def close(self) -> None:
        self._closed = True
        for q in list(self._subscribers):
            try:
                q.put_nowait(None)
            except asyncio.QueueFull:  # pragma: no cover
                pass

    async def subscribe(self, replay: bool = True) -> AsyncIterator[ProgressEvent]:
        q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._subscribers.add(q)
        try:
            if replay:
                for ev in list(self._history):
                    yield ev
            if self._closed:
                return
            while True:
                ev = await q.get()
                if ev is None:
                    return
                yield ev
        finally:
            self._subscribers.discard(q)


class EventBus:
    def __init__(self) -> None:
        self._channels: dict[str, JobChannel] = {}
        self._lock = asyncio.Lock()

    def channel(self, job_id: str) -> JobChannel:
        ch = self._channels.get(job_id)
        if ch is None:
            ch = JobChannel(job_id)
            self._channels[job_id] = ch
        return ch

    def emit(self, event: ProgressEvent) -> None:
        self.channel(event.job_id).publish(event)

    def close(self, job_id: str) -> None:
        if job_id in self._channels:
            self._channels[job_id].close()

    def drop(self, job_id: str) -> None:
        self._channels.pop(job_id, None)


# Global singleton bus.
bus = EventBus()
