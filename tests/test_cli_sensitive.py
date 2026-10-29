"""Tests for sensitive marking CLI commands."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import yaml
from typer.testing import CliRunner

from vault_context_mcp.cli import app


def test_cli_mark_sensitive_success(tmp_path: Path, sample_vault: Path, test_config: any) -> None:
    # Write isolated test config
    config_file = tmp_path / "test_config.yaml"
    config_file.write_text(yaml.safe_dump(test_config.model_dump()), encoding="utf-8")

    # Create a test note
    test_note = sample_vault / "test-cli-mark.md"
    test_note.write_text("# Test Note\n\nSome content.", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["mark-sensitive", str(test_note)],
        env={"VAULT_CONTEXT_CONFIG": str(config_file)},
    )

    assert result.exit_code == 0
    assert "Successfully marked" in result.stdout

    # Verify write
    content = test_note.read_text(encoding="utf-8")
    assert "sensitivity: restricted" in content
    assert "sensitive" in content
    assert content.endswith("\n# Test Note\n\nSome content.")


def test_cli_mark_sensitive_relative_path(
    tmp_path: Path, sample_vault: Path, test_config: any
) -> None:
    config_file = tmp_path / "test_config.yaml"
    config_file.write_text(yaml.safe_dump(test_config.model_dump()), encoding="utf-8")

    # We write a note inside sample_vault/notes
    test_note = sample_vault / "notes" / "test-rel.md"
    test_note.parent.mkdir(parents=True, exist_ok=True)
    test_note.write_text("# Relative Test", encoding="utf-8")

    runner = CliRunner()
    # Execute command relative to vault root
    # Typer command should resolve relative to vault_root when it doesn't exist relative to cwd
    result = runner.invoke(
        app,
        ["mark-sensitive", "notes/test-rel.md"],
        env={"VAULT_CONTEXT_CONFIG": str(config_file)},
    )

    assert result.exit_code == 0
    assert "Successfully marked" in result.stdout

    content = test_note.read_text(encoding="utf-8")
    assert "sensitivity: restricted" in content


def test_cli_mark_sensitive_already_sensitive(
    tmp_path: Path, sample_vault: Path, test_config: any
) -> None:
    config_file = tmp_path / "test_config.yaml"
    config_file.write_text(yaml.safe_dump(test_config.model_dump()), encoding="utf-8")

    test_note = sample_vault / "test-cli-noop.md"
    test_note.write_text(
        "---\nsensitivity: restricted\ntags:\n- sensitive\n---\n# Already set",
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["mark-sensitive", str(test_note)],
        env={"VAULT_CONTEXT_CONFIG": str(config_file)},
    )

    assert result.exit_code == 0
    assert "already sensitive" in result.stdout


def test_cli_backfill_sensitive_dry_run(
    tmp_path: Path, sample_vault: Path, test_config: any
) -> None:
    config_file = tmp_path / "test_config.yaml"
    config_file.write_text(yaml.safe_dump(test_config.model_dump()), encoding="utf-8")

    # Create sub-directory with multiple notes
    sub_dir = sample_vault / "Self-Model-Test"
    sub_dir.mkdir(parents=True, exist_ok=True)

    note_a = sub_dir / "note_a.md"
    note_a.write_text("Note A", encoding="utf-8")

    note_b = sub_dir / "note_b.md"
    note_b.write_text("---\ntitle: B\n---\nNote B", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["backfill-sensitive", "--scope", "Self-Model-Test", "--dry-run"],
        env={"VAULT_CONTEXT_CONFIG": str(config_file)},
    )

    assert result.exit_code == 0
    assert "DRY-RUN MODE" in result.stdout
    assert "Would modify 2 files." in result.stdout
    assert "Would mark sensitive: Self-Model-Test/note_a.md" in result.stdout

    # Verify no files were actually modified
    assert "sensitivity:" not in note_a.read_text(encoding="utf-8")
    assert "sensitivity:" not in note_b.read_text(encoding="utf-8")


def test_cli_backfill_sensitive_apply(tmp_path: Path, sample_vault: Path, test_config: any) -> None:
    config_file = tmp_path / "test_config.yaml"
    config_file.write_text(yaml.safe_dump(test_config.model_dump()), encoding="utf-8")

    sub_dir = sample_vault / "Self-Model-Test-Apply"
    sub_dir.mkdir(parents=True, exist_ok=True)

    note_a = sub_dir / "note_a.md"
    note_a.write_text("Note A", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["backfill-sensitive", "--scope", "Self-Model-Test-Apply", "--apply"],
        env={"VAULT_CONTEXT_CONFIG": str(config_file)},
    )

    assert result.exit_code == 0
    assert "DRY-RUN MODE" not in result.stdout
    assert "Successfully modified 1 files." in result.stdout

    # Verify modification
    assert "sensitivity: restricted" in note_a.read_text(encoding="utf-8")


def test_cli_mark_sensitive_outside_vault_root(
    tmp_path: Path, sample_vault: Path, test_config: any
) -> None:
    config_file = tmp_path / "test_config.yaml"
    config_file.write_text(yaml.safe_dump(test_config.model_dump()), encoding="utf-8")

    # Create a file outside the vault root
    outside_file = tmp_path / "outside.md"
    outside_file.write_text("# Outside Vault", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["mark-sensitive", str(outside_file)],
        env={"VAULT_CONTEXT_CONFIG": str(config_file)},
    )

    assert result.exit_code == 1
    assert "outside vault root" in (result.output or "")


def test_cli_backfill_sensitive_outside_vault_root(
    tmp_path: Path, sample_vault: Path, test_config: any
) -> None:
    config_file = tmp_path / "test_config.yaml"
    config_file.write_text(yaml.safe_dump(test_config.model_dump()), encoding="utf-8")

    # Create a directory outside the vault root
    outside_dir = tmp_path / "outside_dir"
    outside_dir.mkdir(parents=True, exist_ok=True)
    outside_file = outside_dir / "note.md"
    outside_file.write_text("# Outside Vault", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["backfill-sensitive", "--scope", str(outside_dir), "--apply"],
        env={"VAULT_CONTEXT_CONFIG": str(config_file)},
    )

    assert result.exit_code == 1
    assert "outside vault root" in (result.output or "")


@patch("vault_context_mcp.cli.ollama_available", return_value=True)
@patch("vault_context_mcp.cli.query_ollama_proposal")
def test_cli_propose_sensitive(
    mock_query: any, mock_available: any, tmp_path: Path, sample_vault: Path, test_config: any
) -> None:
    config_file = tmp_path / "test_config.yaml"
    config_file.write_text(yaml.safe_dump(test_config.model_dump()), encoding="utf-8")

    # Mock Ollama proposal return
    mock_query.return_value = {
        "is_sensitive": True,
        "reason": "Contains credentials and self-reflection.",
        "confidence": 0.95,
    }

    # Create a test note in vault
    test_note = sample_vault / "notes" / "test-audit.md"
    test_note.parent.mkdir(parents=True, exist_ok=True)
    test_note.write_text("Secret diary details...", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["propose-sensitive", "--scope", "notes/test-audit.md"],
        env={"VAULT_CONTEXT_CONFIG": str(config_file)},
    )

    assert result.exit_code == 0
    assert "Scanning 1 files" in result.stdout
    assert "Candidate: notes/test-audit.md" in result.stdout
    assert "Reason: Contains credentials and self-reflection." in result.stdout
    assert "Confidence: 0.95" in result.stdout
    assert "Audit complete. Queried: 1. Proposed: 1." in result.stdout
