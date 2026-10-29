"""CLI / client-config installer tests.

These tests never touch a real client config on disk (Claude Desktop, Codex,
Gemini) — only tmp_path fixtures — so they are safe to run on any machine.
"""

from __future__ import annotations

import json
from pathlib import Path

from vault_context_mcp.cli import mcp_server_entry, remove_mcp_server_from_json_config


def test_mcp_server_entry_includes_clearance_and_client() -> None:
    entry = mcp_server_entry(
        python_path="/usr/bin/python3",
        config_path="/tmp/vault-context-mcp-config.yaml",
        client="codex",
        clearance="cloud",
    )

    assert entry["env"]["VAULT_CONTEXT_CLEARANCE"] == "cloud"
    assert entry["env"]["VAULT_CONTEXT_CLIENT"] == "codex"


def test_mcp_server_entry_defaults_to_cloud_and_unknown_client() -> None:
    entry = mcp_server_entry(
        python_path="/usr/bin/python3",
        config_path="/tmp/vault-context-mcp-config.yaml",
    )

    assert entry["env"]["VAULT_CONTEXT_CLEARANCE"] == "cloud"
    assert entry["env"]["VAULT_CONTEXT_CLIENT"] == "unknown"


def test_remove_mcp_server_from_json_config_removes_present_entry(tmp_path: Path) -> None:
    config_path = tmp_path / "claude_desktop_config.json"
    config_path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "obsidian-vault": {"command": "npx", "args": ["-y", "server-filesystem"]},
                    "vault-context-mcp": {"command": "/usr/bin/python3"},
                }
            }
        ),
        encoding="utf-8",
    )

    result = remove_mcp_server_from_json_config(config_path, "obsidian-vault")

    assert result["removed"] is True
    assert result["backup_path"]
    assert Path(str(result["backup_path"])).exists()
    remaining = json.loads(config_path.read_text(encoding="utf-8"))
    assert "obsidian-vault" not in remaining["mcpServers"]
    assert "vault-context-mcp" in remaining["mcpServers"]


def test_remove_mcp_server_from_json_config_noop_when_absent(tmp_path: Path) -> None:
    config_path = tmp_path / "claude_desktop_config.json"
    original = json.dumps({"mcpServers": {"vault-context-mcp": {"command": "/usr/bin/python3"}}})
    config_path.write_text(original, encoding="utf-8")

    result = remove_mcp_server_from_json_config(config_path, "obsidian-vault")

    assert result["removed"] is False
    assert config_path.read_text(encoding="utf-8") == original


def test_remove_mcp_server_from_json_config_noop_when_file_missing(tmp_path: Path) -> None:
    result = remove_mcp_server_from_json_config(tmp_path / "missing.json", "obsidian-vault")

    assert result["removed"] is False
