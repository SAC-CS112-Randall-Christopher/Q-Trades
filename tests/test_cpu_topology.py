import json
import os
import struct
import subprocess
import sys
from pathlib import Path

import pytest

from trading.cpu_topology import decode_core_masks, distinct_processors, physical_core_masks


def core_record(mask, group=0):
    return struct.pack("<II", 0, 48) + bytes(22) + struct.pack("<H", 1) + struct.pack(
        "<QHHHH", mask, group, 0, 0, 0
    )


def test_selection_uses_two_physical_cores_and_preserves_available_mask():
    cores = decode_core_masks(core_record(3) + core_record(12) + core_record(48))
    assert cores == [3, 12, 48]
    assert distinct_processors(63, cores) == 5
    assert distinct_processors(42, cores) == 10
    with pytest.raises(OSError, match="distinct physical cores"):
        distinct_processors(3, cores)


@pytest.mark.parametrize(
    "raw", [b"", bytes(47), core_record(3, group=1), core_record(3) + core_record(2)]
)
def test_foreign_incomplete_or_overlapping_topology_cannot_supply_an_allocation(raw):
    with pytest.raises(OSError):
        decode_core_masks(raw)


@pytest.mark.skipif(os.name != "nt", reason="Actual physical topology requires Windows")
def test_native_owned_child_observes_distinct_cores_and_unchanged_priority(tmp_path):
    cores = physical_core_masks()
    if len(cores) < 2:
        pytest.skip("Two distinct physical cores are unavailable on this host")
    code = (
        "import ctypes,json,os; "
        "from trading.numerical_resources import constrain_child,own_limits; "
        "constrain_child(os.getpid(),distinct_cores=True); "
        "k=ctypes.windll.kernel32;k.GetCurrentProcess.restype=ctypes.c_void_p;"
        "a=ctypes.c_size_t();s=ctypes.c_size_t();"
        "k.GetProcessAffinityMask.argtypes=[ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p];"
        "assert k.GetProcessAffinityMask(k.GetCurrentProcess(),ctypes.byref(a),ctypes.byref(s));"
        "print(json.dumps(dict(own_limits(),affinity=a.value)))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=10,
        creationflags=subprocess.CREATE_NO_WINDOW,
        env=dict(os.environ, PYTHONPATH=str(Path("src").resolve())),
    )
    assert result.returncode == 0, result.stderr
    observed = json.loads(result.stdout)
    assert observed["processors_allowed"] == 2 and observed["priority_class"] == 0x40
    assert sum(bool(core & observed["affinity"]) for core in cores) == 2
