from __future__ import annotations

import threading
import time

READ_MAX = 256 * 1024
FULL_WAIT = 1.0


class OutputBuffer:
    def __init__(self, capacity: int) -> None:
        self.capacity = capacity
        self.data = bytearray()
        self.start = 0
        self.acknowledged = 0
        self.closed = False
        self.changed = threading.Condition()

    @property
    def end(self) -> int:
        return self.start + len(self.data)

    def append(self, chunk: bytes) -> bool:
        with self.changed:
            while (
                not self.closed
                and self.end > self.acknowledged
                and self.end - self.acknowledged + len(chunk) > self.capacity
            ):
                self.changed.wait(FULL_WAIT)
            if self.closed:
                return False
            self.data += chunk
            self.changed.notify_all()
            return True

    def read(self, cursor: int, wait: float) -> tuple[bytes, int, bool]:
        deadline = time.monotonic() + wait
        with self.changed:
            cursor = min(cursor, self.end)
            if cursor > self.acknowledged:
                self.acknowledged = cursor
                self._trim()
                self.changed.notify_all()
            while cursor >= self.end and not self.closed:
                left = deadline - time.monotonic()
                if left <= 0:
                    break
                self.changed.wait(left)
            begin = max(cursor, self.start)
            offset = begin - self.start
            chunk = bytes(self.data[offset : offset + READ_MAX])
            return chunk, begin + len(chunk), cursor < self.start

    def drained(self, cursor: int) -> bool:
        with self.changed:
            return self.closed and cursor >= self.end

    def close(self) -> None:
        with self.changed:
            self.closed = True
            self.changed.notify_all()

    def _trim(self) -> None:
        dropped = self.acknowledged - self.start
        if dropped > 0:
            del self.data[:dropped]
            self.start = self.acknowledged
