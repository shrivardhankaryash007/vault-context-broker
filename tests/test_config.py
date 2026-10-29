"""Config tests."""

from __future__ import annotations

from pathlib import Path

import yaml

from vault_context_mcp.config import load_config


def test_config_loads_from_yaml(sample_vault: Path, tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "vault_root": str(sample_vault),
                "index_path": str(tmp_path / "index.sqlite3"),
                "canonical_files": ["PROJECT_STATE.md"],
                "ignore_dirs": [".obsidian"],
            }
        ),
        encoding="utf-8",
    )

    config = load_config(path)

    assert config.vault_root_path == sample_vault.resolve()
    assert config.index_file_path == tmp_path / "index.sqlite3"
    assert "project_state.md" in config.canonical_file_names
