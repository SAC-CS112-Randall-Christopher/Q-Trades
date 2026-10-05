"""Consistent financial monitoring on a separate authenticated read-only connection."""

import time
from collections.abc import Callable
from contextlib import suppress
from typing import Any

from psycopg import Error as PsycopgError
from psycopg import capabilities as psycopg_capabilities
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

    @classmethod
    def from_dsn(cls, dsn: str) -> "FinancialReadback":
        # The owned worker receives only the authenticated read-only DSN, never
        # the financial connection, owner lock or executable instructions.
        reader = cls.__new__(cls)
        reader._dsn, reader._view = dsn, None
        return reader

    def cancel(self) -> None:
        view = self._view
        if view is not None and psycopg_capabilities.has_cancel_safe():
            # Cancellation success is not drainage. The process owner separately
            # waits for completion and has a bounded termination fallback.
            view.connection.cancel_safe(timeout=1)

    def close(self) -> None:
        view, self._view = self._view, None
        if view is not None:
            view.close()

    def sample(
        self, *, audit: bool, publish_audit: Callable[[dict[str, Any]], None] | None = None
    ) -> dict[str, Any]:
        """Called sequentially in the worker pool, never on the financial connection."""
        started = time.perf_counter()
        try:
            if self._view is None:
                self._view = PaperStore(self._dsn)
            view = self._view
            stages: dict[str, float] = {}
            result: dict[str, Any] = {"refresh_errors": {}}
            if audit:
                step = time.perf_counter()
                with view.connection.transaction():
                    view.connection.execute(
                        "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
                    )
                    result["observed_at"], result["observed_mono"] = time.time(), time.monotonic()
                    result["reconciliation"] = view.reconcile()
                stages["reconcile"] = (time.perf_counter() - step) * 1000
                # Publish the fully completed, coherent audit before any optional
                # query. A failure or hang in those queries cannot hide it.
                if publish_audit:
                    publish_audit(dict(result))
            else:
                result["observed_at"], result["observed_mono"] = time.time(), time.monotonic()
            if result.get("reconciliation", {}).get("balanced") is not False:
                refreshes: list[tuple[str, Callable[[], Any]]] = [("recent", view.recent)]
                if audit:
                    refreshes.append(("storage_usage", view.storage_usage))
                for name, query in refreshes:
                    step = time.perf_counter()
                    try:
                        # Optional refreshes have their own transactions; their
                        # rollback cannot invalidate the completed safety audit.
                        with view.connection.transaction():
                            result[name] = query()
                    except (PsycopgError, OSError):
                        result["refresh_errors"][name] = "Refresh unavailable"
                    stages[name] = (time.perf_counter() - step) * 1000
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
