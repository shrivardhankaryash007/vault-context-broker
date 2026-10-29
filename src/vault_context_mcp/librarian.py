"""Local librarian for vault freshness and hygiene."""

from __future__ import annotations

import logging
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

from vault_context_mcp.config import VaultConfig
from vault_context_mcp.index_store import IndexStore, build_index, fingerprint_scanned_files
from vault_context_mcp.markdown_scanner import scan_vault
from vault_context_mcp.provenance import ProvenanceError
from vault_context_mcp.provenance import scan as scan_provenance
from vault_context_mcp.schemas import LibrarianIssue, LibrarianReport, ScannedMarkdownFile
from vault_context_mcp.utils import expand_path, utc_now_iso

HEADING_PREFIX = "# "
REQUIRED_CANONICAL_ANY = {
    "README.md",
    "00_CONTEXT_INDEX.md",
    "01_CURRENT_STATE.md",
    "02_ACTIVE_PROJECTS.md",
    "03_DECISIONS.md",
}


class LibrarianError(RuntimeError):
    """Raised when librarian automation cannot proceed."""


def audit_vault(config: VaultConfig, refresh_index: bool = False) -> LibrarianReport:
    """Audit vault organization and optionally refresh the index.

    Args:
        config: Runtime configuration.
        refresh_index: Whether to rebuild the index before reporting.

    Returns:
        Structured librarian report.
    """

    index_refreshed = False
    if refresh_index:
        build_index(config)
        index_refreshed = True
    files = scan_vault(config)
    issues = _audit_files(config, files)
    store = IndexStore(config.index_file_path)
    report = LibrarianReport(
        generated_at=utc_now_iso(),
        vault_root=str(config.vault_root_path),
        indexed_file_count=len(files),
        indexed_chunk_count=store.chunk_count(),
        index_refreshed=index_refreshed,
        issue_count=len(issues),
        issues=issues[: config.librarian.max_issues],
        next_actions=_next_actions(issues),
    )
    write_librarian_report(config, report)
    return report


def refresh_if_changed(
    config: VaultConfig, previous_fingerprint: str | None = None
) -> tuple[str, bool]:
    """Refresh the index when Markdown file metadata changed.

    Args:
        config: Runtime configuration.
        previous_fingerprint: Fingerprint from a prior scan.

    Returns:
        New fingerprint and whether the index was refreshed.
    """

    fingerprint = vault_fingerprint(config)
    if fingerprint == previous_fingerprint:
        return fingerprint, False
    if config.librarian.auto_refresh_index:
        build_index(config)
    if config.librarian.audit_on_refresh:
        audit_vault(config, refresh_index=False)
    if config.librarian.provenance.enabled:
        try:
            scan_provenance(config)
        except ProvenanceError as exc:
            logging.getLogger(__name__).warning("provenance scan failed: %s", exc)
    return fingerprint, True


def watch_vault(config: VaultConfig, once: bool = False) -> None:
    """Poll the vault for changes and keep the index fresh.

    Args:
        config: Runtime configuration.
        once: Run a single refresh cycle, useful for launch agents and tests.
    """

    if not config.librarian.enabled:
        raise LibrarianError("librarian.enabled is false")
    fingerprint: str | None = None
    while True:
        fingerprint, changed = refresh_if_changed(config, fingerprint)
        if changed:
            sys.stdout.write(f"{utc_now_iso()} refreshed vault-context index\n")
            sys.stdout.flush()
            if config.librarian.auto_apply_fixes:
                report = audit_vault(config, refresh_index=False)
                applied = apply_auto_fixes(config, report.issues)
                if applied:
                    sys.stdout.write(
                        f"{utc_now_iso()} applied {len(applied)} auto-fix(es): "
                        + ", ".join(applied)
                        + "\n"
                    )
                    sys.stdout.flush()
                    build_index(config)
        if config.session_log.summarize_unprocessed_on_watch:
            from vault_context_mcp.session_logger import process_unprocessed_sessions

            updated = process_unprocessed_sessions(config)
            if updated:
                sys.stdout.write(
                    f"{utc_now_iso()} summarized {len(updated)} unprocessed session(s)\n"
                )
                sys.stdout.flush()
        if once:
            return
        time.sleep(config.librarian.watch_interval_seconds)


def vault_fingerprint(config: VaultConfig) -> str:
    """Compute a cheap fingerprint from Markdown paths, mtimes, and sizes."""

    files = scan_vault(config)
    return fingerprint_scanned_files(files)


def write_librarian_report(config: VaultConfig, report: LibrarianReport) -> Path:
    """Write the latest librarian report outside the vault by default."""

    report_path = expand_path(config.librarian.report_path)
    if (
        config.librarian.write_reports_to_vault
        and config.librarian.require_manual_approval_for_vault_writes
    ):
        raise LibrarianError(
            "Refusing to write librarian report to vault while manual approval is required"
        )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(format_librarian_report(report), encoding="utf-8")
    json_path = report_path.with_suffix(".json")
    json_path.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return report_path


def format_librarian_report(report: LibrarianReport) -> str:
    """Format a human-readable librarian report."""

    lines = [
        "# Vault Librarian Report",
        "",
        f"- Generated: {report.generated_at}",
        f"- Vault root: `{report.vault_root}`",
        f"- Indexed files: {report.indexed_file_count}",
        f"- Indexed chunks: {report.indexed_chunk_count}",
        f"- Index refreshed: {report.index_refreshed}",
        f"- Issues: {report.issue_count}",
        "",
        "## Next Actions",
        "",
    ]
    if report.next_actions:
        lines.extend(f"- {action}" for action in report.next_actions)
    else:
        lines.append("- No high-priority actions.")
    lines.extend(["", "## Issues", ""])
    for issue in report.issues:
        location = f" `{issue.path}`" if issue.path else ""
        lines.append(f"- **{issue.severity.upper()} {issue.category}**{location}: {issue.message}")
        lines.append(f"  - Recommendation: {issue.recommendation}")
        if issue.proposed_action:
            lines.append(f"  - Proposed action: {issue.proposed_action}")
    return "\n".join(lines).rstrip() + "\n"


def apply_auto_fixes(config: VaultConfig, issues: list[LibrarianIssue]) -> list[str]:
    """Apply auto-fixable issues directly to vault files.

    Args:
        config: Runtime configuration.
        issues: Issues from a prior audit.

    Returns:
        List of issue IDs that were successfully applied.
    """

    applied: list[str] = []
    for issue in issues:
        if not issue.can_auto_fix or not issue.path:
            continue
        abs_path = config.vault_root_path / issue.path
        if not abs_path.exists():
            continue
        try:
            if issue.issue_id.startswith("missing-h1:"):
                _fix_missing_h1(abs_path)
                applied.append(issue.issue_id)
            elif issue.issue_id.startswith("templated-frontmatter:"):
                _fix_template_frontmatter(abs_path)
                applied.append(issue.issue_id)
        except OSError:
            pass
    return applied


def _fix_missing_h1(path: Path) -> None:
    """Prepend an H1 heading derived from the filename."""

    title = re.sub(r"^\d{4}-\d{2}-\d{2}-?", "", path.stem)
    title = re.sub(r"[-_]+", " ", title).strip().title() or path.stem
    text = path.read_text(encoding="utf-8")
    path.write_text(f"# {title}\n\n{text}", encoding="utf-8")


def _fix_template_frontmatter(path: Path) -> None:
    """Strip unresolved Handlebars-style template placeholders from the file."""

    text = path.read_text(encoding="utf-8")
    cleaned = re.sub(r"\{\{[^}]*\}\}", "", text)
    if cleaned != text:
        path.write_text(cleaned, encoding="utf-8")


def _audit_files(config: VaultConfig, files: list[ScannedMarkdownFile]) -> list[LibrarianIssue]:
    issues: list[LibrarianIssue] = []
    issues.extend(_missing_canonical_issues(config, files))
    issues.extend(_duplicate_file_name_issues(files))
    issues.extend(_heading_issues(files))
    issues.extend(_frontmatter_issues(files))
    issues.extend(_oversized_file_issues(files))
    return sorted(issues, key=_issue_sort_key)


def _missing_canonical_issues(
    config: VaultConfig, files: list[ScannedMarkdownFile]
) -> list[LibrarianIssue]:
    present = {Path(file.path).name for file in files}
    missing = sorted(REQUIRED_CANONICAL_ANY - present)
    if not missing:
        return []
    return [
        LibrarianIssue(
            issue_id="missing-canonical-files",
            severity="warning",
            category="canonical",
            message=f"Canonical operating-memory files are missing: {', '.join(missing)}",
            recommendation=(
                "Create or map canonical state/index/decision files so all LLM clients share "
                "the same current operating memory."
            ),
            can_auto_fix=False,
        )
    ]


def _duplicate_file_name_issues(files: list[ScannedMarkdownFile]) -> list[LibrarianIssue]:
    by_name: dict[str, list[str]] = defaultdict(list)
    for file in files:
        name = Path(file.path).name.lower()
        if name not in {"readme.md", "index.md"}:
            by_name[name].append(file.path)
    issues: list[LibrarianIssue] = []
    for name, paths in by_name.items():
        if len(paths) <= 1:
            continue
        issues.append(
            LibrarianIssue(
                issue_id=f"duplicate-file-name:{name}",
                severity="info",
                category="naming",
                message=f"{len(paths)} notes share the file name `{name}`.",
                recommendation=(
                    "Prefer unique, project-qualified note names when files may appear together "
                    "in LLM context packs."
                ),
                proposed_action="Review duplicate names; rename only after checking backlinks.",
            )
        )
    return issues


def _heading_issues(files: list[ScannedMarkdownFile]) -> list[LibrarianIssue]:
    issues: list[LibrarianIssue] = []
    for file in files:
        h1_count = sum(1 for line in file.raw_text.splitlines() if line.startswith(HEADING_PREFIX))
        if h1_count == 0:
            issues.append(
                LibrarianIssue(
                    issue_id=f"missing-h1:{file.path}",
                    severity="warning",
                    category="structure",
                    path=file.path,
                    message="Markdown note has no top-level H1 heading.",
                    recommendation="Add one clear H1 so chunks have stable anchors for citations.",
                    can_auto_fix=True,
                    proposed_action="Prepend H1 derived from filename.",
                )
            )
        elif h1_count > 1:
            issues.append(
                LibrarianIssue(
                    issue_id=f"multiple-h1:{file.path}",
                    severity="info",
                    category="structure",
                    path=file.path,
                    message=f"Markdown note has {h1_count} top-level H1 headings.",
                    recommendation="Use one H1 title and H2/H3 headings for sections.",
                    can_auto_fix=False,
                )
            )
    return issues


def _frontmatter_issues(files: list[ScannedMarkdownFile]) -> list[LibrarianIssue]:
    issues: list[LibrarianIssue] = []
    for file in files:
        if "{{" not in file.raw_text[:500]:
            continue
        issues.append(
            LibrarianIssue(
                issue_id=f"templated-frontmatter:{file.path}",
                severity="info",
                category="metadata",
                path=file.path,
                message="Note appears to contain unresolved template syntax near the top.",
                recommendation=(
                    "Resolve template placeholders in canonical notes so different LLM clients "
                    "do not interpret them as instructions or missing data."
                ),
                can_auto_fix=True,
                proposed_action="Strip {{...}} template placeholders.",
            )
        )
    return issues


def _oversized_file_issues(files: list[ScannedMarkdownFile]) -> list[LibrarianIssue]:
    issues: list[LibrarianIssue] = []
    for file in files:
        word_count = len(file.raw_text.split())
        if word_count < 5000:
            continue
        issues.append(
            LibrarianIssue(
                issue_id=f"oversized-note:{file.path}",
                severity="info",
                category="chunkability",
                path=file.path,
                message=f"Large note has about {word_count} words.",
                recommendation="Split very large notes into stable sections or add a context index.",
                can_auto_fix=False,
            )
        )
    return issues


def _next_actions(issues: list[LibrarianIssue]) -> list[str]:
    counts = Counter(issue.category for issue in issues)
    actions: list[str] = []
    if counts["canonical"]:
        actions.append("Create canonical current-state/index/decision files for shared LLM memory.")
    if counts["structure"]:
        actions.append("Fix missing or repeated H1 headings in high-value notes first.")
    if counts["naming"]:
        actions.append("Review duplicate note names that may confuse retrieved citations.")
    if counts["metadata"]:
        actions.append("Resolve template placeholders in canonical or frequently retrieved notes.")
    if counts["chunkability"]:
        actions.append("Split oversized notes or add summary/index sections.")
    return actions[:8]


def _issue_sort_key(issue: LibrarianIssue) -> tuple[int, str, str]:
    severity_rank = {"error": 0, "warning": 1, "info": 2}
    return (severity_rank[issue.severity], issue.category, issue.path or "")
