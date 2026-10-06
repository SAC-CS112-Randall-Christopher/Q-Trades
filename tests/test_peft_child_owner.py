"""Disposable Windows venv redirector and Job accounting; no models or private data."""

import ctypes
import json
import os
import subprocess
import time
import venv
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from trading.numerical_resources import child_rss
from trading.peft_child_owner import MAX_JOB_PROCESSES, ChildOwner, MemoryCounters, ProcessIds

MIB = 1024**2
NATIVE = pytest.mark.skipif(os.name != "nt", reason="Windows Job/venv owner proof")


@pytest.fixture
def redirector(tmp_path):
    directory = tmp_path / "disposable-venv"
    venv.EnvBuilder(with_pip=False).create(directory)
    return directory / "Scripts/python.exe"


def start(redirector, directory, *, allocated=64, commit_limit=512, release=False):
    script = directory / "owned_memory.py"
    script.write_text(
        "import gc,json,os,sys,time\n"
        "from pathlib import Path\n"
        "directory=Path(sys.argv[1]); size=int(sys.argv[2])*1024**2\n"
        "while not (directory/'owner-ready').exists(): time.sleep(.01)\n"
        "try:\n"
        "    data=bytearray(size)\n"
        "    for offset in range(0,size,4096): data[offset]=1\n"
        "    refused=False\n"
        "except MemoryError: refused=True\n"
        "if sys.argv[3]=='release' and not refused: del data; gc.collect()\n"
        "(directory/'actual-interpreter.json').write_text(json.dumps(\n"
        "    {'pid':os.getpid(),'allocation_refused':refused,'requested_bytes':size}))\n"
        "time.sleep(30)\n",
        encoding="utf-8",
    )
    child = subprocess.Popen(
        [
            str(redirector),
            str(script),
            str(directory),
            str(allocated),
            "release" if release else "hold",
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW | 0x4,
    )
    try:
        owner = ChildOwner(child, memory_limit=commit_limit * MIB, suspended=True)
    except BaseException:
        child.terminate()
        child.wait(timeout=5)
        raise
    return child, owner


def wait_receipt(directory):
    path = directory / "actual-interpreter.json"
    deadline = time.monotonic() + 5
    while not path.exists():
        if time.monotonic() >= deadline:
            raise TimeoutError("Disposable interpreter did not publish its allocation receipt")
        time.sleep(0.01)
    return json.loads(path.read_text())


@NATIVE
def test_suspended_venv_interpreter_is_owned_before_run_and_old_rss_underreports(
    redirector,
    tmp_path,
):
    child, owner = start(redirector, tmp_path)
    actual_handle = None
    try:
        time.sleep(0.1)
        assert not (tmp_path / "actual-interpreter.json").exists()
        assert owner._members() == {child.pid}
        (tmp_path / "owner-ready").write_text("owned")
        owner.resume()
        receipt = wait_receipt(tmp_path)
        assert not receipt["allocation_refused"]
        assert receipt["pid"] != child.pid  # Actual Windows venv redirector, not a stand-in.
        observed = owner.rss()
        assert receipt["pid"] in owner._members()
        assert observed >= 64 * MIB
        launcher = child_rss(child.pid)
        assert launcher < 32 * MIB < observed
        (tmp_path / "native-owned-memory-proof.json").write_text(
            json.dumps(
                {
                    "scope": "Disposable real venv redirector; synthetic64MiB allocation; no model",
                    "launcher_rss_bytes": launcher,
                    "owned_peak_sum_bytes": observed,
                    "old_launcher_scope_missed_synthetic32MiB_threshold": launcher < 32 * MIB,
                    "new_owned_scope_detected_synthetic32MiB_threshold": observed > 32 * MIB,
                    "before_resume_members": 1,
                    "actual_interpreter_in_job": True,
                }
            )
        )
        actual_handle = owner.kernel.OpenProcess(0x100000, False, receipt["pid"])
        assert actual_handle
        owner.close()
        assert owner.kernel.WaitForSingleObject(actual_handle, 5000) == 0
        child.wait(timeout=5)
        with pytest.raises(OSError, match="membership"):
            owner.rss()
        with pytest.raises(OSError, match="owned and suspended"):
            owner.resume()
    finally:
        owner.close()
        if actual_handle:
            owner.kernel.CloseHandle(actual_handle)
        if child.poll() is None:
            child.terminate()
        child.wait(timeout=5)


@NATIVE
def test_native_commit_limit_reaches_actual_interpreter_and_refuses_allocation(
    redirector,
    tmp_path,
):
    child, owner = start(redirector, tmp_path, allocated=256, commit_limit=128)
    try:
        (tmp_path / "owner-ready").write_text("owned")
        owner.resume()
        receipt = wait_receipt(tmp_path)
        assert receipt["pid"] != child.pid
        assert receipt["allocation_refused"]
        assert receipt["pid"] in owner._members()
        assert owner.rss() < 128 * MIB
    finally:
        owner.close()
        child.wait(timeout=5)


@NATIVE
def test_peak_resident_accounting_catches_allocate_free_while_interpreter_is_alive(
    redirector,
    tmp_path,
):
    child, owner = start(redirector, tmp_path, release=True)
    try:
        (tmp_path / "owner-ready").write_text("owned")
        owner.resume()
        receipt = wait_receipt(tmp_path)
        assert not receipt["allocation_refused"]
        assert owner.rss() >= 64 * MIB
        counters = MemoryCounters()
        counters.size = ctypes.sizeof(counters)
        assert owner.psapi.GetProcessMemoryInfo(
            owner._processes[receipt["pid"]],
            ctypes.byref(counters),
            counters.size,
        )
        assert counters.rss < 32 * MIB <= counters.peak_rss
    finally:
        owner.close()
        child.wait(timeout=5)


@NATIVE
def test_native_aggregate_commit_cap_and_job_close_include_nested_interpreters(
    redirector,
    tmp_path,
):
    script = tmp_path / "nested_memory.py"
    script.write_text(
        "import json,os,subprocess,sys,time\n"
        "from pathlib import Path\n"
        "directory=Path(sys.argv[1]); nested=len(sys.argv)>2\n"
        "while not (directory/'owner-ready').exists(): time.sleep(.01)\n"
        "try:\n"
        "    data=bytearray(96*1024**2)\n"
        "    for offset in range(0,len(data),4096): data[offset]=1\n"
        "    refused=False\n"
        "except MemoryError: refused=True\n"
        "(directory/('nested.json' if nested else 'parent.json')).write_text(\n"
        "    json.dumps({'pid':os.getpid(),'allocation_refused':refused}))\n"
        "if not nested:\n"
        "    subprocess.Popen([sys.executable,__file__,str(directory),'nested'])\n"
        "time.sleep(30)\n",
        encoding="utf-8",
    )
    child = subprocess.Popen(
        [str(redirector), str(script), str(tmp_path)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW | 0x4,
    )
    owner = None
    handles = []
    try:
        owner = ChildOwner(child, memory_limit=160 * MIB, suspended=True)
        (tmp_path / "owner-ready").write_text("owned")
        owner.resume()
        deadline = time.monotonic() + 5
        while not (tmp_path / "nested.json").exists():
            if time.monotonic() >= deadline:
                raise TimeoutError("Disposable nested interpreter did not publish receipt")
            time.sleep(0.01)
        parent = json.loads((tmp_path / "parent.json").read_text())
        nested = json.loads((tmp_path / "nested.json").read_text())
        assert not parent["allocation_refused"] and nested["allocation_refused"]
        assert {parent["pid"], nested["pid"]} <= owner._members()
        assert owner.rss() >= 96 * MIB
        for pid in (parent["pid"], nested["pid"]):
            handle = owner.kernel.OpenProcess(0x100000, False, pid)
            assert handle
            handles.append(handle)
        owner.close()
        assert all(owner.kernel.WaitForSingleObject(handle, 5000) == 0 for handle in handles)
        child.wait(timeout=5)
    finally:
        if owner:
            owner.close()
            for handle in handles:
                owner.kernel.CloseHandle(handle)
        if child.poll() is None:
            child.terminate()
        child.wait(timeout=5)


@pytest.mark.parametrize("limit", [True, False, 0, -1, 1.5, "24GiB", 2**128])
def test_invalid_byte_limits_refuse_without_child_access(limit):
    child = Mock()
    with pytest.raises(ValueError, match="positive whole bytes"):
        ChildOwner(child, memory_limit=limit)
    child.assert_not_called()


@pytest.mark.parametrize(
    "assigned,count,ids",
    [
        (9, 8, tuple(range(1, 9))),
        (2, 1, (1,)),
        (2, 2, (1, 1)),
        (1, 1, (0,)),
    ],
)
def test_partial_overflow_duplicate_or_invalid_membership_refuses(assigned, count, ids):
    def query(_handle, _kind, pointer, _size, _written):
        value = ctypes.cast(pointer, ctypes.POINTER(ProcessIds)).contents
        value.assigned, value.count = assigned, count
        for i, pid in enumerate(ids[:MAX_JOB_PROCESSES]):
            value.ids[i] = pid
        return True

    owner = ChildOwner.__new__(ChildOwner)
    owner.handle = 1
    owner.kernel = SimpleNamespace(QueryInformationJobObject=query)
    with pytest.raises(OSError, match="membership"):
        owner._members()


def test_failed_job_membership_observation_refuses():
    owner = ChildOwner.__new__(ChildOwner)
    owner.handle = 1
    owner.kernel = SimpleNamespace(QueryInformationJobObject=lambda *args: False)
    with pytest.raises(OSError, match="complete"):
        owner._members()


@pytest.mark.parametrize("failed_handle", [11, 12, 13, 14, 15])
@pytest.mark.parametrize("raises", [False, True])
def test_close_attempts_all_handles_and_retains_only_failures_for_retry(failed_handle, raises):
    attempted = []

    def close(handle):
        attempted.append(handle)
        if handle == failed_handle:
            if raises:
                raise OSError("Synthetic API failure")
            return False
        return True

    owner = ChildOwner.__new__(ChildOwner)
    owner.handle, owner._thread, owner._snapshot = 11, 12, 13
    owner._processes = {100: 14, 200: 15}
    owner.kernel = SimpleNamespace(CloseHandle=close)
    with pytest.raises(OSError, match="Cannot close owned development handles"):
        owner.close()
    assert attempted == [11, 12, 13, 14, 15]
    remaining = [owner.handle, owner._thread, owner._snapshot, *owner._processes.values()]
    assert [handle for handle in remaining if handle] == [failed_handle]
    owner.kernel.CloseHandle = lambda handle: attempted.append(handle) or True
    owner.close()
    assert attempted[-1] == failed_handle
    assert owner.handle is owner._thread is owner._snapshot is None
    assert owner._processes == {}
    owner.close()  # Success is idempotent without additional API calls.


@NATIVE
@pytest.mark.parametrize("suspended", [False, True])
def test_aggregate_commit_cap_is_opt_in_and_legacy_process_cap_is_preserved(
    monkeypatch,
    suspended,
):
    flags = []

    def limits(_handle, _kind, value, _size):
        flags.append((value._obj.basic.flags, value._obj.process_memory, value._obj.job_memory))
        return True

    kernel = Mock()
    kernel.CreateJobObjectW.return_value = 17
    kernel.SetInformationJobObject.side_effect = limits
    kernel.AssignProcessToJobObject.return_value = True
    kernel.GetProcessId.return_value = 300
    kernel.CloseHandle.return_value = True
    monkeypatch.setattr(ctypes, "WinDLL", lambda *args, **kwargs: kernel)
    monkeypatch.setattr(ChildOwner, "_primary_thread", lambda _: 19)
    child = SimpleNamespace(pid=300, _handle=31)
    owner = ChildOwner(child, memory_limit=256 * MIB, suspended=suspended)
    try:
        assert flags == [
            (0x2000 | 0x100 | (0x200 if suspended else 0), 256 * MIB, 256 * MIB if suspended else 0)
        ]
    finally:
        owner.close()


@NATIVE
def test_resume_retains_failed_thread_close_and_fails_transport(monkeypatch):
    owner = ChildOwner.__new__(ChildOwner)
    owner.handle, owner._thread, owner._snapshot = 17, 19, None
    owner._suspended = True
    owner._processes = {}
    owner.child = SimpleNamespace(_handle=31)
    kernel = Mock()

    def member(_process, _job, pointer):
        pointer._obj.value = True
        return True

    kernel.IsProcessInJob.side_effect = member
    kernel.ResumeThread.return_value = 1
    kernel.CloseHandle.return_value = False
    owner.kernel = kernel
    with pytest.raises(OSError, match="Cannot close resumed"):
        owner.resume()
    assert owner._thread == 19 and owner._suspended is False
    kernel.CloseHandle.return_value = True
    owner.close()


@NATIVE
def test_thread_snapshot_close_failure_is_retained_for_owner_cleanup(monkeypatch):
    owner = ChildOwner.__new__(ChildOwner)
    owner.handle, owner._thread, owner._snapshot = 17, None, None
    owner._processes = {}
    owner.child = SimpleNamespace(pid=300)
    kernel = Mock()
    kernel.CreateToolhelp32Snapshot.return_value = 19
    kernel.Thread32First.return_value = False
    kernel.CloseHandle.return_value = False
    owner.kernel = kernel
    monkeypatch.setattr(ctypes, "get_last_error", lambda: 18)
    with pytest.raises(OSError, match="Cannot close development thread snapshot"):
        owner._primary_thread()
    assert owner._snapshot == 19
    kernel.CloseHandle.return_value = True
    owner.close()
    assert owner._snapshot is None
