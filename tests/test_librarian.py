"""Librarian tests."""

from __future__ import annotations

from pathlib import Path

from vault_context_mcp.config import LibrarianConfig, VaultConfig
from vault_context_mcp.index_store import build_index
from vault_context_mcp.librarian import (
    apply_auto_fixes,
    audit_vault,
    refresh_if_changed,
    vault_fingerprint,
)


def test_librarian_audit_returns_report_and_writes_files(test_config) -> None:  # type: ignore[no-untyped-def]
    build_index(test_config)

    report = audit_vault(test_config)

    assert report.vault_root == str(test_config.vault_root_path)
    assert report.indexed_file_count >= 9
    assert report.indexed_chunk_count >= 9
    assert Path(test_config.librarian.report_path).exists()
    assert Path(test_config.librarian.report_path).with_suffix(".json").exists()


def test_librarian_detects_missing_h1(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    note = vault / "NoHeading.md"
    note.write_text("No heading here.\n\nJust prose.", encoding="utf-8")
    config = VaultConfig(
        vault_root=str(vault),
        index_path=str(tmp_path / "index.sqlite3"),
        ignore_dirs=[],
        librarian=LibrarianConfig(report_path=str(tmp_path / "report.md")),
    )

    report = audit_vault(config, refresh_index=True)

    assert any(issue.category == "structure" for issue in report.issues)
    assert any(issue.issue_id == "missing-canonical-files" for issue in report.issues)


def test_apply_auto_fixes_adds_h1_from_filename(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    note = vault / "2026-05-07-my-great-session.md"
    note.write_text("No heading here.\n\nJust prose.", encoding="utf-8")
    config = VaultConfig(
        vault_root=str(vault),
        index_path=str(tmp_path / "index.sqlite3"),
        ignore_dirs=[],
        librarian=LibrarianConfig(report_path=str(tmp_path / "report.md"), auto_apply_fixes=True),
    )
    report = audit_vault(config, refresh_index=True)
    h1_issues = [i for i in report.issues if i.issue_id.startswith("missing-h1:")]
    assert h1_issues, "expected at least one missing-h1 issue"

    applied = apply_auto_fixes(config, report.issues)

    assert any("missing-h1" in fid for fid in applied)
    updated_text = note.read_text(encoding="utf-8")
    assert updated_text.startswith("# My Great Session\n")


def test_apply_auto_fixes_strips_template_placeholders(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    note = vault / "template_note.md"
    note.write_text(
        "---\ntitle: {{title}}\ndate: {{date}}\n---\n\n# Real Note\n\nContent here.\n",
        encoding="utf-8",
    )
    config = VaultConfig(
        vault_root=str(vault),
        index_path=str(tmp_path / "index.sqlite3"),
        ignore_dirs=[],
        librarian=LibrarianConfig(report_path=str(tmp_path / "report.md"), auto_apply_fixes=True),
    )
    report = audit_vault(config, refresh_index=True)
    template_issues = [i for i in report.issues if i.issue_id.startswith("templated-frontmatter:")]
    assert template_issues, "expected at least one templated-frontmatter issue"

    applied = apply_auto_fixes(config, report.issues)

    assert any("templated-frontmatter" in fid for fid in applied)
    updated_text = note.read_text(encoding="utf-8")
    assert "{{" not in updated_text


def test_refresh_if_changed_rebuilds_after_markdown_change(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    changed_file = vault / "01_CURRENT_STATE.md"
    changed_file.write_text("# Current State\n\n- Initial state.\n", encoding="utf-8")
    config = VaultConfig(
        vault_root=str(vault),
        index_path=str(tmp_path / "index.sqlite3"),
        canonical_files=["01_CURRENT_STATE.md"],
        ignore_dirs=[],
        librarian=LibrarianConfig(report_path=str(tmp_path / "report.md")),
    )
    fingerprint = vault_fingerprint(config)
    changed_file.write_text(
        changed_file.read_text(encoding="utf-8") + "\n- Test-only changed state.\n",
        encoding="utf-8",
    )

    new_fingerprint, refreshed = refresh_if_changed(config, fingerprint)

    assert refreshed is True
    assert new_fingerprint != fingerprint
