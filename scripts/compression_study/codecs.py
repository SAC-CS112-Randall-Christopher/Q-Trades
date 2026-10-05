"""Fixed single-thread profiles, streaming I/O and strict bounded frame decoding."""

import gzip
import hashlib
import importlib.metadata
import os
import platform
import time
import zlib
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, BinaryIO, TypeVar

CHUNK = 64 * 1024
MAX_INPUT = 32 * 1024**2
MAX_WINDOW_BYTES = 32 * 1024**2
ARMS = ("none", "gzip-9", "zstd-1", "zstd-3", "lz4-frame")
T = TypeVar("T")


class StudyError(ValueError):
    """Fail closed, preserving the specimen and earlier results."""


@dataclass(frozen=True)
class Identity:
    length: int
    sha256: str

    def validate(self) -> None:
        if (
            type(self.length) is not int
            or not 0 <= self.length <= MAX_INPUT
            or len(self.sha256) != 64
            or any(c not in "0123456789abcdef" for c in self.sha256)
        ):
            raise StudyError("Invalid declared size or SHA-256")

    def dump(self) -> dict[str, Any]:
        return asdict(self)


class Clock:
    def __init__(self, seconds: float = 60):
        if not 0 < seconds <= 60:
            raise StudyError("Operation deadline must be in (0, 60] seconds")
        self.deadline = time.monotonic() + seconds

    def check(self) -> None:
        if time.monotonic() > self.deadline:
            raise TimeoutError("Study operation deadline exceeded")


class Metrics:
    def __init__(self) -> None:
        self.values: dict[str, dict[str, float]] = {}

    def call(self, name: str, fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        # Gzip's file wrapper invokes our timed sink; exclude nested write time from codec time.
        nested_wall = sum(v["wall_s"] for v in self.values.values())
        nested_cpu = sum(v["cpu_s"] for v in self.values.values())
        wall, cpu = time.perf_counter(), time.process_time()
        try:
            return fn(*args, **kwargs)
        finally:
            nested_wall = sum(v["wall_s"] for v in self.values.values()) - nested_wall
            nested_cpu = sum(v["cpu_s"] for v in self.values.values()) - nested_cpu
            item = self.values.setdefault(name, {"wall_s": 0.0, "cpu_s": 0.0})
            item["wall_s"] += max(0.0, time.perf_counter() - wall - nested_wall)
            item["cpu_s"] += max(0.0, time.process_time() - cpu - nested_cpu)


def profile(arm: str) -> dict[str, Any]:
    if arm == "none":
        return {"codec": "none", "threads": 1}
    if arm == "gzip-9":
        return {
            "codec": "gzip",
            "level": 9,
            "threads": 1,
            "filename": "segment-000000000001.jsonl.partial",
            "mtime": 0,
            "header_note": "Application level 9; fixed study filename/time for reproducibility",
        }
    if arm in ("zstd-1", "zstd-3"):
        return {
            "codec": "zstandard",
            "level": int(arm[-1]),
            "threads": 0,
            "write_checksum": True,
            "write_content_size": True,
            "max_window_bytes": MAX_WINDOW_BYTES,
            "compressed_read_bytes": 1024,
            "max_window_size_argument": MAX_WINDOW_BYTES,
        }
    if arm == "lz4-frame":
        return {
            "codec": "lz4.frame",
            "compression_level": 0,
            "threads": 1,
            "block_size": 64 * 1024,
            "block_linked": True,
            "content_checksum": True,
            "block_checksum": True,
            "auto_flush": False,
            "store_size": True,
        }
    raise StudyError("Unknown codec/profile")


def dependencies() -> dict[str, Any]:
    result: dict[str, Any] = {
        "python": platform.python_version(),
        "architecture": platform.machine(),
        "pointer_bits": __import__("struct").calcsize("P") * 8,
        "os": platform.system(),
        "zlib_build": zlib.ZLIB_VERSION,
        "zlib_runtime": zlib.ZLIB_RUNTIME_VERSION,
        "sqlite": __import__("sqlite3").sqlite_version,
    }
    for name in ("zstandard", "lz4", "psutil", "pydantic", "pytest", "ruff", "mypy"):
        try:
            result[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            result[name] = "unavailable"
    try:
        import zstandard

        result["zstd_native"] = list(zstandard.ZSTD_VERSION)
        result["zstd_backend"] = zstandard.backend
    except ImportError:
        pass
    try:
        import lz4

        result["lz4_native"] = lz4.library_version_string()
    except ImportError:
        pass
    return result


def identity(
    path: Path,
    clock: Clock | None = None,
    *,
    max_bytes: int = MAX_INPUT,
) -> Identity:
    h, length = hashlib.sha256(), 0
    with path.open("rb") as src:
        while block := src.read(CHUNK):
            if clock:
                clock.check()
            length += len(block)
            if length > max_bytes:
                raise StudyError("Specimen exceeds per-file study limit")
            h.update(block)
    return Identity(length, h.hexdigest())


class Sink:
    def __init__(
        self,
        target: BinaryIO,
        limit: int,
        metrics: Metrics,
        clock: Clock,
        fail_after: int | None = None,
    ):
        self.target, self.limit, self.metrics, self.clock = target, limit, metrics, clock
        self.length, self.hash, self.fail_after = 0, hashlib.sha256(), fail_after

    def write(self, block: bytes) -> int:
        self.clock.check()
        if self.length + len(block) > self.limit:
            raise StudyError("Bounded decompression expansion or staging limit exceeded")
        if self.fail_after is not None and self.length + len(block) > self.fail_after:
            import errno

            raise OSError(errno.ENOSPC, "Disposable disk-full simulation")
        written = self.metrics.call("io_write", self.target.write, block)
        if written != len(block):
            raise OSError("Interrupted/short output write")
        self.length += written
        self.hash.update(block)
        return written

    def flush(self) -> None:
        # Codec wrappers may flush here. Durable flush/fsync is a separate phase.
        self.metrics.call("io_write", self.target.flush)


def encode(arm: str, src: BinaryIO, sink: Sink, size: int, metrics: Metrics) -> None:
    settings = profile(arm)
    compressor: Any
    if arm == "gzip-9":
        compressor = metrics.call(
            "codec",
            gzip.GzipFile,
            filename=settings["filename"],
            mode="wb",
            compresslevel=9,
            fileobj=sink,
            mtime=0,
        )
        try:
            while block := metrics.call("io_read", src.read, CHUNK):
                sink.clock.check()
                metrics.call("codec", compressor.write, block)
            metrics.call("codec", compressor.close)
        except BaseException:
            # No close/final trailer after failure: a partial must remain partial.
            compressor.fileobj = None
            raise
        return
    if arm.startswith("zstd-"):
        import zstandard

        context = metrics.call(
            "codec",
            zstandard.ZstdCompressor,
            level=settings["level"],
            threads=0,
            write_checksum=True,
            write_content_size=True,
        )
        compressor = metrics.call("codec", context.compressobj, size=size)
    elif arm == "lz4-frame":
        import lz4.frame

        compressor = metrics.call(
            "codec",
            lz4.frame.LZ4FrameCompressor,
            compression_level=0,
            block_size=lz4.frame.BLOCKSIZE_MAX64KB,
            block_linked=True,
            content_checksum=True,
            block_checksum=True,
            auto_flush=False,
        )
        sink.write(metrics.call("codec", compressor.begin, source_size=size))
    else:
        compressor = None
    while block := metrics.call("io_read", src.read, CHUNK):
        sink.clock.check()
        sink.write(metrics.call("codec", compressor.compress, block) if compressor else block)
    if compressor:
        sink.write(metrics.call("codec", compressor.flush))


def decode(arm: str, src: BinaryIO, sink: Sink, metrics: Metrics) -> None:
    profile(arm)
    if arm == "none":
        while block := metrics.call("io_read", src.read, CHUNK):
            sink.write(block)
        return
    decoder: Any
    if arm == "gzip-9":
        decoder = metrics.call("codec", zlib.decompressobj, 31)
    elif arm.startswith("zstd-"):
        import zstandard

        context = metrics.call(
            "codec",
            zstandard.ZstdDecompressor,
            max_window_size=MAX_WINDOW_BYTES,
        )
        decoder = metrics.call(
            "codec",
            context.decompressobj,
            write_size=CHUNK,
            read_across_frames=False,
        )
    else:
        import lz4.frame

        decoder = metrics.call("codec", lz4.frame.LZ4FrameDecompressor)
    # Zstd's incremental API has no max_length argument. Small compressed feeds,
    # a 32-MiB window cap and the supervisor's hard 512-MiB job limit bound memory.
    read_size = 1024 if arm.startswith("zstd-") else CHUNK
    first_block = True
    while block := metrics.call("io_read", src.read, read_size):
        sink.clock.check()
        if decoder.eof:
            raise StudyError("Trailing or concatenated frame refused")
        if arm.startswith("zstd-"):
            if first_block:
                # Enforce the frame's byte window independently of binding-specific
                # max_window_size units. Pinned cext behavior is covered by regression.
                params = zstandard.get_frame_parameters(block)
                if params.window_size > MAX_WINDOW_BYTES:
                    raise StudyError("Zstandard frame window exceeds study ceiling")
                if (
                    params.content_size
                    not in (
                        zstandard.CONTENTSIZE_UNKNOWN,
                        zstandard.CONTENTSIZE_ERROR,
                    )
                    and params.content_size > sink.limit
                ):
                    raise StudyError("Bounded decompression expansion refused by frame header")
                first_block = False
            sink.write(metrics.call("codec", decoder.decompress, block))
        elif arm == "gzip-9":
            while block:
                sink.write(metrics.call("codec", decoder.decompress, block, CHUNK))
                block = decoder.unconsumed_tail
        else:
            sink.write(metrics.call("codec", decoder.decompress, block, max_length=CHUNK))
            while not decoder.needs_input and not decoder.eof:
                sink.write(metrics.call("codec", decoder.decompress, b"", max_length=CHUNK))
        if decoder.unused_data:
            raise StudyError("Trailing or concatenated frame refused")
    if not decoder.eof:
        raise StudyError("Truncated frame refused")


def transfer(
    arm: str,
    source: Path,
    destination: Path,
    expected: Identity,
    *,
    decompress: bool,
    clock: Clock | None = None,
    fail_after: int | None = None,
) -> dict[str, Any]:
    expected.validate()
    clock, metrics = clock or Clock(), Metrics()
    started, cpu = time.perf_counter(), time.process_time()
    # Compression may grow an incompressible stream. Reserve bounded frame overhead.
    limit = expected.length if decompress else expected.length + expected.length // 8 + CHUNK
    with source.open("rb") as src, destination.open("xb") as target:
        sink = Sink(target, limit, metrics, clock, fail_after)
        try:
            if decompress:
                decode(arm, src, sink, metrics)
            else:
                encode(arm, src, sink, expected.length, metrics)
        except (OSError, StudyError, TimeoutError):
            raise
        except Exception as exc:
            raise StudyError("Invalid compressed frame") from exc
        metrics.call("flush", target.flush)
        metrics.call("flush", os.fsync, target.fileno())
        actual = Identity(sink.length, sink.hash.hexdigest())
    if decompress and actual != expected:
        raise StudyError("Decompressed length or SHA-256 differs")
    return {
        "identity": actual.dump(),
        "phases": metrics.values,
        "wall_s": time.perf_counter() - started,
        "cpu_s": time.process_time() - cpu,
    }
