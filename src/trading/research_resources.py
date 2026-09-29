"""Read bounded, verified Windows resource observations for advisory inference."""

import ctypes
import json
import sys
from ctypes import wintypes
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ELASTIC_CPU_RUNTIME = "trading-cpu-elastic-six-threads-v1"


def _process(pid: int, executable: str, started_at: str) -> dict[str, int]:
    if sys.platform != "win32":
        raise ValueError("Windows resource observation is unavailable")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.GetPriorityClass.argtypes = [wintypes.HANDLE]
    kernel.GetPriorityClass.restype = wintypes.DWORD
    kernel.GetProcessAffinityMask.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(ctypes.c_size_t),
        ctypes.POINTER(ctypes.c_size_t),
    ]
    kernel.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    handle = kernel.OpenProcess(0x0400, False, pid)
    if not handle:
        raise OSError("Owned runtime process is unavailable")
    try:
        name = ctypes.create_unicode_buffer(32768)
        size = wintypes.DWORD(len(name))
        if not kernel.QueryFullProcessImageNameW(handle, 0, name, ctypes.byref(size)):
            raise OSError("Runtime executable identity is unavailable")
        if Path(name.value) != Path(executable):
            raise ValueError("Runtime process executable changed")
        times = [wintypes.FILETIME() for _ in range(4)]
        if not kernel.GetProcessTimes(handle, *(ctypes.byref(t) for t in times)):
            raise OSError("Runtime process creation time is unavailable")
        created = ((times[0].dwHighDateTime << 32) | times[0].dwLowDateTime) / 1e7 - 11644473600
        if abs(created - datetime.fromisoformat(started_at).timestamp()) > 0.002:
            raise ValueError("Runtime process identity changed; PID may have been reused")
        affinity, available = ctypes.c_size_t(), ctypes.c_size_t()
        if not kernel.GetProcessAffinityMask(
            handle, ctypes.byref(affinity), ctypes.byref(available)
        ):
            raise OSError("Runtime processor affinity is unavailable")
        priority = kernel.GetPriorityClass(handle)
        if not priority:
            raise OSError("Runtime priority is unavailable")
        return {
            "pid": pid,
            "priority_class": priority,
            "affinity": affinity.value,
            "available_affinity": available.value,
        }
    finally:
        kernel.CloseHandle(handle)


def capture_resources(path: Path, *, include_worker: bool = True) -> dict[str, Any]:
    with path.open("rb") as source:
        raw = source.read(65537)
    if len(raw) > 65536:
        raise ValueError("Runtime status exceeds its size limit")
    state = json.loads(raw)
    age = (datetime.now(UTC) - datetime.fromisoformat(state["updated_at"])).total_seconds()
    if not 0 <= age <= 30 or state["state"] != "running":
        raise ValueError("Runtime supervisor status is stale or not running")
    if state["origin"] != "http://127.0.0.1:11435":
        raise ValueError("Unexpected inference endpoint")
    server = _process(state["server_pid"], state["executable"], state["server_started_at"])
    observed = {
        "profile": state["profile"],
        "inference_threads": state["inference_threads"],
        "observed_at": datetime.now(UTC).isoformat(),
        "server": server,
    }
    if include_worker:
        observed["worker"] = _process(
            state["last_budgeted_worker_pid"],
            state["worker_executable"],
            state["worker_started_at"],
        )
    return observed


def elastic_resources_valid(value: Any, *, include_worker: bool = True) -> bool:
    if not isinstance(value, dict) or value.get("profile") != ELASTIC_CPU_RUNTIME:
        return False
    if value.get("inference_threads") != 6:
        return False
    for key in ("server", "worker") if include_worker else ("server",):
        process = value.get(key)
        if not isinstance(process, dict) or process.get("priority_class") != 0x40:  # IDLE
            return False
        mask = process.get("affinity")
        if not isinstance(mask, int) or mask.bit_count() < 6:
            return False
        if mask != process.get("available_affinity"):
            return False
    return True
