"""Bounded lifecycle for the sole owned read-only financial monitoring child."""

import asyncio
import json
import multiprocessing
import time
from collections.abc import Callable
from contextlib import suppress
from multiprocessing.process import BaseProcess
from threading import Thread
from typing import Any, Protocol

from trading.financial_readback import FinancialReadback

SAMPLE_SECONDS = 15.0
DRAIN_SECONDS = 4.0
TERMINATE_SECONDS = 1.0
MAX_RECEIPT_BYTES = 2 * 1024**2
FRAME_BYTES = 256  # Header + frame remain below POSIX's minimum atomic pipe write size.


class ReadbackPipe(Protocol):
    """Common bounded IPC methods on POSIX Connection and Windows PipeConnection."""

    def send(self, value: Any) -> None: ...
    def recv(self) -> Any: ...
    def send_bytes(self, value: bytes) -> None: ...
    def recv_bytes(self, maxlength: int) -> bytes: ...
    def poll(self, timeout: float = 0) -> bool: ...
    def close(self) -> None: ...


class ReadbackChannels:
    """Two simplex pipes: small writes are atomic, unlike a duplex POSIX socketpair."""

    def __init__(self, incoming: ReadbackPipe, outgoing: ReadbackPipe):
        self.incoming, self.outgoing = incoming, outgoing

    def send(self, value: Any) -> None:
        self.outgoing.send(value)

    def recv(self) -> Any:
        return self.incoming.recv()

    def send_bytes(self, value: bytes) -> None:
        self.outgoing.send_bytes(value)

    def recv_bytes(self, maxlength: int) -> bytes:
        return self.incoming.recv_bytes(maxlength)

    def poll(self, timeout: float = 0) -> bool:
        return self.incoming.poll(timeout)

    def close(self) -> None:
        self.incoming.close()
        self.outgoing.close()


def _send(pipe: ReadbackPipe, kind: bytes, value: Any) -> None:
    content = json.dumps(value).encode()
    if len(content) > MAX_RECEIPT_BYTES:
        kind, content = b"E", b'"Financial refresh exceeded its receipt budget"'
    # Small atomic pipe messages keep poll/receive bounded even if the child
    # stops between packets. Never receive a partial multi-megabyte frame.
    for offset in range(0, len(content), FRAME_BYTES):
        chunk = content[offset : offset + FRAME_BYTES]
        final = offset + len(chunk) == len(content)
        pipe.send_bytes(kind + bytes([final]) + chunk)


def readback_child(pipe: ReadbackPipe, dsn: str) -> None:
    """No financial owner is inherited; spawn uses a private local IPC handle."""
    reader = FinancialReadback.from_dsn(dsn)
    work: Thread | None = None
    stopping = False

    def sample(audit: bool) -> None:
        try:
            result = reader.sample(
                audit=audit, publish_audit=lambda value: _send(pipe, b"A", value)
            )
            _send(pipe, b"S", result)
        except Exception:
            # Never expose connection strings, credentials or provider text.
            _send(pipe, b"E", "Durable financial monitoring query unavailable")

    try:
        while True:
            if stopping and (work is None or not work.is_alive()):
                break
            if pipe.poll(0.01):
                command, value = pipe.recv()
                if command == "stop":
                    stopping = True
                    with suppress(Exception):
                        reader.cancel()
                elif command == "sample" and not stopping:
                    if work is not None and work.is_alive():
                        raise RuntimeError("Overlapping readback request")
                    work = Thread(target=sample, args=(value,), daemon=True)
                    work.start()
    finally:
        # Only the idle/completed reader closes its connection. If this worker
        # stalls, the parent terminates this exact process instead of racing it.
        if work is None or not work.is_alive():
            reader.close()
        pipe.close()


class ReadbackWorker:
    def __init__(self, reader: FinancialReadback):
        self._dsn = reader._dsn
        self._process: BaseProcess | None = None
        self._pipe: ReadbackPipe | None = None
        self.last_shutdown: dict[str, Any] | None = None

    def _start(self) -> None:
        context = multiprocessing.get_context("spawn")
        parent_in, child_out = context.Pipe(duplex=False)
        child_in, parent_out = context.Pipe(duplex=False)
        parent = ReadbackChannels(parent_in, parent_out)
        child = ReadbackChannels(child_in, child_out)
        process = context.Process(target=readback_child, args=(child, self._dsn), daemon=True)
        try:
            process.start()
        except BaseException:
            parent.close()
            raise
        finally:
            child.close()
        self._process, self._pipe = process, parent

    async def sample(
        self, *, audit: bool, publish_audit: Callable[[dict[str, Any]], None]
    ) -> dict[str, Any]:
        deadline = time.monotonic() + SAMPLE_SECONDS
        if self._process is None:
            self._start()
        assert self._pipe is not None and self._process is not None
        self._pipe.send(("sample", audit))
        content = bytearray()
        message_kind: bytes | None = None
        while time.monotonic() < deadline:
            if self._pipe.poll():
                packet = self._pipe.recv_bytes(FRAME_BYTES + 2)
                if (
                    len(packet) < 2
                    or packet[:1] not in (b"A", b"S", b"E")
                    or packet[1] not in (0, 1)
                ):
                    raise OSError("Invalid financial readback receipt")
                kind, final = packet[:1], packet[1]
                if (
                    message_kind not in (None, kind)
                    or len(content) + len(packet) - 2 > MAX_RECEIPT_BYTES
                ):
                    raise OSError("Invalid financial readback receipt")
                message_kind = kind
                content.extend(packet[2:])
                if not final:
                    continue
                try:
                    value = json.loads(content)
                except (ValueError, UnicodeError) as exc:
                    raise OSError("Invalid financial readback receipt") from exc
                content, message_kind = bytearray(), None
                if kind == b"A":
                    if not isinstance(value, dict):
                        raise OSError("Invalid financial audit receipt")
                    publish_audit(value)
                elif kind == b"S":
                    if (
                        not isinstance(value, dict)
                        or not {
                            "observed_at", "completed_at", "elapsed_ms",
                            "stages_ms", "refresh_errors"
                        } <= value.keys()
                        or not isinstance(value["stages_ms"], dict)
                        or not isinstance(value["refresh_errors"], dict)
                    ):
                        raise OSError("Invalid financial sample receipt")
                    return dict(value)
                else:
                    raise OSError("Durable financial monitoring query unavailable")
            if not self._process.is_alive():
                raise OSError("Owned financial reader stopped")
            await asyncio.sleep(0.01)
        raise TimeoutError("Owned financial readback exceeded its operation deadline")

    async def close(self) -> dict[str, Any]:
        process, pipe = self._process, self._pipe
        if process is None:
            return self.last_shutdown or {"status": "not_started"}
        if self.last_shutdown and self.last_shutdown["status"] == "termination_failed":
            raise RuntimeError("Owned financial reader shutdown previously failed")
        started = time.monotonic()
        assert pipe is not None
        with suppress(OSError):
            pipe.send(("stop", None))
        deadline = started + DRAIN_SECONDS
        cancelled = False
        # Repeated cancellation does not extend the fixed drain deadline.
        while process.is_alive() and time.monotonic() < deadline:
            with suppress(OSError, EOFError):
                if pipe.poll():
                    pipe.recv_bytes(FRAME_BYTES + 2)
            try:
                await asyncio.sleep(0.01)
            except asyncio.CancelledError:
                cancelled = True
        status = "drained"
        if process.is_alive():
            status = "terminated_owned_reader"
            process.terminate()  # Only this original child handle; never a backend lookup.
            deadline = time.monotonic() + TERMINATE_SECONDS
            while process.is_alive() and time.monotonic() < deadline:
                try:
                    await asyncio.sleep(0.01)
                except asyncio.CancelledError:
                    cancelled = True
        if process.is_alive():
            # Retain ownership and report failure; never silently abandon/restart.
            self.last_shutdown = {
                "status": "termination_failed",
                "elapsed_seconds": round(time.monotonic() - started, 3),
            }
            raise RuntimeError("Owned financial reader did not terminate within shutdown budget")
        process.join(timeout=0)
        exitcode = process.exitcode
        process.close()
        pipe.close()
        self._process, self._pipe = None, None
        self.last_shutdown = {
            "status": status,
            "exitcode": exitcode,
            "elapsed_seconds": round(time.monotonic() - started, 3),
        }
        # A cancel arriving during ordinary recovery must still stop its caller.
        # Defer it until cleanup finishes, rather than swallowing the request.
        if cancelled:
            raise asyncio.CancelledError
        return self.last_shutdown
