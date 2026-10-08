"""Study-owned scratch accounting and read-only workload observations."""

import json
import os
import shutil
import time
from pathlib import Path
from typing import Any

import psutil

from trading.research_storage import volume

from .codecs import StudyError

MEMORY_LIMIT = 512 * 1024**2
SCRATCH_LIMIT = 1024**3


class Scratch:
    def __init__(self, path: Path, token: str, live_root: Path):
        if not path.is_absolute() or not live_root.is_absolute():
            raise StudyError("Scratch and excluded live root must be explicit absolute paths")
        for component in (path, *path.parents):
            if component.is_symlink() or (
                os.name == "nt" and component.stat().st_file_attributes & 0x400
            ):
                raise StudyError("Redirected scratch refused")
            if (component / ".git").exists():
                raise StudyError("Private scratch must be outside every Git checkout")
        self.path = path.resolve()
        live = live_root.resolve()
        if self.path == live or self.path.is_relative_to(live) or live.is_relative_to(self.path):
            raise StudyError("Scratch overlaps operating research storage")
        if os.name == "nt" and self.path.drive.upper() != "G:":
            raise StudyError("Initial Windows study requires G:; no C: spill")
        marker = path / "study-owned.json"
        if marker.stat().st_size > 4096:
            raise StudyError("Scratch marker exceeds bound")
        owned = json.loads(marker.read_text(encoding="utf-8-sig"))
        if (
            owned.get("owner_token") != token
            or owned.get("lane") != "temporary-lossless-compression-study"
        ):
            raise StudyError("Scratch ownership is unknown")
        if owned.get("max_scratch_bytes") != SCRATCH_LIMIT:
            raise StudyError("Scratch study ceiling differs")
        self.volume_identity = owned["volume_identity"]
        self.reserve = max(5 * 1024**3, owned["min_free_bytes"])
        self.work = self.path / "work"
        self.work.mkdir(exist_ok=True)
        # Environment/cache are frozen for a run; include them in the 1-GiB allowance.
        self.static_bytes = sum(
            p.stat().st_size
            for p in self.path.rglob("*")
            if p.is_file() and not p.is_relative_to(self.work)
        )
        self.peak_bytes = 0
        self.check()

    def check(self, additional: int = 0) -> int:
        observed = volume(self.path)
        if observed["identity"] != self.volume_identity:
            raise StudyError("Scratch volume identity changed")
        if shutil.disk_usage(self.path).free < self.reserve + SCRATCH_LIMIT:
            raise StudyError("Study would consume the operating free-space reserve")
        usage = self.static_bytes + sum(
            p.stat().st_size for p in self.work.rglob("*") if p.is_file()
        )
        if usage + additional > SCRATCH_LIMIT:
            raise StudyError("Study scratch ceiling exceeded")
        self.peak_bytes = max(self.peak_bytes, usage)
        return usage


def allocation(path: Path) -> int | None:
    if os.name != "nt":
        blocks = getattr(path.stat(), "st_blocks", None)
        return blocks * 512 if blocks is not None else None
    import ctypes
    from ctypes import wintypes

    # Compressed/sparse/reparse streams require separate allocation accounting.
    # The study never turns on those filesystem features.
    if path.stat().st_file_attributes & (0x800 | 0x200 | 0x400):
        return None

    class StandardInfo(ctypes.Structure):
        _fields_ = [
            ("allocated", ctypes.c_int64),
            ("end_of_file", ctypes.c_int64),
            ("links", wintypes.DWORD),
            ("delete_pending", ctypes.c_ubyte),
            ("directory", ctypes.c_ubyte),
        ]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.GetFileInformationByHandleEx.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    kernel.GetFileInformationByHandleEx.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.CreateFileW(str(path), 0x80, 7, None, 3, 0, None)
    if handle in (None, ctypes.c_void_p(-1).value):
        raise OSError("Cannot open specimen for allocation observation")
    try:
        info = StandardInfo()
        if not kernel.GetFileInformationByHandleEx(
            handle, 1, ctypes.byref(info), ctypes.sizeof(info)
        ):
            raise OSError("Physical data-stream allocation observation failed")
        return int(info.allocated)
    finally:
        kernel.CloseHandle(handle)


def own_memory() -> dict[str, Any]:
    proc = psutil.Process()
    memory = proc.memory_info()
    cpu = proc.cpu_times()
    io = proc.io_counters()
    return {
        "rss_bytes": memory.rss,
        "peak_working_set_bytes": getattr(memory, "peak_wset", None),
        "peak_commit_bytes": getattr(memory, "peak_pagefile", None),
        "priority_class": int(proc.nice()) if os.name == "nt" else proc.nice(),
        "threads_observed": proc.num_threads(),
        "peak_scope": "one child operation including imports, correctness, codec and read work",
        "process_cpu_s": cpu.user + cpu.system,
        "process_io": {
            name: getattr(io, name, None)
            for name in ("read_count", "write_count", "read_bytes", "write_bytes")
        },
        "io_scope": "process counters include imports; not physical device traffic",
    }


def workloads() -> dict[str, Any]:
    heavy, unknown = [], 0
    me = psutil.Process()
    ignored = {me.pid, *(p.pid for p in me.parents())}
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        if proc.pid in ignored:
            continue
        name = (proc.info["name"] or "").lower()
        if name not in {"python.exe", "pythonw.exe", "node.exe", "ollama.exe", "git.exe"}:
            continue
        args = proc.info["cmdline"]
        if args is None:
            unknown += 1
            continue
        command = " ".join(args).lower()
        # Classify without publishing command lines, paths, credentials or PIDs.
        role = next(
            (
                label
                for word, label in (
                    ("pytest", "foreign-tests"),
                    ("qualification", "qualification"),
                    ("benchmark", "benchmark"),
                    ("acceptance", "acceptance"),
                    ("peft", "model-work"),
                    ("transformers", "model-work"),
                    ("training", "model-work"),
                    ("vite build", "build"),
                    ("npm run build", "build"),
                    ("git fetch", "git-transfer"),
                )
                if word in command
            ),
            None,
        )
        if role:
            heavy.append({"role": role, "name": name})
        elif name == "ollama.exe":
            # A resident runtime alone doesn't prove inference. Active/idle remains unknown.
            unknown += 1
    return {
        "observed_unix": time.time(),
        "heavy": heavy,
        "unknown_runtime_count": unknown,
        "quiet_window_established": not heavy and not unknown,
        "limitation": "Point-in-time process observation; no cache clearing or service changes",
    }
