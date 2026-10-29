"""Retriever tests."""

from __future__ import annotations

from pathlib import Path

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from vault_context_mcp.config import LibrarianConfig, VaultConfig
from vault_context_mcp.index_store import build_index
from vault_context_mcp.retriever import chunks_for_file_name, retrieve_chunks, search_vault


def test_search_returns_project_state_for_project_query(test_config) -> None:  # type: ignore[no-untyped-def]
    build_index(test_config)

    results = search_vault(test_config, "ATLAS project state", top_k=5, project="ATLAS")

    assert any(result.path == "projects/ATLAS/PROJECT_STATE.md" for result in results)


def test_canonical_files_are_boosted(test_config) -> None:  # type: ignore[no-untyped-def]
    build_index(test_config)

    results = search_vault(test_config, "current state", top_k=3)

    assert results[0].metadata["is_canonical"] is True


def test_search_self_refreshes_stale_index(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    note = vault / "01_CURRENT_STATE.md"
    note.write_text("# Current State\n\n- Initial state.\n", encoding="utf-8")
    config = VaultConfig(
        vault_root=str(vault),
        index_path=str(tmp_path / "index.sqlite3"),
        canonical_files=["01_CURRENT_STATE.md"],
        ignore_dirs=[],
        librarian=LibrarianConfig(report_path=str(tmp_path / "report.md")),
    )
    build_index(config)

    note.write_text("# Current State\n\n- zephyr-context-refresh-marker.\n", encoding="utf-8")
    results = search_vault(config, "zephyr-context-refresh-marker", top_k=3)

    assert results
    assert "zephyr-context-refresh-marker" in results[0].text


def test_search_vault_excludes_restricted_under_cloud_clearance(test_config) -> None:  # type: ignore[no-untyped-def]
    build_index(test_config)

    cloud_results = search_vault(test_config, "widget gear actuator", top_k=10, clearance="cloud")
    local_results = search_vault(test_config, "widget gear actuator", top_k=10, clearance="local")

    assert cloud_results == []
    assert any(result.path == "ACME/widget-design-notes.md" for result in local_results)


def test_search_vault_defaults_to_cloud_clearance(test_config) -> None:  # type: ignore[no-untyped-def]
    build_index(test_config)

    results = search_vault(test_config, "widget gear actuator", top_k=10)

    assert results == []


def test_chunks_for_file_name_excludes_restricted_under_cloud_clearance(test_config) -> None:  # type: ignore[no-untyped-def]
    build_index(test_config)

    cloud_chunks = chunks_for_file_name(test_config, {"widget-design-notes.md"}, clearance="cloud")
    local_chunks = chunks_for_file_name(test_config, {"widget-design-notes.md"}, clearance="local")

    assert cloud_chunks == []
    assert local_chunks


def test_retrieve_chunks_excludes_restricted_under_cloud_clearance(test_config) -> None:  # type: ignore[no-untyped-def]
    build_index(test_config)

    cloud_chunks = retrieve_chunks(test_config, "widget gear actuator", clearance="cloud")
    local_chunks = retrieve_chunks(test_config, "widget gear actuator", clearance="local")

    assert all(chunk.path != "ACME/widget-design-notes.md" for chunk in cloud_chunks)
    assert any(chunk.path == "ACME/widget-design-notes.md" for chunk in local_chunks)


@settings(
    max_examples=25,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(query=st.text(min_size=1, max_size=40))
def test_no_query_string_leaks_restricted_chunks_under_cloud_clearance(
    test_config,  # type: ignore[no-untyped-def]
    query: str,
) -> None:
    build_index(test_config)

    results = search_vault(test_config, query, top_k=50, clearance="cloud")

    assert all(result.sensitivity == "open" for result in results)
    assert all(result.path != "ACME/widget-design-notes.md" for result in results)
