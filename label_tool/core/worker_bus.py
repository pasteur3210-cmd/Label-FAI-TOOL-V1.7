from __future__ import annotations

from dataclasses import dataclass
from queue import Queue, Empty, Full
from typing import Any
import time


@dataclass
class WorkerEvent:
    kind: str
    payload: Any = None
    cycle_id: int = 0
    item: str = ""
    created_at: float = 0.0

    def __post_init__(self):
        if not self.created_at:
            self.created_at = time.time()


class WorkerResultBus:
    """In-process thread-safe transport from workers to Tk main thread.

    Workers may ONLY put events here. Tk widgets / Smart Lock merge are
    performed by the main thread while polling this bus.
    """
    def __init__(self, maxsize: int = 64):
        self._q = Queue(maxsize=maxsize)
        self.dropped = 0

    def put(self, event: WorkerEvent) -> bool:
        try:
            self._q.put_nowait(event)
            return True
        except Full:
            # Result transport must never block recognition threads.
            self.dropped += 1
            return False

    def drain(self, limit: int = 32) -> list[WorkerEvent]:
        out = []
        for _ in range(max(1, int(limit))):
            try:
                out.append(self._q.get_nowait())
            except Empty:
                break
        return out

    def size(self) -> int:
        return self._q.qsize()
