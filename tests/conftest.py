"""Shared test fixtures."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from vault_context_mcp.config import LibrarianConfig, VaultConfig


@pytest.fixture()
def sample_vault(tmp_path: Path) -> Path:
    """Return the sample vault path."""

    source = Path(__file__).parent / "fixtures" / "sample_vault"
    target = tmp_path / "sample_vault"
    shutil.copytree(source, target)
    return target


@pytest.fixture()
def test_config(sample_vault: Path, tmp_path: Path) -> VaultConfig:
    """Return an isolated runtime config for tests."""

    return VaultConfig(
        vault_root=str(sample_vault),
        index_path=str(tmp_path / "index.sqlite3"),
        sensitivity_map_path=str(Path(__file__).parent / "fixtures" / "sensitivity_map.yaml"),
        canonical_files=[
            "README.md",
            "00_CONTEXT_INDEX.md",
            "01_CURRENT_STATE.md",
            "02_ACTIVE_PROJECTS.md",
            "03_DECISIONS.md",
            "AGENTS.md",
            "PROJECT_STATE.md",
            "DECISIONS.md",
            "OPEN_QUESTIONS.md",
            "NEXT_ACTIONS.md",
        ],
        ignore_dirs=[".git", ".obsidian", "archive"],
        librarian=LibrarianConfig(report_path=str(tmp_path / "librarian_report.md")),
    )
