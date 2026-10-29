"""Direct MCP tool function tests."""

from __future__ import annotations

import pytest

from vault_context_mcp.index_store import IndexStore, build_index
from vault_context_mcp.server import (
    FRICTIONLESS_SESSION_LOGGING_PROMPT,
    get_context_pack,
    get_decisions,
    get_librarian_report,
    get_open_questions,
    get_project_state,
    get_recent_sessions,
    get_session_handoff,
    process_sessions,
    refresh_index,
    search_vault,
)


def test_server_tool_functions_can_be_called_directly(test_config) -> None:  # type: ignore[no-untyped-def]
    build_index(test_config)

    pack = get_context_pack("Continue ATLAS architecture", project="ATLAS", config=test_config)
    search = search_vault("ATLAS project state", project="ATLAS", config=test_config)
    state = get_project_state("ATLAS", config=test_config)
    decisions = get_decisions(project="ATLAS", config=test_config)
    questions = get_open_questions(project="ATLAS", config=test_config)
    refresh = refresh_index(force=False, config=test_config)
    report = get_librarian_report(config=test_config)
    sessions = get_recent_sessions(config=test_config)
    handoff = get_session_handoff(project="Orion", config=test_config)

    assert pack["task"] == "Continue ATLAS architecture"
    assert search
    assert state
    assert decisions
    assert questions
    assert refresh["refreshed"] is False
    assert report["vault_root"] == str(test_config.vault_root_path)
    assert sessions
    assert handoff["project"] == "Orion"
    assert "log this chat" in FRICTIONLESS_SESSION_LOGGING_PROMPT


def test_process_sessions_returns_updated_list(test_config) -> None:  # type: ignore[no-untyped-def]
    result = process_sessions(config=test_config)

    assert "updated" in result
    assert "count" in result
    assert isinstance(result["updated"], list)
    assert result["count"] == len(result["updated"])


def test_search_vault_tool_defaults_to_cloud_clearance_when_env_unset(
    test_config,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    build_index(test_config)
    monkeypatch.delenv("VAULT_CONTEXT_CLEARANCE", raising=False)

    results = search_vault("widget gear actuator station", top_k=20, config=test_config)

    assert results == []


def test_search_vault_tool_grants_local_clearance_via_env(
    test_config,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    build_index(test_config)

    monkeypatch.setenv("VAULT_CONTEXT_CLEARANCE", "cloud")
    cloud_results = search_vault("widget gear actuator station", top_k=20, config=test_config)
    assert not any(chunk["path"] == "ACME/widget-design-notes.md" for chunk in cloud_results)

    monkeypatch.setenv("VAULT_CONTEXT_CLEARANCE", "local")
    local_results = search_vault("widget gear actuator station", top_k=20, config=test_config)
    assert any(chunk["path"] == "ACME/widget-design-notes.md" for chunk in local_results)


@pytest.mark.parametrize(
    "query",
    [
        "ACME widget azimuth drive",
        "sensor actuator station engagement",
        "worm gear ratio sensor mast",
    ],
)
def test_three_acme_flavored_queries_leak_nothing_under_cloud_clearance(
    test_config,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
    query: str,
) -> None:
    """ADR 0036 M1 acceptance: no ACME-flavored query surfaces ACME/** to a cloud caller."""

    build_index(test_config)
    monkeypatch.delenv("VAULT_CONTEXT_CLEARANCE", raising=False)

    pack = get_context_pack(query, mode="deep", config=test_config)
    search_results = search_vault(query, top_k=20, config=test_config)

    assert all(
        source["path"] != "ACME/widget-design-notes.md" for source in pack["relevant_sources"]
    )
    assert all(chunk["path"] != "ACME/widget-design-notes.md" for chunk in search_results)


def test_search_vault_tool_logs_client_and_clearance_to_ledger(
    test_config,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    build_index(test_config)
    monkeypatch.setenv("VAULT_CONTEXT_CLEARANCE", "cloud")
    monkeypatch.setenv("VAULT_CONTEXT_CLIENT", "codex")

    search_vault("ATLAS project state", project="ATLAS", config=test_config)

    with IndexStore(test_config.index_file_path).connect() as connection:
        row = connection.execute(
            "SELECT tool_name, client, clearance, chunks_returned FROM tool_call_log "
            "ORDER BY id DESC LIMIT 1"
        ).fetchone()

    assert row["tool_name"] == "search_vault"
    assert row["client"] == "codex"
    assert row["clearance"] == "cloud"
    assert row["chunks_returned"] is not None
