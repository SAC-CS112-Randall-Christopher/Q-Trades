import pytest

from trading.ownership import CollectorLock


def test_second_collector_is_rejected_and_lock_released(tmp_path):
    first = CollectorLock(tmp_path / "monitor.lock")
    second = CollectorLock(tmp_path / "monitor.lock")
    first.acquire()
    try:
        with pytest.raises(RuntimeError, match="Another collector"):
            second.acquire()
    finally:
        first.release()
    second.acquire()
    second.release()
