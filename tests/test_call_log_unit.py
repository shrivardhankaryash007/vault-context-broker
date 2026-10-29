"""Unit tests for metadata-only MCP call logging."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import anyio
from mcp.shared.memory import create_connected_server_and_client_session

from vault_context_mcp import call_log
from vault_context_mcp.server import create_mcp_server


def test_record_call_writes_compact_metadata(tmp_path: Path, monkeypatch: Any) -> None:
    """A call record contains only the defined metadata fields."""

    path = tmp_path / "nested" / "calls.jsonl"
    monkeypatch.setenv(call_log.LOG_ENV, str(path))

    call_log.record_call(
        "search_vault",
        "claude-code",
        True,
        7,
        now=datetime(2026, 10, 15, 12, 30, 45, tzinfo=UTC),
    )

    line = path.read_text(encoding="utf-8")
    row = json.loads(line)
    assert line.endswith("\n")
    assert set(row) == {"ts", "call_id", "tool", "client", "ok", "ms"}
    assert row["ts"] == "2026-10-15T12:30:45Z"
    assert row["tool"] == "search_vault"
    assert row["client"] == "claude-code"
    assert row["ok"] is True
    assert row["ms"] == 7


def test_tool_error_is_returned_to_client(monkeypatch: Any, tmp_path: Path) -> None:
    """Logging preserves the MCP client's normal tool-error response."""

    monkeypatch.setenv(call_log.LOG_ENV, str(tmp_path / "calls.jsonl"))
    server = create_mcp_server()

    @server.tool(name="boom_test")
    def boom_test() -> str:
        raise RuntimeError("nope")

    async def go() -> Any:
        async with create_connected_server_and_client_session(server) as session:
            return await session.call_tool("boom_test", {})

    result = anyio.run(go)

    assert result.isError is True
    assert any("nope" in item.text for item in result.content if hasattr(item, "text"))
    row = json.loads((tmp_path / "calls.jsonl").read_text(encoding="utf-8"))
    assert row["ok"] is False
