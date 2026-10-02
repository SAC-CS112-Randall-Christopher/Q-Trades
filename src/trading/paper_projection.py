"""Operator-only, opt-in compression for future financial projection writes."""

import hashlib
from typing import Any

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

METHODS = {"default": "", "pglz": "p", "lz4": "l"}


def _metadata(connection: psycopg.Connection[dict[str, Any]]) -> dict[str, Any]:
    row = connection.execute(
        "SELECT n.nspname AS schema,c.oid AS table_oid,a.attcompression AS compression "
        "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
        "JOIN pg_attribute a ON a.attrelid=c.oid "
        "WHERE n.nspname=current_schema() AND c.relname='paper_state' "
        "AND c.relkind='r' AND a.attname='body' AND NOT a.attisdropped "
        "AND a.atttypid='jsonb'::regtype"
    ).fetchone()
    if row is None or row["compression"] not in METHODS.values():
        raise RuntimeError("Expected financial projection table is unavailable")
    row["method"] = next(key for key, value in METHODS.items() if value == row["compression"])
    return row


def _projection(
    connection: psycopg.Connection[dict[str, Any]], schema: str
) -> dict[str, Any]:
    rows = connection.execute(
        sql.SQL(
            "SELECT id,revision,body::text AS text,body->'schema'='1'::jsonb AS valid_version,"
            "pg_column_compression(body) AS stored_compression,"
            "pg_column_size(body) AS stored_bytes FROM {}"
        ).format(sql.Identifier(schema, "paper_state"))
    ).fetchmany(2)
    if len(rows) != 1 or rows[0]["id"] != 1 or rows[0]["valid_version"] is not True:
        raise RuntimeError("Expected initialized financial projection is unavailable")
    row = rows[0]
    encoded = row["text"].encode("utf-8")
    return {
        "revision": row["revision"],
        "projection_sha256": hashlib.sha256(encoded).hexdigest(),
        "text_bytes": len(encoded),
        "stored_bytes": row["stored_bytes"],
        "stored_compression": row["stored_compression"],
    }


def configure_projection_compression(
    dsn: str, *, target: str, expected: str, apply: bool = False
) -> dict[str, Any]:
    """Preview by default; apply only with the ordinary financial writer stopped.

    This is not an application/model tool. The operator's separately authorized
    updater owns stopping/restarting the installed process. No financial rows are
    rewritten here; the existing writer applies compression on its next commit.
    """
    if target not in METHODS or expected not in METHODS:
        raise ValueError("Supported projection compression method required")
    try:
        with psycopg.connect(
            dsn,
            autocommit=True,
            connect_timeout=3,
            application_name="qtrades_projection_compression",
            row_factory=dict_row,
        ) as connection, connection.transaction():
            if not apply:
                connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            connection.execute("SET LOCAL statement_timeout='3000'")
            connection.execute("SET LOCAL lock_timeout='500'")
            if apply:
                owned = connection.execute(
                    "SELECT pg_try_advisory_xact_lock("
                    "hashtext(current_database() || current_schema()),734921) AS acquired"
                ).fetchone()
                if not owned or not owned["acquired"]:
                    raise RuntimeError(
                        "The financial writer is active; compression was not changed"
                    )
            metadata = _metadata(connection)
            if apply:
                connection.execute(
                    sql.SQL("LOCK TABLE ONLY {} IN ACCESS EXCLUSIVE MODE").format(
                        sql.Identifier(metadata["schema"], "paper_state")
                    )
                )
                # Recheck after the table lock: no stale metadata transition.
                locked = _metadata(connection)
                if locked != metadata:
                    raise RuntimeError("Projection identity changed; compression was not changed")
            if metadata["method"] != expected:
                raise RuntimeError("Projection compression differs from the reviewed expectation")
            capability = connection.execute(
                "SELECT enumvals FROM pg_settings WHERE name='default_toast_compression'"
            ).fetchone()
            if capability is None or (target != "default" and target not in capability["enumvals"]):
                raise RuntimeError("Requested compression is unavailable in this PostgreSQL build")
            before = _projection(connection, metadata["schema"])
            if apply:
                connection.execute(
                    sql.SQL("ALTER TABLE {} ALTER COLUMN body SET COMPRESSION {}").format(
                        sql.Identifier(metadata["schema"], "paper_state"), sql.SQL(target)
                    )
                )
                after = _projection(connection, metadata["schema"])
                if before != after or _metadata(connection)["method"] != target:
                    raise RuntimeError(
                        "Projection preservation failed; compression change rolled back"
                    )
            report = {
                "mode": "applied" if apply else "preview",
                "previous_compression": metadata["method"],
                "target_compression": target,
                "server_version": connection.info.server_version,
                "projection": before,
                "financial_rows_rewritten": False,
                "future_writes_only": True,
            }
        # Returning after the context exits confirms the metadata commit.
        return report
    except psycopg.Error:
        # Connection/query errors may contain private credentials or server details.
        raise RuntimeError("Projection compression database operation failed") from None
