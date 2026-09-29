"""OS-released lock: one collector per local monitor database."""

import sys
from pathlib import Path
from typing import BinaryIO


class CollectorLock:
    def __init__(self, path: Path):
        self.path = path
        self.handle: BinaryIO | None = None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            handle.close()
            raise RuntimeError("Another collector owns this monitor database") from exc
        self.handle = handle

    def release(self) -> None:
        if self.handle:
            # Closing a process-owned handle releases its OS lock, including on crashes.
            self.handle.close()
            self.handle = None
