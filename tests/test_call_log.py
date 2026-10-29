"""Locked acceptance tests: every MCP tool call appends one metadata-only log line.

Workspace plan ``plans/flow-edges-wiring-2026-10`` (packet P2). The log feeds the
Agent OS lake so the Cockpit Flow tab can light its "Claude Code -> Vault" edge.
Executors must not edit this file.
"""

from __future__ import annotations

import json
import stat
from pathlib import Path
from typing import Any

import anyio
import pytest
from mcp import types
from mcp.shared.memory import create_connected_server_and_client_session

from vault_context_mcp import call_log
from vault_context_mcp.server import create_mcp_server

KEYS = {"ts", "call_id", "tool", "client", "ok", "ms"}


def _server() -> Any:
    server = create_mcp_server()

    @server.tool(name="ping_test")
    def ping_test(secret_query: str) -> str:
        return "pong"

    @server.tool(name="boom_test")
    def boom_test(secret_query: str) -> str:
        raise RuntimeError("nope")

    return server


def _call(server: Any, client: str | None, *tools: str) -> None:
    async def go() -> None:
        info = types.Implementation(name=client, version="0") if client else None
        async with create_connected_server_and_client_session(server, client_info=info) as session:
            for tool in tools:
                await session.call_tool(tool, {"secret_query": "private vault words"})

    anyio.run(go)


def _lines(path: Path) -> list[dict[str, object]]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x]


@pytest.fixture()
def log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "mcp" / "calls.jsonl"
    monkeypatch.setenv("AGENTIC_OS_VAULT_MCP_LOG", str(path))
    return path


def test_default_path() -> None:
    expected = Path.home() / ".local/share/agentic-os/mcp/vault-context-mcp.jsonl"
    assert expected == call_log.DEFAULT_LOG_PATH


def test_each_call_logs_metadata_only(log: Path) -> None:
    _call(_server(), "claude-code", "ping_test", "boom_test")

    rows = _lines(log)
    assert [r["tool"] for r in rows] == ["ping_test", "boom_test"]
    assert all(set(r) == KEYS for r in rows)
    assert [r["ok"] for r in rows] == [True, False]
    assert all(r["client"] == "claude-code" for r in rows)
    assert all(isinstance(r["ms"], int) and r["ms"] >= 0 for r in rows)
    assert len({r["call_id"] for r in rows}) == 2
    assert all(str(r["ts"]).endswith("Z") and len(str(r["ts"])) == 20 for r in rows)
    assert "private vault words" not in log.read_text(encoding="utf-8")
    assert "nope" not in log.read_text(encoding="utf-8")
    assert stat.S_IMODE(log.stat().st_mode) == 0o600


def test_client_name_is_sanitised_or_unknown(log: Path) -> None:
    _call(_server(), "Weird Client/1 <x>", "ping_test")
    _call(_server(), None, "ping_test")

    clients = [r["client"] for r in _lines(log)]
    assert clients[0] == "unknown"  # not [A-Za-z0-9._-]{1,40}
    # The SDK sends a default clientInfo when none is given; any valid name passes.
    assert isinstance(clients[1], str) and clients[1]


def test_log_failure_never_breaks_the_tool(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("x", encoding="utf-8")
    monkeypatch.setenv("AGENTIC_OS_VAULT_MCP_LOG", str(blocker / "calls.jsonl"))

    _call(_server(), "claude-code", "ping_test")  # must not raise


def test_empty_env_disables_logging(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENTIC_OS_VAULT_MCP_LOG", "")
    assert call_log.log_path() is None
    _call(_server(), "claude-code", "ping_test")
    assert not any(tmp_path.rglob("*.jsonl"))
