"""Tie the one development child to its parent's lifetime using pinned handles."""

import ctypes
import os
import subprocess
import time
from ctypes import wintypes
from typing import Any

from trading.numerical_resources import child_rss

MAX_JOB_PROCESSES = 8
MAX_THREAD_ENTRIES = 65536


class ThreadEntry(ctypes.Structure):
    _fields_ = [
        ("size", wintypes.DWORD),
        ("usage", wintypes.DWORD),
        ("thread", wintypes.DWORD),
        ("process", wintypes.DWORD),
        ("base_priority", wintypes.LONG),
        ("delta_priority", wintypes.LONG),
        ("flags", wintypes.DWORD),
    ]


class ProcessIds(ctypes.Structure):
    _fields_ = [
        ("assigned", wintypes.DWORD),
        ("count", wintypes.DWORD),
        ("ids", ctypes.c_size_t * MAX_JOB_PROCESSES),
    ]


class MemoryCounters(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("faults", wintypes.DWORD)] + [
        (name, ctypes.c_size_t)
        for name in (
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


def available_memory() -> int:
    if os.name != "nt":
        raise ValueError("Actual development memory observation requires Windows")

    class Memory(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("load", wintypes.DWORD)] + [
            (name, ctypes.c_uint64)
            for name in (
                "total",
                "available",
                "pagefile",
                "available_pagefile",
                "virtual",
                "available_virtual",
                "extended",
            )
        ]

    memory = Memory()
    memory.size = ctypes.sizeof(memory)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memory)):
        raise OSError("Development memory observation is unavailable")
    return int(memory.available)


class ChildOwner:
    def __init__(
        self,
        child: subprocess.Popen[bytes],
        *,
        memory_limit: int | None = None,
        suspended: bool = False,
    ):
        if memory_limit is not None and (
            isinstance(memory_limit, bool)
            or not isinstance(memory_limit, int)
            or not 0 < memory_limit <= ctypes.c_size_t(-1).value
        ):
            raise ValueError("Development memory limit must be positive whole bytes")
        self.handle: Any = None
        self.child = child
        self._suspended = suspended
        self._thread: Any = None
        self._snapshot: Any = None
        self._processes: dict[int, Any] = {}
        self._peaks: dict[int, int] = {}
        if os.name != "nt":
            return  # Portable procedural tests; actual profile requires Windows.

        class Basic(ctypes.Structure):
            _fields_ = [
                ("process_time", ctypes.c_int64),
                ("job_time", ctypes.c_int64),
                ("flags", wintypes.DWORD),
                ("minimum", ctypes.c_size_t),
                ("maximum", ctypes.c_size_t),
                ("active", wintypes.DWORD),
                ("affinity", ctypes.c_size_t),
                ("priority", wintypes.DWORD),
                ("scheduling", wintypes.DWORD),
            ]

        class Extended(ctypes.Structure):
            _fields_ = [
                ("basic", Basic),
                ("io", ctypes.c_uint64 * 6),
                ("process_memory", ctypes.c_size_t),
                ("job_memory", ctypes.c_size_t),
                ("peak_process", ctypes.c_size_t),
                ("peak_job", ctypes.c_size_t),
            ]

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel.CreateJobObjectW.restype = wintypes.HANDLE
        kernel.SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        kernel.GetProcessId.argtypes = [wintypes.HANDLE]
        kernel.GetProcessId.restype = wintypes.DWORD
        kernel.QueryInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.c_void_p,
        ]
        kernel.QueryInformationJobObject.restype = wintypes.BOOL
        kernel.IsProcessInJob.argtypes = [wintypes.HANDLE, wintypes.HANDLE, ctypes.c_void_p]
        kernel.IsProcessInJob.restype = wintypes.BOOL
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.WaitForSingleObject.restype = wintypes.DWORD
        self.psapi = ctypes.WinDLL("psapi", use_last_error=True)
        self.psapi.GetProcessMemoryInfo.argtypes = [
            wintypes.HANDLE,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        self.psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        handle = kernel.CreateJobObjectW(None, None)
        limits = Extended()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if memory_limit is not None:
            # Private committed memory has an allocation-time OS ceiling. It is
            # distinct from the resident-set observation across the entire Job.
            limits.basic.flags |= 0x100  # PROCESS_MEMORY; existing unsuspended callers.
            limits.process_memory = memory_limit
            if suspended:
                # The model's owned suspended launch opts into an aggregate cap.
                limits.basic.flags |= 0x200  # JOB_MEMORY
                limits.job_memory = memory_limit
        self.kernel, self.handle = kernel, handle
        try:
            if (
                not handle
                or not kernel.SetInformationJobObject(
                    handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)
                )
                or not kernel.AssignProcessToJobObject(handle, int(child._handle))  # type: ignore[attr-defined]
            ):
                raise OSError("Cannot establish owned development-child lifetime")
            if kernel.GetProcessId(int(child._handle)) != child.pid:  # type: ignore[attr-defined]
                raise OSError("Development process handle identity differs")
            if suspended:
                self._thread = self._primary_thread()
        except BaseException:
            self.close()
            raise

    def _primary_thread(self) -> Any:
        """Pin the only thread of the CREATE_SUSPENDED launcher before release."""
        kernel = self.kernel
        kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        kernel.Thread32First.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
        kernel.Thread32Next.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
        kernel.OpenThread.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenThread.restype = wintypes.HANDLE
        kernel.GetProcessIdOfThread.argtypes = [wintypes.HANDLE]
        kernel.GetProcessIdOfThread.restype = wintypes.DWORD
        snapshot = kernel.CreateToolhelp32Snapshot(0x4, 0)  # TH32CS_SNAPTHREAD
        if not snapshot or snapshot == ctypes.c_void_p(-1).value:
            raise OSError("Cannot inspect suspended development thread")
        self._snapshot = snapshot
        found = []
        deadline = time.monotonic() + 2
        try:
            entry = ThreadEntry()
            entry.size = ctypes.sizeof(entry)
            valid = kernel.Thread32First(snapshot, ctypes.byref(entry))
            count = 0
            while valid:
                count += 1
                if count > MAX_THREAD_ENTRIES or time.monotonic() > deadline:
                    raise OSError("Suspended development thread inspection exceeds bound")
                if entry.process == self.child.pid:
                    found.append(entry.thread)
                entry.size = ctypes.sizeof(entry)
                valid = kernel.Thread32Next(snapshot, ctypes.byref(entry))
            if ctypes.get_last_error() != 18:  # ERROR_NO_MORE_FILES
                raise OSError("Suspended development thread inspection incomplete")
        finally:
            if not kernel.CloseHandle(snapshot):
                raise OSError("Cannot close development thread snapshot")
            self._snapshot = None
        if len(found) != 1:
            raise OSError("Suspended development launcher must have exactly one thread")
        thread = kernel.OpenThread(0x2 | 0x800, False, found[0])
        if not thread:
            raise OSError("Cannot pin suspended development thread")
        self._thread = thread
        if kernel.GetProcessIdOfThread(thread) != self.child.pid:
            raise OSError("Suspended development thread changed ownership")
        return thread

    def resume(self) -> None:
        """Release only the pinned suspended launcher after its Job owns it."""
        if os.name != "nt":
            return
        if not self.handle or not self._suspended or not self._thread:
            raise OSError("Development launcher is not owned and suspended")
        member = wintypes.BOOL()
        process = int(self.child._handle)  # type: ignore[attr-defined]
        if not self.kernel.IsProcessInJob(process, self.handle, ctypes.byref(member)) or not member:
            raise OSError("Suspended development launcher is outside its Job")
        self.kernel.ResumeThread.argtypes = [wintypes.HANDLE]
        self.kernel.ResumeThread.restype = wintypes.DWORD
        if self.kernel.ResumeThread(self._thread) != 1:
            raise OSError("Development launcher did not have exactly one suspension")
        self._suspended = False
        if not self.kernel.CloseHandle(self._thread):
            raise OSError("Cannot close resumed development thread")
        self._thread = None

    def _members(self) -> set[int]:
        value = ProcessIds()
        if not self.handle or not self.kernel.QueryInformationJobObject(
            self.handle,
            3,
            ctypes.byref(value),
            ctypes.sizeof(value),
            None,
        ):
            raise OSError("Cannot observe complete development Job membership")
        if value.assigned != value.count or not 0 <= value.count <= MAX_JOB_PROCESSES:
            raise OSError("Development Job membership exceeds its finite bound")
        members = {int(value.ids[i]) for i in range(value.count)}
        if len(members) != value.count or any(pid <= 0 for pid in members):
            raise OSError("Development Job membership is invalid")
        return members

    def rss(self) -> int:
        """Conservative sum of pinned Job members' peak resident sets.

        Per-process peaks need not coincide. Summing them deliberately refuses
        uncertain aggregate headroom, rather than overlooking a redirector's
        interpreter or a between-poll peak while it remains observable. After
        exit, only its last observed peak remains; a never-observed short-lived
        process's RSS peak is unknown. This is not Job private-commit usage or a
        complete continuous trace. The final runner peak is checked separately.
        """
        if os.name != "nt":
            return child_rss(self.child.pid)
        for _ in range(3):
            members = self._members()
            if not members and self.child.poll() is None:
                raise OSError("Running development launcher is absent from its Job")
            for pid in members:
                if pid not in self._processes:
                    if len(self._processes) >= MAX_JOB_PROCESSES:
                        raise OSError("Development process lifetime count exceeds bound")
                    process = self.kernel.OpenProcess(0x0410 | 0x100000, False, pid)
                    if not process:
                        raise OSError("Cannot pin owned development process")
                    self._processes[pid] = process
                process = self._processes[pid]
                member = wintypes.BOOL()
                if (
                    self.kernel.GetProcessId(process) != pid
                    or not self.kernel.IsProcessInJob(
                        process,
                        self.handle,
                        ctypes.byref(member),
                    )
                    or not member
                ):
                    raise OSError("Development process handle is outside its Job")
                counters = MemoryCounters()
                counters.size = ctypes.sizeof(counters)
                if not self.psapi.GetProcessMemoryInfo(
                    process, ctypes.byref(counters), counters.size
                ):
                    raise OSError("Cannot inspect owned development process memory")
                self._peaks[pid] = max(self._peaks.get(pid, 0), int(counters.peak_rss))
            if self._members() == members:
                return sum(self._peaks.values())
        raise OSError("Development Job membership did not stabilize within its bound")

    def close(self) -> None:
        failed = []
        for name in ("handle", "_thread", "_snapshot"):
            handle = getattr(self, name)
            if handle:
                try:
                    closed = self.kernel.CloseHandle(handle)
                except Exception:
                    closed = False
                if closed:
                    setattr(self, name, None)
                else:
                    failed.append(name)
        for pid, process in list(self._processes.items()):
            try:
                closed = self.kernel.CloseHandle(process)
            except Exception:
                closed = False
            if closed:
                del self._processes[pid]
            else:
                failed.append("process")
        if failed:
            raise OSError("Cannot close owned development handles: " + ",".join(failed))
