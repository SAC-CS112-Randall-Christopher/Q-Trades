"""Read only child accounting and a two-processor Windows numerical-worker limit."""

import ctypes
import mmap
import os
from pathlib import Path


def constrain_child(pid: int) -> None:
    if os.name != "nt":
        return  # Numerical fits are single-threaded; Windows is the supported operator host.
    kernel = ctypes.windll.kernel32
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel.GetProcessAffinityMask.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
    kernel.SetProcessAffinityMask.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
    kernel.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    handle = kernel.OpenProcess(0x0600, False, pid)
    if not handle:
        raise OSError("Cannot bound numerical worker processors")
    try:
        available, system = ctypes.c_size_t(), ctypes.c_size_t()
        if not kernel.GetProcessAffinityMask(handle, ctypes.byref(available), ctypes.byref(system)):
            raise OSError("Cannot read numerical worker processor allowance")
        bits = [1 << i for i in range(64) if available.value & (1 << i)]
        if not kernel.SetProcessAffinityMask(handle, sum(bits[:2])):
            raise OSError("Cannot enforce numerical worker processor allowance")
        if not kernel.SetPriorityClass(handle, 0x40):
            raise OSError("Cannot enforce numerical worker IDLE priority")
    finally:
        kernel.CloseHandle(handle)


def own_limits() -> dict[str, int | None]:
    if os.name != "nt":
        return {"pid": os.getpid(), "processors_allowed": None, "priority_class": None}
    kernel = ctypes.windll.kernel32
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel.GetPriorityClass.argtypes = [ctypes.c_void_p]
    handle = kernel.OpenProcess(0x0400, False, os.getpid())
    try:
        affinity, system = ctypes.c_size_t(), ctypes.c_size_t()
        if not handle or not kernel.GetProcessAffinityMask(
            handle, ctypes.byref(affinity), ctypes.byref(system)
        ):
            raise OSError("Cannot verify own numerical worker allowance")
        return {
            "pid": os.getpid(),
            "processors_allowed": affinity.value.bit_count(),
            "priority_class": int(kernel.GetPriorityClass(handle)),
        }
    finally:
        if handle:
            kernel.CloseHandle(handle)


def child_rss(pid: int) -> int:
    if os.name != "nt":
        try:
            parts = Path(f"/proc/{pid}/statm").read_text().split()
            return int(parts[1]) * mmap.PAGESIZE
        except (OSError, IndexError):
            return 0

    class Counters(ctypes.Structure):
        _fields_ = [("cb", ctypes.c_ulong), ("faults", ctypes.c_ulong)] + [
            (k, ctypes.c_size_t)
            for k in (
                "peak_rss",
                "rss",
                "peak_pool",
                "pool",
                "peak_nonpool",
                "nonpool",
                "pagefile",
                "peak_pagefile",
            )
        ]

    kernel = ctypes.windll.kernel32
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    ctypes.windll.psapi.GetProcessMemoryInfo.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_ulong,
    ]
    handle = kernel.OpenProcess(0x0410, False, pid)
    if not handle:
        return 0  # The child may have finished between polling and measurement.
    try:
        value = Counters()
        value.cb = ctypes.sizeof(value)
        if not ctypes.windll.psapi.GetProcessMemoryInfo(handle, ctypes.byref(value), value.cb):
            raise OSError("Cannot inspect numerical worker memory")
        return int(value.rss)
    finally:
        kernel.CloseHandle(handle)
