"""Consistent financial monitoring on a separate authenticated read-only connection."""

import time
from contextlib import suppress
from typing import Any

from psycopg.conninfo import conninfo_to_dict, make_conninfo

from trading.paper_store import PaperStore


class FinancialReadback:
    def __init__(self, store: PaperStore):
        info = store.connection.info
        options = str(conninfo_to_dict(info.dsn).get("options") or "")
        self._dsn = make_conninfo(
            info.dsn,
            password=info.password,
            connect_timeout=3,
            options=options + " -c default_transaction_read_only=on",
        )
        self._view: PaperStore | None = None

    def close(self) -> None:
        view, self._view = self._view, None
        if view is not None:
            view.close()

    def sample(self, *, audit: bool) -> dict[str, Any]:
        """Called sequentially in the worker pool, never on the financial connection."""
        started = time.perf_counter()
        try:
            if self._view is None:
                self._view = PaperStore(self._dsn)
            view = self._view
            stages: dict[str, float] = {}
            with view.connection.transaction():
                view.connection.execute(
                    "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
                )
                observed_at, observed_mono = time.time(), time.monotonic()
                step = time.perf_counter()
                result: dict[str, Any] = {
                    "recent": view.recent(),
                    "observed_at": observed_at,
                    "observed_mono": observed_mono,
                }
                stages["recent"] = (time.perf_counter() - step) * 1000
                if audit:
                    step = time.perf_counter()
                    result["reconciliation"] = view.reconcile()
                    stages["reconcile"] = (time.perf_counter() - step) * 1000
                    step = time.perf_counter()
                    result["storage_usage"] = view.storage_usage()
                    stages["storage_usage"] = (time.perf_counter() - step) * 1000
            result["completed_at"] = time.time()
            result["elapsed_ms"] = (time.perf_counter() - started) * 1000
            result["stages_ms"] = {k: round(v, 3) for k, v in stages.items()}
            return result
        except BaseException:
            # An interrupted/failed transaction never supplies a partial audit.
            # Reconnect on the next bounded poll, preserving the original writer.
            with suppress(Exception):
                self.close()
            raise
