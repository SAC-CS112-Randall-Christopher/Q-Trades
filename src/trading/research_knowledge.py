"""Private reference versions and bounded, source-first retrieval; no financial owner."""

from __future__ import annotations

import base64
import builtins
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import closing, contextmanager
from html.parser import HTMLParser
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from trading.experiment_registry import fingerprint
from trading.peft_child_owner import ChildOwner
from trading.research_storage import ResearchStorage

MAX_SOURCE = 65536
MAX_CONTEXT = 16384
MAX_CANDIDATES = 2048
SOURCE_ID = r"^[a-zA-Z0-9_-]{3,64}$"


class SourceImport(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    source_id: str = Field(pattern=SOURCE_ID)
    title: str = Field(min_length=3, max_length=150)
    author: str = Field(min_length=2, max_length=150)
    origin: str = Field(min_length=3, max_length=300)
    rights: str = Field(min_length=12, max_length=500)
    text: str = Field(min_length=1, max_length=MAX_SOURCE)
    format: Literal["text", "markdown", "html", "pdf"] = "markdown"
    category: Literal["theory", "mechanics", "methods", "costs", "risk", "note"] = "methods"
    symbol: str | None = Field(default=None, pattern=r"^[A-Z0-9]{3,20}$")
    horizon: Literal["short", "medium", "long"] | None = None
    published_at: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    external_allowed: bool = False
    training_allowed: bool = False
    protected: bool = False
    generated: bool = False
    expected_revision: int = Field(default=0, ge=0)


class KnowledgeQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    text: str = Field(min_length=1, max_length=300)
    cutoff: float = Field(gt=0, allow_inf_nan=False)
    symbol: str | None = Field(default=None, pattern=r"^[A-Z0-9]{3,20}$")
    horizon: Literal["short", "medium", "long"] | None = None
    limit: int = Field(default=8, ge=1, le=12)
    match: Literal["terms", "phrase", "exact_source"] = "terms"


class DocumentImport(SourceImport):
    text: str = "Native PDF extraction requested"
    format: Literal["text", "markdown", "html", "pdf"] = "pdf"
    document_base64: str = Field(min_length=8, max_length=174768)
    first_page: int = Field(default=1, ge=1, le=1000)
    last_page: int = Field(default=1, ge=1, le=1000)


class KnowledgeDisposition(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    revision: int = Field(ge=1)
    expected_state: int = Field(ge=1)
    state: Literal["reference", "accepted", "disputed", "excluded", "withdrawn"]
    reason: str = Field(min_length=12, max_length=1200)


class _HTMLText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hidden = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "template"}:
            self.hidden += 1
        if tag in {"p", "br", "div", "h1", "h2", "h3", "li", "tr"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "template"} and self.hidden:
            self.hidden -= 1

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.parts.append(data)


def safe_text(text: str) -> None:
    if re.search(r"sk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{20,}|BEGIN .*PRIVATE KEY", text):
        raise ValueError("Credential-like content cannot enter the knowledge library")


class ResearchKnowledge:
    def __init__(self, storage: ResearchStorage, *, name: str = "reference-knowledge.sqlite"):
        self.storage = storage
        if name != "reference-knowledge.sqlite" and not re.fullmatch(
            r"knowledge-restore-\d{10,24}\.sqlite", name
        ):
            raise ValueError("Only the canonical library or an owned fresh restore is permitted")
        self.path = storage.research / name
        with storage._exclusive():
            storage.admission(262144, "research")
            storage._not_redirected(self.path)
            with self.connection() as db:
                db.execute("PRAGMA journal_mode=WAL")
                db.execute("PRAGMA max_page_count=16384")  # Separate, declared 64 MiB ceiling.
                db.executescript("""
                    CREATE TABLE IF NOT EXISTS knowledge_sources(
                        source TEXT NOT NULL, revision INTEGER NOT NULL,
                        received REAL NOT NULL, sha TEXT NOT NULL, metadata TEXT NOT NULL,
                        original BLOB NOT NULL, extracted TEXT NOT NULL,
                        PRIMARY KEY(source,revision));
                    CREATE TABLE IF NOT EXISTS knowledge_states(
                        seq INTEGER PRIMARY KEY,source TEXT NOT NULL,revision INTEGER NOT NULL,
                        at REAL NOT NULL,state TEXT NOT NULL,reason TEXT NOT NULL,
                        actor TEXT NOT NULL);
                    CREATE TABLE IF NOT EXISTS knowledge_receipts(
                        id TEXT PRIMARY KEY,body TEXT NOT NULL,created REAL NOT NULL);
                    CREATE INDEX IF NOT EXISTS knowledge_availability
                        ON knowledge_sources(source,received,revision);
                    CREATE INDEX IF NOT EXISTS knowledge_visibility
                        ON knowledge_states(source,revision,at,seq);
                    CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts
                        USING fts5(source UNINDEXED,revision UNINDEXED,text);
                    CREATE TRIGGER IF NOT EXISTS knowledge_original_frozen
                        BEFORE UPDATE ON knowledge_sources
                        BEGIN SELECT RAISE(ABORT,'Source versions are immutable'); END;
                    CREATE TRIGGER IF NOT EXISTS knowledge_original_retained
                        BEFORE DELETE ON knowledge_sources
                        BEGIN SELECT RAISE(ABORT,'Source versions are retained'); END;
                    CREATE TRIGGER IF NOT EXISTS knowledge_state_frozen
                        BEFORE UPDATE ON knowledge_states
                        BEGIN SELECT RAISE(ABORT,'Disposition history is append-only'); END;
                    CREATE TRIGGER IF NOT EXISTS knowledge_state_retained
                        BEFORE DELETE ON knowledge_states
                        BEGIN SELECT RAISE(ABORT,'Disposition history is retained'); END;
                    CREATE TRIGGER IF NOT EXISTS knowledge_receipt_frozen
                        BEFORE UPDATE ON knowledge_receipts
                        BEGIN SELECT RAISE(ABORT,'Delivered context is immutable'); END;
                    CREATE TRIGGER IF NOT EXISTS knowledge_receipt_retained
                        BEFORE DELETE ON knowledge_receipts
                        BEGIN SELECT RAISE(ABORT,'Delivered context is retained'); END;
                """)

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        self.storage._check_volume()
        self.storage._not_redirected(self.path)
        with closing(sqlite3.connect(self.path, timeout=2, isolation_level=None)) as db:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA synchronous=FULL")
            db.execute("PRAGMA journal_size_limit=1048576")
            db.execute("PRAGMA wal_autocheckpoint=64")
            yield db

    @contextmanager
    def write(self, amount: int) -> Iterator[sqlite3.Connection]:
        # Share the storage owner's cross-process reservation boundary. No hidden spill.
        with self.storage._exclusive():
            self.storage.admission(amount * 4 + 131072, "research")
            with self.connection() as db:
                db.execute("BEGIN IMMEDIATE")
                try:
                    yield db
                    db.execute("COMMIT")
                except BaseException:
                    db.execute("ROLLBACK")
                    raise

    def ingest(self, source: SourceImport) -> dict[str, Any]:
        if source.format == "pdf":
            raise ValueError("Use bounded original PDF import; text alone is not the source PDF")
        return self._ingest(source, source.text.encode(), {})

    def ingest_document(self, command: DocumentImport) -> dict[str, Any]:
        if command.format != "pdf" or not 0 <= command.last_page - command.first_page < 6:
            raise ValueError("Choose one to six complete PDF pages")
        try:
            raw = base64.b64decode(command.document_base64, validate=True)
        except ValueError as exc:
            raise ValueError("Invalid bounded PDF upload") from exc
        if not raw.startswith(b"%PDF-") or len(raw) > 131072:
            raise ValueError("Choose a PDF section no larger than 128 KiB")
        flags = (
            subprocess.CREATE_NO_WINDOW | subprocess.IDLE_PRIORITY_CLASS if os.name == "nt" else 0
        )
        child = subprocess.Popen(
            [sys.executable, "-m", "trading.knowledge_extract"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
        )
        owner = None
        try:
            owner = ChildOwner(child, memory_limit=256 * 1024**2)
            output, _ = child.communicate(
                json.dumps(
                    {
                        "bytes": command.document_base64,
                        "first": command.first_page,
                        "last": command.last_page,
                    }
                ).encode(),
                timeout=10,
            )
            if child.returncode != 0 or len(output) > 100000:
                raise ValueError(
                    "PDF extraction unavailable or resource-blocked; no source indexed"
                )
            parsed = json.loads(output)
            source = SourceImport.model_validate(
                command.model_dump(exclude={"document_base64", "first_page", "last_page"})
                | {"text": parsed["text"]}
            )
            return self._ingest(source, raw, parsed["extraction"])
        except (subprocess.TimeoutExpired, KeyError, json.JSONDecodeError) as exc:
            raise ValueError("PDF extraction did not complete; no invented text/OCR") from exc
        finally:
            if child.poll() is None:
                child.kill()
            child.wait(timeout=5)
            if owner:
                owner.close()

    def _ingest(
        self, source: SourceImport, encoded: bytes, extraction: dict[str, Any]
    ) -> dict[str, Any]:
        if len(source.text.encode()) > MAX_SOURCE or len(encoded) > (
            131072 if source.format == "pdf" else MAX_SOURCE
        ):
            raise ValueError("Source exceeds 64 KiB; import a declared smaller section")
        safe_text(json.dumps(source.model_dump()))
        extracted = source.text
        if source.format == "html":
            parser = _HTMLText()
            parser.feed(source.text)
            extracted = "".join(parser.parts)
        if not extracted.strip():
            raise ValueError("No readable text extracted; source is unavailable, not indexed")
        metadata = source.model_dump(exclude={"text", "expected_revision"}) | {
            "extraction": extraction or {"method": "utf8-section-v1"},
        }
        sha = fingerprint({"bytes": hashlib.sha256(encoded).hexdigest(), "metadata": metadata})
        with self.write(len(encoded)) as db:
            old = db.execute(
                "SELECT revision,sha FROM knowledge_sources WHERE source=? "
                "ORDER BY revision DESC LIMIT 1",
                (source.source_id,),
            ).fetchone()
            if old and old["sha"] == sha:
                return {"source": source.source_id, "revision": old["revision"], "duplicate": True}
            revision = old["revision"] if old else 0
            if revision != source.expected_revision:
                raise ValueError("Source changed; reopen its latest version before appending")
            revision += 1
            now = time.time()
            db.execute(
                "INSERT INTO knowledge_sources VALUES(?,?,?,?,?,?,?)",
                (source.source_id, revision, now, sha, json.dumps(metadata), encoded, extracted),
            )
            state = "disputed" if source.generated else "reference"
            db.execute(
                "INSERT INTO knowledge_states(source,revision,at,state,reason,actor) "
                "VALUES(?,?,?,?,?,'local operator')",
                (source.source_id, revision, now, state, "Explicit rights-scoped source import"),
            )
            db.execute(
                "INSERT INTO knowledge_fts VALUES(?,?,?)", (source.source_id, revision, extracted)
            )
        return {"source": source.source_id, "revision": revision, "duplicate": False}

    @staticmethod
    def _state(db: sqlite3.Connection, source: str, revision: int, cutoff: float) -> dict[str, Any]:
        row = db.execute(
            "SELECT * FROM knowledge_states WHERE source=? AND revision=? AND at<=? "
            "ORDER BY seq DESC LIMIT 1",
            (source, revision, cutoff),
        ).fetchone()
        return dict(row) if row else {"state": "unavailable"}

    @staticmethod
    def _eligible(meta: dict[str, Any], state: dict[str, Any], *, external: bool) -> bool:
        return (
            not meta["protected"]
            and state["state"] not in {"excluded", "withdrawn", "unavailable"}
            and (not external or meta["external_allowed"])
        )

    def _permitted_now(
        self, db: sqlite3.Connection, source: str, revision: int, *, external: bool
    ) -> bool:
        # Historical availability is separate from today's disclosure permission.
        # An old receipt remains immutable, but revocation also closes cached reads.
        latest = db.execute(
            "SELECT revision,metadata FROM knowledge_sources WHERE source=? "
            "ORDER BY revision DESC LIMIT 1",
            (source,),
        ).fetchone()
        original = db.execute(
            "SELECT metadata FROM knowledge_sources WHERE source=? AND revision=?",
            (source, revision),
        ).fetchone()
        if latest is None or original is None:
            return False
        now = time.time()
        # A sanitized successor can revoke access, but cannot grant access to an
        # older local-only/protected passage already saved in a context or receipt.
        return self._eligible(
            json.loads(original["metadata"]),
            self._state(db, source, revision, now),
            external=external,
        ) and self._eligible(
            json.loads(latest["metadata"]),
            self._state(db, source, latest["revision"], now),
            external=external,
        )

    def check_passages(self, passages: list[dict[str, Any]], *, external: bool) -> None:
        with self.connection() as db:
            db.execute("BEGIN")
            if any(
                not self._permitted_now(db, p["source"], p["revision"], external=external)
                for p in passages
            ):
                raise ValueError(
                    "A source permission was revoked; retained context is not disclosed"
                )

    def teaching_permitted(self, source: str, revision: int) -> bool:
        with self.connection() as db:
            latest = db.execute(
                "SELECT metadata FROM knowledge_sources WHERE source=? "
                "ORDER BY revision DESC LIMIT 1",
                (source,),
            ).fetchone()
            original = db.execute(
                "SELECT metadata FROM knowledge_sources WHERE source=? AND revision=?",
                (source, revision),
            ).fetchone()
            return bool(
                latest
                and original
                and self._permitted_now(db, source, revision, external=False)
                and json.loads(latest[0])["training_allowed"]
                and json.loads(original[0])["training_allowed"]
            )

    def read(
        self,
        source: str,
        revision: int,
        *,
        cutoff: float,
        external: bool = False,
        operator: bool = False,
    ) -> dict[str, Any]:
        with self.connection() as db:
            db.execute("BEGIN")
            row = db.execute(
                "SELECT * FROM knowledge_sources WHERE source=? AND revision=? AND received<=?",
                (source, revision, cutoff),
            ).fetchone()
            if row is None:
                raise ValueError("Source is unavailable in this permitted context")
            meta = json.loads(row["metadata"])
            state = self._state(db, source, revision, cutoff)
            if not operator and (
                not self._eligible(meta, state, external=external)
                or not self._permitted_now(db, source, revision, external=external)
            ):
                raise ValueError("Source is unavailable in this permitted context")
            return {
                "source": source,
                "revision": revision,
                "received_at": row["received"],
                "sha256": row["sha"],
                "metadata": meta,
                "disposition": state,
                "original": (bytes(row["original"]).decode() if meta["format"] != "pdf" else None),
                "original_bytes": len(row["original"]),
                "original_sha256": hashlib.sha256(row["original"]).hexdigest(),
                "text": row["extracted"],
                "locator": "Complete imported section; UTF-8 bytes retained exactly",
            }

    def list(self, before: str = "") -> dict[str, Any]:
        with self.connection() as db:
            rows = db.execute(
                "SELECT source,revision,received,metadata FROM knowledge_sources WHERE "
                "source>? AND revision=(SELECT max(revision) FROM knowledge_sources s "
                "WHERE s.source=knowledge_sources.source) ORDER BY source LIMIT 21",
                (before,),
            ).fetchall()
            items = [
                {
                    "source": r["source"],
                    "revision": r["revision"],
                    "received_at": r["received"],
                    "metadata": json.loads(r["metadata"]),
                    "disposition": self._state(db, r["source"], r["revision"], time.time()),
                }
                for r in rows[:20]
            ]
            latest = db.execute("SELECT max(received) FROM knowledge_sources").fetchone()[0]
            try:
                db.execute("SELECT count(*) FROM knowledge_fts").fetchone()
                index_condition = (
                    "Derived FTS5 index available; historical ranking uses eligible originals"
                )
            except sqlite3.DatabaseError:
                index_condition = (
                    "Derived index unavailable; bounded search rebuilds from originals"
                )
        return {
            "sources": items,
            "next_before": items[-1]["source"] if len(rows) > 20 else None,
            "mode": "FTS5; optional semantic/routing helper disabled",
            "limits": {
                "source_bytes": MAX_SOURCE,
                "context_bytes": MAX_CONTEXT,
                "library_bytes": 64 * 1024**2,
            },
            "extraction": "UTF-8 sections / bounded native PDF pages; OCR not available",
            "index_condition": index_condition,
            "latest_source_received_at": latest,
            "backups": self.backups(),
        }

    def document(self, source: str, revision: int) -> bytes:
        # Operator-only original download; MCP receives only permitted extracted sections.
        record = self.read(source, revision, cutoff=time.time(), operator=True)
        if record["metadata"]["format"] != "pdf":
            raise ValueError("Source has no original PDF")
        with self.connection() as db:
            row = db.execute(
                "SELECT original FROM knowledge_sources WHERE source=? AND revision=?",
                (source, revision),
            ).fetchone()
            return bytes(row[0])

    def disposition(self, source: str, command: KnowledgeDisposition) -> dict[str, Any]:
        with self.write(2048) as db:
            if not db.execute(
                "SELECT 1 FROM knowledge_sources WHERE source=? AND revision=?",
                (source, command.revision),
            ).fetchone():
                raise ValueError("Source unavailable")
            old = self._state(db, source, command.revision, time.time())
            if old["seq"] != command.expected_state:
                raise ValueError("Disposition changed; reopen before making this decision")
            db.execute(
                "INSERT INTO knowledge_states(source,revision,at,state,reason,actor) "
                "VALUES(?,?,?,?,?,'local operator')",
                (source, command.revision, time.time(), command.state, command.reason),
            )
            return self._state(db, source, command.revision, time.time())

    def retrieve(
        self, query: KnowledgeQuery, *, external: bool = False, task: str = "local-library"
    ) -> dict[str, Any]:
        began = time.perf_counter()
        if query.cutoff > time.time():
            raise ValueError("Future retrieval cutoff is unavailable")
        terms = re.findall(r"[\w-]+", query.text, re.UNICODE)[:24]
        if not terms:
            raise ValueError("Supply words or an exact source identity")
        expression = (
            '"' + query.text.replace('"', '""') + '"'
            if query.match != "terms"
            else " OR ".join('"' + x.replace('"', '""') + '"' for x in terms)
        )
        # Rank a bounded, already eligible population. Present/future FTS frequencies
        # cannot leak into historical selection. Persisted index is rebuildable only.
        with self.connection() as db, closing(sqlite3.connect(":memory:")) as search:
            db.execute("BEGIN")
            rows = db.execute(
                "SELECT * FROM knowledge_sources k WHERE received<=? AND revision="
                "(SELECT max(revision) FROM knowledge_sources s WHERE s.source=k.source "
                "AND s.received<=?) ORDER BY source",
                (query.cutoff, query.cutoff),
            )
            eligible: dict[str, dict[str, Any]] = {}
            search.execute("CREATE VIRTUAL TABLE candidate USING fts5(id UNINDEXED,text)")
            for row in rows:
                meta = json.loads(row["metadata"])
                state = self._state(db, row["source"], row["revision"], query.cutoff)
                if (
                    query.match == "exact_source"
                    and row["source"] != query.text
                    or not self._eligible(meta, state, external=external)
                    or not self._permitted_now(
                        db, row["source"], row["revision"], external=external
                    )
                    or query.symbol
                    and meta["symbol"] not in {None, query.symbol}
                    or query.horizon
                    and meta["horizon"] not in {None, query.horizon}
                ):
                    continue
                paragraphs = re.split(r"\n\s*\n", row["extracted"])
                offset = 0
                for paragraph in paragraphs:
                    start = row["extracted"].find(paragraph, offset)
                    offset = start + len(paragraph)
                    if not paragraph.strip():
                        continue
                    if len(eligible) >= MAX_CANDIDATES:
                        raise ValueError("Eligible corpus exceeds bounded ranking; narrow scope")
                    identity = (
                        "k-" + fingerprint([row["source"], row["revision"], start, offset])[:32]
                    )
                    eligible[identity] = {
                        "source": row["source"],
                        "revision": row["revision"],
                        "sha256": row["sha"],
                        "title": meta["title"],
                        "author": meta["author"],
                        "origin": meta["origin"],
                        "rights": meta["rights"],
                        "category": meta["category"],
                        "symbol": meta["symbol"],
                        "horizon": meta["horizon"],
                        "generated": meta["generated"],
                        "published_at": meta["published_at"],
                        "received_at": row["received"],
                        "status": state["state"],
                        "disposition_at": state["at"],
                        "locator": {"start_character": start, "end_character": offset},
                        "text": paragraph,
                        "citation": identity,
                    }
                    search.execute(
                        "INSERT INTO candidate VALUES(?,?)",
                        (identity, meta["title"] + " " + row["source"] + " " + paragraph),
                    )
            ranked = search.execute(
                "SELECT id,bm25(candidate) FROM candidate WHERE candidate MATCH ? "
                "ORDER BY bm25(candidate),id LIMIT 25",
                (expression,),
            ).fetchall()
            matched = search.execute(
                "SELECT count(*) FROM candidate WHERE candidate MATCH ?", (expression,)
            ).fetchone()[0]
        items: list[dict[str, Any]] = []
        size = 0
        for identity, score in ranked:
            item = eligible[identity] | {"score": score}
            amount = len(json.dumps(item).encode())
            if len(items) < query.limit and size + amount <= MAX_CONTEXT:
                items.append(item)
                size += amount
        result = {
            "version": "source-rag-v1",
            "task": task,
            "query": query.model_dump(),
            "external": external,
            "mode": "eligible-population-fts5-v1",
            "passages": items,
            "omitted_matches": matched - len(items),
            "coverage": "Bounded reference corpus; theory is not observed performance",
            "absence": None if items else "No eligible matching reference evidence",
            "semantic_support": "Citation identity checked separately from claim support",
            "context_bytes": size,
            "elapsed_ms": (time.perf_counter() - began) * 1000,
        }
        # Stable content identity excludes timing so repeated reads reuse one receipt.
        identity = "rag-" + fingerprint({k: v for k, v in result.items() if k != "elapsed_ms"})[:32]
        result["id"] = identity
        with self.write(MAX_CONTEXT) as db:
            if any(
                not self._permitted_now(db, p["source"], p["revision"], external=external)
                for p in items
            ):
                raise ValueError("Source visibility changed while retrieving; repeat the read")
            db.execute(
                "INSERT OR IGNORE INTO knowledge_receipts VALUES(?,?,?)",
                (identity, json.dumps(result, allow_nan=False), time.time()),
            )
            return dict(
                json.loads(
                    db.execute(
                        "SELECT body FROM knowledge_receipts WHERE id=?", (identity,)
                    ).fetchone()[0]
                )
            )

    def receipt(self, identity: str) -> dict[str, Any]:
        with self.connection() as db:
            row = db.execute(
                "SELECT body FROM knowledge_receipts WHERE id=?", (identity,)
            ).fetchone()
        if row is None:
            raise ValueError("Delivered retrieval receipt unavailable")
        return dict(json.loads(row[0]))

    def reindex(self) -> dict[str, Any]:
        with self.connection() as reader:
            size = reader.execute(
                "SELECT sum(length(extracted)) FROM knowledge_sources"
            ).fetchone()[0]
        with self.write(int(size or 0)) as db:
            db.execute("DROP TABLE IF EXISTS knowledge_fts")
            db.execute(
                "CREATE VIRTUAL TABLE knowledge_fts USING fts5(source UNINDEXED,"
                "revision UNINDEXED,text)"
            )
            db.execute(
                "INSERT INTO knowledge_fts SELECT source,revision,extracted FROM knowledge_sources"
            )
            count = db.execute("SELECT count(*) FROM knowledge_fts").fetchone()[0]
        return {"indexed_versions": count, "originals": "unchanged", "mode": "FTS5"}

    def backup(self) -> dict[str, Any]:
        # One coherent DB holds original UTF-8 bytes, authoritative notes and receipts.
        identity = "knowledge-backup-" + str(time.time_ns()) + ".sqlite"
        target = self.storage.research / identity
        with self.storage._exclusive(), self.connection() as source:
            self.storage.admission(self.path.stat().st_size * 2 + 131072, "research")
            self.storage._not_redirected(target)
            with closing(sqlite3.connect(target)) as copied:
                source.backup(copied, pages=128)
                if copied.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise OSError("Knowledge backup verification failed; original preserved")
        result = {
            "backup": identity,
            "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            "source_bytes_included": True,
        }
        with self.storage._exclusive():
            manifest = target.with_suffix(".json")
            self.storage._not_redirected(manifest)
            manifest.write_text(json.dumps(result), encoding="utf-8")
        return result

    def backups(self) -> builtins.list[dict[str, Any]]:
        self.storage._check_volume()
        result = []
        for p in sorted(self.storage.research.glob("knowledge-backup-*.sqlite"), reverse=True)[:20]:
            self.storage._not_redirected(p)
            manifest = p.with_suffix(".json")
            self.storage._not_redirected(manifest)
            meta = json.loads(manifest.read_text()) if manifest.is_file() else {}
            result.append(
                {"backup": p.name, "bytes": p.stat().st_size, "sha256": meta.get("sha256")}
            )
        return result

    def restore(self, backup: str, expected_sha256: str) -> dict[str, Any]:
        """Restore to a fresh owned snapshot. Never replace the active library/evidence."""
        if not re.fullmatch(r"knowledge-backup-\d{10,24}\.sqlite", backup):
            raise ValueError("Select an owned knowledge backup; arbitrary paths are refused")
        source = self.storage.research / backup
        target_name = "knowledge-restore-" + str(time.time_ns()) + ".sqlite"
        target = self.storage.research / target_name
        with self.storage._exclusive():
            self.storage._not_redirected(source)
            self.storage._not_redirected(target)
            if not source.is_file() or source.stat().st_size > 64 * 1024**2:
                raise ValueError("Bounded knowledge backup unavailable")
            if hashlib.sha256(source.read_bytes()).hexdigest() != expected_sha256:
                raise ValueError("Backup checksum differs; original library preserved")
            self.storage.admission(source.stat().st_size * 3 + 131072, "research")
            with closing(sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)) as db:
                if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise ValueError("Backup integrity failed")
                # Reject an injected SQLite schema; schema is local authority, not source data.
                unexpected = db.execute(
                    "SELECT name FROM sqlite_master WHERE type IN ('trigger','view') "
                    "AND name NOT IN ('knowledge_original_frozen','knowledge_original_retained',"
                    "'knowledge_state_frozen','knowledge_state_retained',"
                    "'knowledge_receipt_frozen','knowledge_receipt_retained')"
                ).fetchone()
                if unexpected:
                    raise ValueError("Backup contains an unsupported schema")
                for identity, metadata, original in db.execute(
                    "SELECT sha,metadata,original FROM knowledge_sources"
                ):
                    if identity != fingerprint(
                        {
                            "bytes": hashlib.sha256(original).hexdigest(),
                            "metadata": json.loads(metadata),
                        }
                    ):
                        raise ValueError("Original source checksum differs")
                with closing(sqlite3.connect(target)) as copied:
                    db.backup(copied, pages=128)
        restored = ResearchKnowledge(self.storage, name=target_name)
        index = restored.reindex()
        return {
            "library": target_name,
            "backup": backup,
            "sha256": expected_sha256,
            "index": index,
            "sources": restored.list()["sources"],
            "active_library": "unchanged; restored originals are a separate fresh snapshot",
        }
