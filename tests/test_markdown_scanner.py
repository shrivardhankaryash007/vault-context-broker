"""Markdown scanner tests."""

from __future__ import annotations

from vault_context_mcp.markdown_scanner import scan_vault
from vault_context_mcp.security import SecurityError, resolve_and_validate_path


def test_scanner_finds_sample_markdown_files(test_config) -> None:  # type: ignore[no-untyped-def]
    files = scan_vault(test_config)
    paths = {file.path for file in files}

    assert "01_CURRENT_STATE.md" in paths
    assert "projects/ATLAS/PROJECT_STATE.md" in paths


def test_scanner_ignores_obsidian_and_archive(test_config) -> None:  # type: ignore[no-untyped-def]
    files = scan_vault(test_config)
    paths = {file.path for file in files}

    assert ".obsidian/ignored.md" not in paths
    assert "archive/old.md" not in paths


def test_scanner_supports_glob_style_ignore_dirs(test_config, tmp_path) -> None:  # type: ignore[no-untyped-def]
    backup_dir = tmp_path / "Main_Vault_backup_20260318"
    backup_dir.mkdir(exist_ok=True)
    backup_file = backup_dir / "ignored.md"
    backup_file.write_text("# Ignored Backup\n", encoding="utf-8")
    config = test_config.model_copy(
        update={"vault_root": str(tmp_path), "ignore_dirs": ["*_backup_*"]}
    )

    files = scan_vault(config)
    paths = {file.path for file in files}

    assert "Main_Vault_backup_20260318/ignored.md" not in paths


def test_security_rejects_paths_outside_vault(test_config) -> None:  # type: ignore[no-untyped-def]
    try:
        resolve_and_validate_path("../outside.md", test_config.vault_root_path)
    except SecurityError:
        return
    raise AssertionError("expected SecurityError")
