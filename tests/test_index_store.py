"""Index store tests."""

from __future__ import annotations

import sqlite3

from vault_context_mcp.index_store import IndexStore, build_index


def test_index_can_be_built(test_config) -> None:  # type: ignore[no-untyped-def]
    file_count, chunk_count, _ = build_index(test_config)

    assert file_count >= 9
    assert chunk_count >= 9
    assert IndexStore(test_config.index_file_path).chunk_count() == chunk_count


def test_get_chunks_for_paths_carries_sensitivity(test_config) -> None:  # type: ignore[no-untyped-def]
    build_index(test_config)
    store = IndexStore(test_config.index_file_path)

    chunks = store.get_chunks_for_paths(["ACME/widget-design-notes.md"], clearance="local")

    assert chunks
    assert all(chunk.sensitivity == "restricted" for chunk in chunks)


def test_search_excludes_restricted_chunks_under_cloud_clearance(test_config) -> None:  # type: ignore[no-untyped-def]
    build_index(test_config)
    store = IndexStore(test_config.index_file_path)

    cloud_results = store.search("widget gear actuator", top_k=10, clearance="cloud")
    local_results = store.search("widget gear actuator", top_k=10, clearance="local")

    assert cloud_results == []
    assert local_results
    assert all(result.chunk.path != "ACME/widget-design-notes.md" for result in cloud_results)
    assert any(result.chunk.path == "ACME/widget-design-notes.md" for result in local_results)


def test_get_chunks_for_paths_excludes_restricted_under_cloud_clearance(test_config) -> None:  # type: ignore[no-untyped-def]
    build_index(test_config)
    store = IndexStore(test_config.index_file_path)

    cloud_chunks = store.get_chunks_for_paths(
        ["ACME/widget-design-notes.md", "01_CURRENT_STATE.md"], clearance="cloud"
    )

    assert cloud_chunks
    assert all(chunk.path != "ACME/widget-design-notes.md" for chunk in cloud_chunks)


def test_search_defaults_to_cloud_clearance_when_unspecified(test_config) -> None:  # type: ignore[no-untyped-def]
    build_index(test_config)
    store = IndexStore(test_config.index_file_path)

    results = store.search("widget gear actuator", top_k=10)

    assert results == []


def test_log_tool_call_stores_ledger_fields(test_config) -> None:  # type: ignore[no-untyped-def]
    store = IndexStore(test_config.index_file_path)

    store.log_tool_call(
        "search_vault",
        {"query": "x"},
        client="codex",
        clearance="cloud",
        chunks_returned=3,
        est_tokens=120,
    )

    with store.connect() as connection:
        row = connection.execute(
            "SELECT client, clearance, chunks_returned, est_tokens FROM tool_call_log "
            "ORDER BY id DESC LIMIT 1"
        ).fetchone()

    assert row["client"] == "codex"
    assert row["clearance"] == "cloud"
    assert row["chunks_returned"] == 3
    assert row["est_tokens"] == 120


def test_initialize_migrates_pre_sensitivity_chunks_table(test_config) -> None:  # type: ignore[no-untyped-def]
    store = IndexStore(test_config.index_file_path)
    store.index_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(store.index_path) as connection:
        connection.executescript(
            """
            CREATE TABLE files (
                path TEXT PRIMARY KEY,
                absolute_path TEXT NOT NULL,
                modified_time REAL NOT NULL,
                size INTEGER NOT NULL,
                raw_text TEXT NOT NULL
            );
            CREATE TABLE chunks (
                chunk_id TEXT PRIMARY KEY,
                path TEXT NOT NULL,
                heading TEXT,
                text TEXT NOT NULL,
                line_start INTEGER NOT NULL,
                line_end INTEGER NOT NULL,
                metadata_json TEXT NOT NULL
            );
            CREATE TABLE tool_call_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tool_name TEXT NOT NULL,
                args_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )

    store.initialize()

    with store.connect() as connection:
        chunk_columns = {row[1] for row in connection.execute("PRAGMA table_info(chunks)")}
        log_columns = {row[1] for row in connection.execute("PRAGMA table_info(tool_call_log)")}

    assert "sensitivity" in chunk_columns
    assert {"client", "clearance", "chunks_returned", "est_tokens"} <= log_columns
