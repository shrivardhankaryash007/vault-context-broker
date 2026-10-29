"""SQLite index storage and keyword search."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from pathlib import Path
from typing import Any

from vault_context_mcp.chunker import chunk_files
from vault_context_mcp.config import VaultConfig
from vault_context_mcp.markdown_scanner import scan_vault
from vault_context_mcp.schemas import (
    Clearance,
    MarkdownChunk,
    RetrievedChunk,
    ScannedMarkdownFile,
    SearchResult,
)
from vault_context_mcp.utils import utc_now_iso


class IndexError(RuntimeError):
    """Raised for index build or query failures."""


def sqlite_supports_fts5() -> bool:
    """Check whether the current SQLite build supports FTS5.

    Returns:
        True when FTS5 virtual tables can be created.
    """

    try:
        connection = sqlite3.connect(":memory:")
        connection.execute("CREATE VIRTUAL TABLE test_fts USING fts5(content)")
        connection.close()
    except sqlite3.Error:
        return False
    return True


def _ensure_columns(connection: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
    """Add any of `columns` missing from `table`."""

    existing = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
    for name, definition in columns.items():
        if name not in existing:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


class IndexStore:
    """SQLite-backed file and chunk index."""

    def __init__(self, index_path: Path) -> None:
        self.index_path = index_path

    def connect(self) -> sqlite3.Connection:
        """Open a SQLite connection.

        Returns:
            SQLite connection with row dictionaries enabled.
        """

        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.index_path)
        connection.row_factory = sqlite3.Row
        return connection

    def initialize(self) -> bool:
        """Create tables and optional FTS index.

        Returns:
            True when FTS5 is available.
        """

        fts_enabled = sqlite_supports_fts5()
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS files (
                    path TEXT PRIMARY KEY,
                    absolute_path TEXT NOT NULL,
                    modified_time REAL NOT NULL,
                    size INTEGER NOT NULL,
                    raw_text TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS chunks (
                    chunk_id TEXT PRIMARY KEY,
                    path TEXT NOT NULL,
                    heading TEXT,
                    text TEXT NOT NULL,
                    line_start INTEGER NOT NULL,
                    line_end INTEGER NOT NULL,
                    sensitivity TEXT NOT NULL DEFAULT 'open',
                    metadata_json TEXT NOT NULL,
                    FOREIGN KEY(path) REFERENCES files(path)
                );
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS tool_call_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tool_name TEXT NOT NULL,
                    args_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )
            if fts_enabled:
                connection.execute(
                    """
                    CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts
                    USING fts5(chunk_id UNINDEXED, path, heading, text)
                    """
                )
            _ensure_columns(connection, "chunks", {"sensitivity": "TEXT NOT NULL DEFAULT 'open'"})
            _ensure_columns(
                connection,
                "tool_call_log",
                {
                    "client": "TEXT",
                    "clearance": "TEXT",
                    "chunks_returned": "INTEGER",
                    "est_tokens": "INTEGER",
                },
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_chunks_sensitivity ON chunks(sensitivity)"
            )
            connection.execute(
                "INSERT OR REPLACE INTO metadata(key, value) VALUES (?, ?)",
                ("fts5_enabled", json.dumps(fts_enabled)),
            )
        return fts_enabled

    def build(
        self,
        files: list[ScannedMarkdownFile],
        chunks: list[MarkdownChunk],
        vault_fingerprint: str | None = None,
    ) -> bool:
        """Replace index contents with scanned files and chunks.

        Args:
            files: Scanned Markdown files.
            chunks: Chunks derived from the files.

        Returns:
            True when FTS5 is enabled.
        """

        fts_enabled = self.initialize()
        with self.connect() as connection:
            connection.execute("DELETE FROM chunks")
            connection.execute("DELETE FROM files")
            if fts_enabled:
                connection.execute("DELETE FROM chunks_fts")
            connection.executemany(
                """
                INSERT INTO files(path, absolute_path, modified_time, size, raw_text)
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (
                        file.path,
                        file.absolute_path,
                        file.modified_time,
                        file.size,
                        file.raw_text,
                    )
                    for file in files
                ],
            )
            connection.executemany(
                """
                INSERT INTO chunks(
                    chunk_id, path, heading, text, line_start, line_end, sensitivity, metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        chunk.chunk_id,
                        chunk.path,
                        chunk.heading,
                        chunk.text,
                        chunk.line_start,
                        chunk.line_end,
                        chunk.sensitivity,
                        json.dumps(chunk.metadata, default=str, sort_keys=True),
                    )
                    for chunk in chunks
                ],
            )
            if fts_enabled:
                connection.executemany(
                    "INSERT INTO chunks_fts(chunk_id, path, heading, text) VALUES (?, ?, ?, ?)",
                    [
                        (chunk.chunk_id, chunk.path, chunk.heading or "", chunk.text)
                        for chunk in chunks
                    ],
                )
            connection.execute(
                "INSERT OR REPLACE INTO metadata(key, value) VALUES (?, ?)",
                ("indexed_at", utc_now_iso()),
            )
            connection.execute(
                "INSERT OR REPLACE INTO metadata(key, value) VALUES (?, ?)",
                ("file_count", str(len(files))),
            )
            connection.execute(
                "INSERT OR REPLACE INTO metadata(key, value) VALUES (?, ?)",
                ("chunk_count", str(len(chunks))),
            )
            if vault_fingerprint is not None:
                connection.execute(
                    "INSERT OR REPLACE INTO metadata(key, value) VALUES (?, ?)",
                    ("vault_fingerprint", vault_fingerprint),
                )
        return fts_enabled

    def metadata_value(self, key: str) -> str | None:
        """Return a metadata value from the index."""

        if not self.index_path.exists():
            return None
        with self.connect() as connection:
            try:
                row = connection.execute(
                    "SELECT value FROM metadata WHERE key = ?", (key,)
                ).fetchone()
            except sqlite3.Error:
                return None
        return str(row["value"]) if row is not None else None

    def chunk_count(self) -> int:
        """Return indexed chunk count."""

        if not self.index_path.exists():
            return 0
        with self.connect() as connection:
            try:
                row = connection.execute("SELECT COUNT(*) AS count FROM chunks").fetchone()
            except sqlite3.Error:
                return 0
        return int(row["count"] if row is not None else 0)

    def fts_enabled(self) -> bool:
        """Return whether this index was created with FTS5."""

        if not self.index_path.exists():
            return sqlite_supports_fts5()
        with self.connect() as connection:
            row = connection.execute(
                "SELECT value FROM metadata WHERE key = ?", ("fts5_enabled",)
            ).fetchone()
        return bool(json.loads(row["value"])) if row is not None else False

    def list_paths(self) -> list[str]:
        """Return indexed vault-relative file paths."""

        with self.connect() as connection:
            rows = connection.execute("SELECT path FROM files ORDER BY path").fetchall()
        return [str(row["path"]) for row in rows]

    def get_chunks_for_paths(
        self, paths: list[str], clearance: Clearance = "cloud"
    ) -> list[RetrievedChunk]:
        """Return chunks for the given vault-relative paths."""

        if not paths:
            return []
        placeholders = ",".join("?" for _ in paths)
        clearance_clause = "" if clearance == "local" else " AND sensitivity = 'open'"
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT chunk_id, path, heading, text, line_start, line_end,
                       sensitivity, metadata_json
                FROM chunks
                WHERE path IN ({placeholders}){clearance_clause}
                ORDER BY path, line_start
                """,
                paths,
            ).fetchall()
        return [self._row_to_chunk(row, score=0.0) for row in rows]

    def search(
        self, query: str, top_k: int = 20, clearance: Clearance = "cloud"
    ) -> list[SearchResult]:
        """Search indexed chunks.

        Args:
            query: Search query.
            top_k: Maximum raw results.

        Returns:
            Search results with keyword scores.
        """

        terms = _query_terms(query)
        if not terms:
            return []
        if self.fts_enabled():
            return self._search_fts(terms, top_k, clearance)
        return self._search_like(terms, top_k, clearance)

    def log_tool_call(
        self,
        tool_name: str,
        args: dict[str, Any],
        client: str | None = None,
        clearance: str | None = None,
        chunks_returned: int | None = None,
        est_tokens: int | None = None,
    ) -> None:
        """Log an MCP tool call to the local index."""

        self.initialize()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO tool_call_log(
                    tool_name, args_json, created_at, client, clearance,
                    chunks_returned, est_tokens
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tool_name,
                    json.dumps(args, sort_keys=True),
                    utc_now_iso(),
                    client,
                    clearance,
                    chunks_returned,
                    est_tokens,
                ),
            )

    def _search_fts(self, terms: list[str], top_k: int, clearance: Clearance) -> list[SearchResult]:
        fts_query = " OR ".join(f"{term}*" for term in terms)
        clearance_clause = "" if clearance == "local" else " AND c.sensitivity = 'open'"
        with self.connect() as connection:
            try:
                rows = connection.execute(
                    f"""
                    SELECT c.chunk_id, c.path, c.heading, c.text, c.line_start, c.line_end,
                           c.sensitivity, c.metadata_json, bm25(chunks_fts) AS rank
                    FROM chunks_fts
                    JOIN chunks c ON c.chunk_id = chunks_fts.chunk_id
                    WHERE chunks_fts MATCH ?{clearance_clause}
                    ORDER BY rank
                    LIMIT ?
                    """,
                    (fts_query, top_k),
                ).fetchall()
            except sqlite3.Error:
                return self._search_like(terms, top_k, clearance)
        results: list[SearchResult] = []
        for row in rows:
            rank = float(row["rank"])
            score = 10.0 / (1.0 + abs(rank))
            results.append(SearchResult(chunk=self._row_to_chunk(row, score), keyword_score=score))
        return results

    def _search_like(
        self, terms: list[str], top_k: int, clearance: Clearance
    ) -> list[SearchResult]:
        where = " OR ".join(
            ["LOWER(path || ' ' || COALESCE(heading, '') || ' ' || text) LIKE ?"] * len(terms)
        )
        params = [f"%{term.lower()}%" for term in terms]
        clearance_clause = "" if clearance == "local" else " AND sensitivity = 'open'"
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT chunk_id, path, heading, text, line_start, line_end,
                       sensitivity, metadata_json
                FROM chunks
                WHERE ({where}){clearance_clause}
                LIMIT ?
                """,
                [*params, top_k],
            ).fetchall()
        results: list[SearchResult] = []
        for row in rows:
            haystack = f"{row['path']} {row['heading'] or ''} {row['text']}".lower()
            score = float(sum(haystack.count(term.lower()) for term in terms))
            results.append(SearchResult(chunk=self._row_to_chunk(row, score), keyword_score=score))
        return results

    @staticmethod
    def _row_to_chunk(row: sqlite3.Row, score: float) -> RetrievedChunk:
        metadata_raw = row["metadata_json"]
        metadata = json.loads(metadata_raw) if metadata_raw else {}
        return RetrievedChunk(
            chunk_id=str(row["chunk_id"]),
            path=str(row["path"]),
            heading=str(row["heading"]) if row["heading"] is not None else None,
            text=str(row["text"]),
            line_start=int(row["line_start"]),
            line_end=int(row["line_end"]),
            score=score,
            sensitivity=row["sensitivity"]
            if row["sensitivity"] in ("open", "restricted")
            else "open",
            metadata=metadata,
        )


def build_index(config: VaultConfig) -> tuple[int, int, bool]:
    """Scan, chunk, and build the configured index.

    Args:
        config: Runtime configuration.

    Returns:
        Tuple of file count, chunk count, and FTS availability.
    """

    files = scan_vault(config)
    chunks = chunk_files(files, config)
    fts_enabled = IndexStore(config.index_file_path).build(
        files,
        chunks,
        vault_fingerprint=fingerprint_scanned_files(files),
    )
    return len(files), len(chunks), fts_enabled


def ensure_index(config: VaultConfig) -> None:
    """Build the index when it is missing or empty."""

    store = IndexStore(config.index_file_path)
    if store.chunk_count() == 0:
        build_index(config)
        return
    if config.librarian.auto_refresh_index:
        files = scan_vault(config)
        fingerprint = fingerprint_scanned_files(files)
        if store.metadata_value("vault_fingerprint") != fingerprint:
            chunks = chunk_files(files, config)
            store.build(files, chunks, vault_fingerprint=fingerprint)


def fingerprint_scanned_files(files: list[ScannedMarkdownFile]) -> str:
    """Compute a stable fingerprint from scanned file metadata."""

    digest = hashlib.sha1()
    for file in files:
        digest.update(f"{file.path}:{file.modified_time}:{file.size}\n".encode())
    return digest.hexdigest()


def _query_terms(query: str) -> list[str]:
    terms = re.findall(r"[A-Za-z0-9_/-]+", query.lower())
    return [term for term in terms if len(term) > 1]
