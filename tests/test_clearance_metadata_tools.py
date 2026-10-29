"""Clearance boundary for session and librarian tools (cloud must not see restricted notes)."""

from __future__ import annotations

from pathlib import Path

import pytest

from vault_context_mcp import server
from vault_context_mcp.config import VaultConfig
from vault_context_mcp.schemas import LibrarianIssue, LibrarianReport
from vault_context_mcp.server import (
    get_librarian_report,
    get_recent_sessions,
    get_session_handoff,
)

SESSION = """---
type: session
project: Orion
{extra}---

# {title}

## Summary

{summary}
"""


def _write(root: Path, rel: str, *, summary: str, extra: str = "") -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        SESSION.format(summary=summary, extra=extra, title=Path(rel).stem), encoding="utf-8"
    )


@pytest.fixture()
def vault(test_config: VaultConfig) -> VaultConfig:
    root = test_config.vault_root_path
    _write(root, "40-Thinking/Journal/01-Sessions/journal-session.md", summary="SECRET-RULE")
    _write(
        root,
        "20-Projects/Orion/01-Sessions/marked-session.md",
        summary="SECRET-FRONTMATTER",
        extra="sensitivity: restricted\n",
    )
    _write(root, "20-Projects/Orion/01-Sessions/open-session.md", summary="OPEN-SUMMARY")
    return test_config


def _summaries(sessions: list[dict[str, object]]) -> set[object]:
    return {session["summary"] for session in sessions}


def test_cloud_recent_sessions_exclude_restricted(
    vault: VaultConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VAULT_CONTEXT_CLEARANCE", "cloud")
    summaries = _summaries(get_recent_sessions(limit=50, config=vault))
    assert "OPEN-SUMMARY" in summaries
    assert "SECRET-RULE" not in summaries
    assert "SECRET-FRONTMATTER" not in summaries


def test_local_recent_sessions_include_restricted(
    vault: VaultConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VAULT_CONTEXT_CLEARANCE", "local")
    summaries = _summaries(get_recent_sessions(limit=50, config=vault))
    assert {"OPEN-SUMMARY", "SECRET-RULE", "SECRET-FRONTMATTER"} <= summaries


def test_missing_clearance_defaults_to_cloud(
    vault: VaultConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("VAULT_CONTEXT_CLEARANCE", raising=False)
    assert "SECRET-RULE" not in _summaries(get_recent_sessions(limit=50, config=vault))


def test_cloud_handoff_excludes_restricted(
    vault: VaultConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VAULT_CONTEXT_CLEARANCE", "cloud")
    handoff = str(get_session_handoff(project="Orion", limit=50, config=vault))
    assert "OPEN-SUMMARY" in handoff
    assert "SECRET" not in handoff


def _issue(path: str | None, n: int) -> LibrarianIssue:
    return LibrarianIssue(
        issue_id=f"i{n}",
        severity="info",
        category="chunkability",
        path=path,
        message=f"msg about {path}",
        recommendation="r",
    )


@pytest.fixture()
def fake_report(vault: VaultConfig, monkeypatch: pytest.MonkeyPatch) -> VaultConfig:
    issues = [
        _issue(None, 0),
        _issue("ACME/widget-design-notes.md", 1),
        _issue("40-Thinking/Journal/01-Sessions/journal-session.md", 2),
        _issue("20-Projects/Orion/01-Sessions/marked-session.md", 3),
        _issue("gone/deleted-note.md", 4),
        *[_issue("README.md", n) for n in range(5, 45)],
    ]

    def audit(config: VaultConfig, refresh_index: bool = False) -> LibrarianReport:
        return LibrarianReport(
            generated_at="2026-10-09T00:00:00+00:00",
            vault_root=str(config.vault_root_path),
            indexed_file_count=1,
            indexed_chunk_count=1,
            index_refreshed=False,
            issue_count=len(issues),
            issues=issues,
            next_actions=[],
        )

    monkeypatch.setattr(server, "audit_vault", audit)
    return vault


def test_cloud_librarian_withholds_restricted_and_missing_paths(
    fake_report: VaultConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VAULT_CONTEXT_CLEARANCE", "cloud")
    report = get_librarian_report(limit=100, config=fake_report)
    paths = {issue["path"] for issue in report["issues"]}  # type: ignore[union-attr]
    assert paths == {None, "README.md"}
    assert report["withheld_restricted_count"] == 4
    assert "ACME" not in str(report)
    assert "journal-session" not in str(report)


def test_librarian_output_is_bounded(
    fake_report: VaultConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VAULT_CONTEXT_CLEARANCE", "local")
    report = get_librarian_report(config=fake_report)
    assert len(report["issues"]) == 25  # type: ignore[arg-type]
    assert report["issues_omitted_count"] == 45 - 25
    assert report["issue_count"] == 45
    assert report["issue_counts_by_category"] == {"chunkability": 45}
