"""Command-line interface for vault-context-mcp."""

from __future__ import annotations

import json
import os
import plistlib
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Annotated

import typer

from vault_context_mcp.config import (
    ConfigError,
    default_config_path,
    load_config,
    missing_config_message,
)
from vault_context_mcp.context_builder import build_context_pack
from vault_context_mcp.index_store import build_index, sqlite_supports_fts5
from vault_context_mcp.librarian import audit_vault, watch_vault
from vault_context_mcp.provenance import (
    ProvenanceError,
)
from vault_context_mcp.provenance import (
    propose as provenance_propose,
)
from vault_context_mcp.provenance import (
    report as provenance_report,
)
from vault_context_mcp.provenance import (
    review as provenance_review,
)
from vault_context_mcp.provenance import (
    scan as provenance_scan,
)
from vault_context_mcp.provenance import (
    trace as provenance_trace,
)
from vault_context_mcp.retriever import search_vault
from vault_context_mcp.schemas import ContextMode
from vault_context_mcp.sensitive_audit import query_ollama_proposal
from vault_context_mcp.sensitive_marker import (
    mark_content_sensitive,
    parse_frontmatter_and_body,
)
from vault_context_mcp.sensitivity import resolve_clearance
from vault_context_mcp.server import run_stdio_server
from vault_context_mcp.session_logger import (
    build_session_handoff,
    log_llm_session,
    process_unprocessed_sessions,
    recent_sessions,
    request_from_json_payload,
)

app = typer.Typer(help="Local-first MCP context broker for Obsidian vaults.")
SERVER_NAME = "vault-context-mcp"
SERVER_MODULE = "vault_context_mcp"


@app.command("benchmark-retrieval")
def benchmark_retrieval_command() -> None:
    """Run the isolated synthetic retrieval gate without loading user config."""
    from vault_context_mcp.retrieval_benchmark import run_retrieval_benchmark

    report = run_retrieval_benchmark()
    typer.echo(json.dumps(report.model_dump(), indent=2))
    if not report.passed:
        raise typer.Exit(code=1)


@app.command()
def doctor() -> None:
    """Check local configuration and runtime prerequisites."""

    typer.echo(f"Python: {sys.version.split()[0]}")
    config_path = default_config_path()
    if config_path is None:
        typer.echo(f"Config: missing - {missing_config_message()}")
        raise typer.Exit(code=1)
    typer.echo(f"Config: {config_path}")
    try:
        config = load_config(config_path)
    except ConfigError as exc:
        typer.echo(f"Config: invalid - {exc}")
        raise typer.Exit(code=1) from exc
    vault_root = config.vault_root_path
    typer.echo(f"Vault root: {vault_root} ({'ok' if vault_root.is_dir() else 'missing'})")
    if not vault_root.is_dir():
        raise typer.Exit(code=1)
    if not os_access_read(vault_root):
        typer.echo("Vault root readable: no")
        raise typer.Exit(code=1)
    typer.echo("Vault root readable: yes")
    index_path = config.index_file_path
    index_path.parent.mkdir(parents=True, exist_ok=True)
    typer.echo(f"Index path: {index_path}")
    typer.echo(f"Index directory writable: {'yes' if os_access_write(index_path.parent) else 'no'}")
    typer.echo(
        f"SQLite FTS5: {'yes' if sqlite_supports_fts5() else 'no - LIKE fallback will be used'}"
    )
    typer.echo(
        f"Ollama: {'available' if ollama_available(config.summarizer.ollama_base_url) else 'not detected'}"
    )
    claude_config = claude_desktop_config_path()
    typer.echo(f"Claude Desktop config path: {claude_config}")
    typer.echo(f"Claude Desktop config exists: {'yes' if claude_config.exists() else 'no'}")


@app.command("index")
def index_command() -> None:
    """Scan the vault and rebuild the SQLite index."""

    config = load_config()
    file_count, chunk_count, fts_enabled = build_index(config)
    typer.echo(
        json.dumps(
            {
                "files": file_count,
                "chunks": chunk_count,
                "index_path": str(config.index_file_path),
                "fts5_enabled": fts_enabled,
            },
            indent=2,
        )
    )


@app.command("search")
def search_command(
    query: Annotated[str, typer.Argument(help="Search query.")],
    top_k: Annotated[int, typer.Option("--top-k", min=1, max=100)] = 10,
    project: Annotated[str | None, typer.Option("--project")] = None,
) -> None:
    """Search indexed vault chunks."""

    config = load_config()
    chunks = search_vault(config, query, top_k=top_k, project=project)
    for chunk in chunks:
        heading = f"#{chunk.heading}" if chunk.heading else ""
        typer.echo(
            f"{chunk.score:.2f}\t{chunk.path}{heading}\tL{chunk.line_start}-{chunk.line_end}"
        )


@app.command("pack")
def pack_command(
    task: Annotated[str, typer.Argument(help="Task to prepare context for.")],
    mode: Annotated[ContextMode, typer.Option("--mode")] = "standard",
    project: Annotated[str | None, typer.Option("--project")] = None,
) -> None:
    """Print a ContextPack as JSON."""

    config = load_config()
    pack = build_context_pack(config, task, mode=mode, project=project)
    typer.echo(pack.model_dump_json(indent=2))


@app.command("serve-mcp")
def serve_mcp_command() -> None:
    """Start the MCP stdio server."""

    run_stdio_server()


@app.command("install-claude")
def install_claude_command(
    python_path: Annotated[str | None, typer.Option("--python-path")] = None,
    config_path: Annotated[str | None, typer.Option("--config-path")] = None,
) -> None:
    """Create or patch Claude Desktop MCP config."""

    final = install_claude_desktop_config(python_path=python_path, config_path=config_path)
    typer.echo(json.dumps(final, indent=2))


@app.command("install-codex")
def install_codex_command(
    python_path: Annotated[str | None, typer.Option("--python-path")] = None,
    config_path: Annotated[str | None, typer.Option("--config-path")] = None,
) -> None:
    """Add this MCP server to Codex user config."""

    final = install_codex_config(python_path=python_path, config_path=config_path)
    typer.echo(json.dumps(final, indent=2))


@app.command("install-claude-code")
def install_claude_code_command(
    python_path: Annotated[str | None, typer.Option("--python-path")] = None,
    config_path: Annotated[str | None, typer.Option("--config-path")] = None,
) -> None:
    """Add this MCP server to Claude Code user config."""

    final = install_claude_code_config(python_path=python_path, config_path=config_path)
    typer.echo(json.dumps(final, indent=2))


@app.command("install-gemini")
def install_gemini_command(
    python_path: Annotated[str | None, typer.Option("--python-path")] = None,
    config_path: Annotated[str | None, typer.Option("--config-path")] = None,
    settings_path: Annotated[str | None, typer.Option("--settings-path")] = None,
) -> None:
    """Add this MCP server to Gemini CLI user settings."""

    final = install_gemini_config(
        python_path=python_path,
        config_path=config_path,
        settings_path=settings_path,
    )
    typer.echo(json.dumps(final, indent=2))


@app.command("install-antigravity")
def install_antigravity_command(
    python_path: Annotated[str | None, typer.Option("--python-path")] = None,
    config_path: Annotated[str | None, typer.Option("--config-path")] = None,
    mcp_config_path: Annotated[str | None, typer.Option("--mcp-config-path")] = None,
) -> None:
    """Add this MCP server to Antigravity user configuration."""

    final = install_antigravity_config(
        python_path=python_path,
        config_path=config_path,
        mcp_config_path=mcp_config_path,
    )
    typer.echo(json.dumps(final, indent=2))


@app.command("install-all-clients")
def install_all_clients_command(
    python_path: Annotated[str | None, typer.Option("--python-path")] = None,
    config_path: Annotated[str | None, typer.Option("--config-path")] = None,
) -> None:
    """Install local stdio MCP config for supported local clients."""

    results = install_all_local_client_configs(python_path=python_path, config_path=config_path)
    typer.echo(json.dumps(results, indent=2))


@app.command("librarian-audit")
def librarian_audit_command(
    refresh_index: Annotated[bool, typer.Option("--refresh-index/--no-refresh-index")] = False,
) -> None:
    """Run the local librarian hygiene audit."""

    config = load_config()
    report = audit_vault(config, refresh_index=refresh_index)
    typer.echo(report.model_dump_json(indent=2))


@app.command("librarian-watch")
def librarian_watch_command(
    once: Annotated[bool, typer.Option("--once")] = False,
) -> None:
    """Watch the vault and refresh the index when Markdown changes."""

    config = load_config()
    watch_vault(config, once=once)


def _provenance_error(exc: ProvenanceError) -> None:
    typer.echo(str(exc), err=True)
    raise typer.Exit(code=1) from exc


@app.command("provenance-scan")
def provenance_scan_command() -> None:
    """Scan configured provenance sources."""

    try:
        counts = provenance_scan(load_config())
    except ProvenanceError as exc:
        _provenance_error(exc)
    typer.echo(" ".join(f"{key}={value}" for key, value in counts.__dict__.items()))


@app.command("provenance-report")
def provenance_report_command(
    paths: Annotated[bool, typer.Option("--paths")] = False,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Show provenance counts, with paths only when explicitly requested."""

    try:
        result = provenance_report(load_config(), resolve_clearance(), show_paths=paths)
    except (ProvenanceError, RuntimeError) as exc:
        _provenance_error(ProvenanceError(str(exc)))
    typer.echo(json.dumps(result, indent=2) if as_json else json.dumps(result, sort_keys=True))


@app.command("provenance-propose")
def provenance_propose_command(
    derivation_id: Annotated[str, typer.Argument()],
    dep: Annotated[list[str], typer.Option("--dep")],
    note: Annotated[str, typer.Option("--note")] = "",
) -> None:
    """Record a derivation proposal and its source dependencies."""

    try:
        provenance_propose(load_config(), derivation_id, dep, note)
    except ProvenanceError as exc:
        _provenance_error(exc)


@app.command("provenance-review")
def provenance_review_command(
    derivation_id: Annotated[str, typer.Argument()],
    accept: Annotated[bool, typer.Option("--accept/--reject")],
) -> None:
    """Accept or reject a proposed derivation."""

    try:
        provenance_review(load_config(), derivation_id, accept)
    except ProvenanceError as exc:
        _provenance_error(exc)


@app.command("provenance-trace")
def provenance_trace_command(subject: Annotated[str, typer.Argument()]) -> None:
    """Print source or derivation transition history."""

    try:
        result = provenance_trace(load_config(), subject)
    except ProvenanceError as exc:
        _provenance_error(exc)
    typer.echo(json.dumps(result, indent=2))


@app.command("install-librarian-agent")
def install_librarian_agent_command(
    python_path: Annotated[str | None, typer.Option("--python-path")] = None,
    config_path: Annotated[str | None, typer.Option("--config-path")] = None,
    load: Annotated[bool, typer.Option("--load/--no-load")] = True,
) -> None:
    """Install the macOS LaunchAgent that runs `librarian-watch`."""

    result = install_librarian_launch_agent(
        python_path=python_path,
        config_path=config_path,
        load=load,
    )
    typer.echo(json.dumps(result, indent=2))


@app.command("install-capture-agent")
def install_capture_agent_command(
    python_path: Annotated[str | None, typer.Option("--python-path")] = None,
    config_path: Annotated[str | None, typer.Option("--config-path")] = None,
    load: Annotated[bool, typer.Option("--load/--no-load")] = True,
) -> None:
    """Install the macOS LaunchAgent for the localhost capture server."""

    result = install_capture_launch_agent(
        python_path=python_path,
        config_path=config_path,
        load=load,
    )
    typer.echo(json.dumps(result, indent=2))


@app.command("uninstall-capture-agent")
def uninstall_capture_agent_command() -> None:
    """Unload and remove the macOS LaunchAgent for the capture server."""

    result = uninstall_capture_launch_agent()
    typer.echo(json.dumps(result, indent=2))


@app.command("remove-obsidian-vault-server")
def remove_obsidian_vault_server_command() -> None:
    """Remove the misconfigured obsidian-vault filesystem MCP server from Claude Desktop."""

    typer.echo(json.dumps(remove_obsidian_vault_from_claude_desktop(), indent=2))


@app.command("log-session")
def log_session_command(
    source: Annotated[str, typer.Option("--source")],
    title: Annotated[str, typer.Option("--title")],
    transcript_file: Annotated[Path | None, typer.Option("--transcript-file")] = None,
    origin: Annotated[str, typer.Option("--origin")] = "manual",
    project: Annotated[str | None, typer.Option("--project")] = None,
    domain: Annotated[str | None, typer.Option("--domain")] = None,
    summary: Annotated[str | None, typer.Option("--summary")] = None,
    no_daily: Annotated[bool, typer.Option("--no-daily")] = False,
) -> None:
    """Log an LLM session from a file or stdin."""

    from vault_context_mcp.schemas import LLMSessionLogRequest

    config = load_config()
    transcript = (
        transcript_file.read_text(encoding="utf-8")
        if transcript_file is not None
        else sys.stdin.read()
    )
    request = LLMSessionLogRequest.model_validate(
        {
            "source": source,
            "title": title,
            "transcript": transcript,
            "origin": origin,
            "project": project,
            "domain": domain,
            "summary": summary,
            "append_daily_note": not no_daily,
        }
    )
    result = log_llm_session(config, request)
    typer.echo(result.model_dump_json(indent=2))


@app.command("recent-sessions")
def recent_sessions_command(
    project: Annotated[str | None, typer.Option("--project")] = None,
    source: Annotated[str | None, typer.Option("--source")] = None,
    limit: Annotated[int, typer.Option("--limit", min=1, max=100)] = 10,
) -> None:
    """List recent cross-client LLM session logs."""

    config = load_config()
    sessions = recent_sessions(
        config, project=project, source=source, limit=limit, clearance=resolve_clearance()
    )
    typer.echo(json.dumps([session.model_dump() for session in sessions], indent=2))


@app.command("process-sessions")
def process_sessions_command() -> None:
    """Summarize unprocessed session captures using the local Ollama model."""

    config = load_config()
    updated = process_unprocessed_sessions(config)
    typer.echo(json.dumps({"updated": updated, "count": len(updated)}, indent=2))


@app.command("session-handoff")
def session_handoff_command(
    project: Annotated[str | None, typer.Option("--project")] = None,
    limit: Annotated[int, typer.Option("--limit", min=1, max=50)] = 8,
) -> None:
    """Build a recent-session handoff for another LLM client."""

    config = load_config()
    handoff = build_session_handoff(
        config, project=project, limit=limit, clearance=resolve_clearance()
    )
    typer.echo(handoff.model_dump_json(indent=2))


@app.command("serve-capture")
def serve_capture_command() -> None:
    """Run the localhost JSON capture endpoint for browser/shortcut capture."""

    config = load_config()
    server = make_capture_server(config)
    typer.echo(
        f"Serving capture endpoint on http://{config.session_log.capture_server_host}:"
        f"{config.session_log.capture_server_port}/capture"
    )
    server.serve_forever()


@app.command("uninstall-librarian-agent")
def uninstall_librarian_agent_command() -> None:
    """Unload and remove the macOS LaunchAgent for the librarian."""

    result = uninstall_librarian_launch_agent()
    typer.echo(json.dumps(result, indent=2))


@app.command("mark-sensitive")
def mark_sensitive_command(
    note_path: Annotated[
        str, typer.Argument(help="Path to the note (absolute or relative to vault root).")
    ],
) -> None:
    """Idempotently mark a single note as sensitive in its frontmatter."""

    config = load_config()
    vault_root = config.vault_root_path

    path = Path(note_path)
    if not path.is_absolute():
        path = path.resolve() if path.exists() else (vault_root / path).resolve()

    try:
        path.relative_to(vault_root)
    except ValueError as exc:
        typer.echo(f"Error: path {path} is outside vault root {vault_root}", err=True)
        raise typer.Exit(code=1) from exc

    if not path.is_file():
        typer.echo(f"Error: {note_path} is not a file", err=True)
        raise typer.Exit(code=1)

    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        typer.echo(f"Error reading file {path}: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    try:
        new_content, modified = mark_content_sensitive(content)
    except ValueError as exc:
        typer.echo(f"Error parsing frontmatter in {path}: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    if modified:
        try:
            path.write_text(new_content, encoding="utf-8")
            typer.echo(f"Successfully marked {path} as sensitive.")
        except OSError as exc:
            typer.echo(f"Error writing file {path}: {exc}", err=True)
            raise typer.Exit(code=1) from exc
    else:
        typer.echo(f"Note {path} is already sensitive (idempotent; no changes made).")


@app.command("backfill-sensitive")
def backfill_sensitive_command(
    scope: Annotated[
        str,
        typer.Option("--scope", help="Path scope to scan (absolute or relative to vault root)."),
    ],
    dry_run: Annotated[
        bool, typer.Option("--dry-run/--no-dry-run", help="Show changes without writing them.")
    ] = True,
    apply: Annotated[
        bool, typer.Option("--apply", help="Apply changes directly to files.")
    ] = False,
) -> None:
    """Idempotently mark all markdown notes under scope as sensitive."""

    # If --apply is specified, dry_run is turned off
    if apply:
        dry_run = False

    config = load_config()
    vault_root = config.vault_root_path

    scope_path = Path(scope)
    if not scope_path.is_absolute():
        scope_path = (
            scope_path.resolve() if scope_path.exists() else (vault_root / scope_path).resolve()
        )

    if not scope_path.exists():
        typer.echo(f"Error: scope path {scope} does not exist", err=True)
        raise typer.Exit(code=1)

    try:
        scope_path.relative_to(vault_root)
    except ValueError as exc:
        typer.echo(f"Error: scope {scope_path} is outside vault root {vault_root}", err=True)
        raise typer.Exit(code=1) from exc

    files_to_process: list[Path] = []
    if scope_path.is_file():
        if scope_path.suffix.lower() == ".md":
            files_to_process.append(scope_path)
    else:
        files_to_process = sorted(scope_path.rglob("*.md"))

    total_files = len(files_to_process)
    modified_files = 0
    errors = 0

    typer.echo(f"Scanning {total_files} markdown files under {scope_path}...")
    if dry_run:
        typer.echo("DRY-RUN MODE: No changes will be written.")

    def check_frontmatter_status(content: str) -> str:
        try:
            fm_dict, _, _ = parse_frontmatter_and_body(content)
            if fm_dict is None:
                return "no frontmatter"
            has_sensitivity = "sensitivity" in fm_dict
            has_tags = "tags" in fm_dict
            if has_sensitivity and has_tags:
                return "has sensitivity and tags"
            elif has_sensitivity:
                return "has sensitivity, missing tags"
            elif has_tags:
                return "has tags, missing sensitivity"
            else:
                return "has frontmatter, missing sensitivity and tags"
        except ValueError:
            return "invalid frontmatter"

    for path in files_to_process:
        try:
            content = path.read_text(encoding="utf-8")
        except OSError as exc:
            typer.echo(f"Error reading {path}: {exc}", err=True)
            errors += 1
            continue

        try:
            new_content, modified = mark_content_sensitive(content)
        except ValueError as exc:
            try:
                rel_path = path.relative_to(vault_root)
            except ValueError:
                rel_path = path
            typer.echo(f"Error parsing frontmatter in {rel_path}: {exc}", err=True)
            errors += 1
            continue

        status = check_frontmatter_status(content)

        if modified:
            modified_files += 1
            try:
                rel_path = path.relative_to(vault_root)
            except ValueError:
                rel_path = path

            if dry_run:
                typer.echo(f"[DRY-RUN] Would mark sensitive: {rel_path} (status: {status})")
            else:
                try:
                    path.write_text(new_content, encoding="utf-8")
                    typer.echo(f"Marked sensitive: {rel_path}")
                except OSError as exc:
                    typer.echo(f"Error writing {path}: {exc}", err=True)
                    errors += 1

    typer.echo("---")
    typer.echo(f"Scan complete. Total files: {total_files}")
    if dry_run:
        typer.echo(f"Would modify {modified_files} files.")
    else:
        typer.echo(f"Successfully modified {modified_files} files.")

    if errors > 0:
        typer.echo(f"Encountered errors on {errors} files.", err=True)
        raise typer.Exit(code=1)


@app.command("propose-sensitive")
def propose_sensitive_command(
    scope: Annotated[
        str,
        typer.Option("--scope", help="Path scope to scan (absolute or relative to vault root)."),
    ],
    limit: Annotated[
        int | None,
        typer.Option(
            "--limit", help="Limit the number of files queried to local Ollama (for testing)."
        ),
    ] = None,
) -> None:
    """Query local Ollama to propose sensitive notes outside the restricted zones."""

    config = load_config()
    vault_root = config.vault_root_path

    if not ollama_available(config.summarizer.ollama_base_url):
        typer.echo(
            f"Error: Local Ollama is not available at {config.summarizer.ollama_base_url}. "
            "Please ensure Ollama is running.",
            err=True,
        )
        raise typer.Exit(code=1)

    scope_path = Path(scope)
    if not scope_path.is_absolute():
        scope_path = (
            scope_path.resolve() if scope_path.exists() else (vault_root / scope_path).resolve()
        )

    if not scope_path.exists():
        typer.echo(f"Error: scope path {scope} does not exist", err=True)
        raise typer.Exit(code=1)

    try:
        scope_path.relative_to(vault_root)
    except ValueError as exc:
        typer.echo(f"Error: scope {scope_path} is outside vault root {vault_root}", err=True)
        raise typer.Exit(code=1) from exc

    files_to_process: list[Path] = []
    if scope_path.is_file():
        if scope_path.suffix.lower() == ".md":
            files_to_process.append(scope_path)
    else:
        files_to_process = sorted(scope_path.rglob("*.md"))

    typer.echo(
        f"Scanning {len(files_to_process)} files under {scope_path} for sensitive candidates..."
    )

    proposed_count = 0
    queried_count = 0

    for path in files_to_process:
        if limit is not None and queried_count >= limit:
            typer.echo(f"Reached limit of {limit} queries. Stopping.")
            break

        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            continue

        try:
            fm_dict, _, _ = parse_frontmatter_and_body(content)
            if fm_dict is not None and fm_dict.get("sensitivity") == "restricted":
                continue
        except ValueError:
            pass

        try:
            rel_path = path.relative_to(vault_root)
        except ValueError:
            rel_path = path

        queried_count += 1
        proposal = query_ollama_proposal(config, path, content)
        if proposal is None:
            continue

        if proposal["is_sensitive"]:
            proposed_count += 1
            typer.echo(f"Candidate: {rel_path}")
            typer.echo(f"Reason: {proposal['reason']}")
            typer.echo(f"Confidence: {proposal['confidence']:.2f}")
            typer.echo("---")

    typer.echo(f"Audit complete. Queried: {queried_count}. Proposed: {proposed_count}.")


def install_claude_desktop_config(
    python_path: str | None = None,
    config_path: str | None = None,
) -> dict[str, object]:
    """Safely patch Claude Desktop config for this MCP server."""

    claude_path = claude_desktop_config_path()
    claude_path.parent.mkdir(parents=True, exist_ok=True)
    existing: dict[str, object]
    if claude_path.exists():
        backup = claude_path.with_suffix(f".json.bak-{timestamp_for_file()}")
        shutil.copy2(claude_path, backup)
        existing = json.loads(claude_path.read_text(encoding="utf-8") or "{}")
    else:
        backup = None
        existing = {}
    servers = existing.get("mcpServers")
    if not isinstance(servers, dict):
        servers = {}
    servers[SERVER_NAME] = mcp_server_entry(
        python_path=python_path,
        config_path=config_path,
        client="claude-desktop",
        clearance="cloud",
    )
    existing["mcpServers"] = servers
    claude_path.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")
    return {
        "config_path": str(claude_path),
        "backup_path": str(backup) if backup else None,
        "server": SERVER_NAME,
        "restart_required": True,
    }


def install_codex_config(
    python_path: str | None = None,
    config_path: str | None = None,
) -> dict[str, object]:
    """Add this server to Codex via `codex mcp add`."""

    resolved_config = resolved_config_path(config_path)
    command = resolved_python_path(python_path)
    codex = shutil.which("codex")
    if codex is None:
        return {"client": "codex", "installed": False, "reason": "codex CLI not found on PATH"}
    result = run_command(
        [
            codex,
            "mcp",
            "add",
            SERVER_NAME,
            "--env",
            f"VAULT_CONTEXT_CONFIG={resolved_config}",
            "--env",
            "VAULT_CONTEXT_CLEARANCE=cloud",
            "--env",
            "VAULT_CONTEXT_CLIENT=codex",
            "--",
            command,
            "-m",
            SERVER_MODULE,
            "serve-mcp",
        ]
    )
    return {
        "client": "codex",
        "installed": result.returncode == 0,
        "command": codex,
        "config_path": str(Path.home() / ".codex/config.toml"),
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
        "restart_required": True,
    }


def install_claude_code_config(
    python_path: str | None = None,
    config_path: str | None = None,
) -> dict[str, object]:
    """Add this server to Claude Code via `claude mcp add-json`."""

    claude = shutil.which("claude")
    if claude is None:
        return {
            "client": "claude-code",
            "installed": False,
            "reason": "claude CLI not found on PATH",
        }
    server_json = json.dumps(
        mcp_server_entry(
            python_path=python_path,
            config_path=config_path,
            client="claude-code",
            clearance="cloud",
        )
    )
    result = run_command([claude, "mcp", "add-json", "--scope", "user", SERVER_NAME, server_json])
    return {
        "client": "claude-code",
        "installed": result.returncode == 0,
        "command": claude,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
        "restart_required": True,
    }


def install_gemini_config(
    python_path: str | None = None,
    config_path: str | None = None,
    settings_path: str | None = None,
) -> dict[str, object]:
    """Patch Gemini CLI `settings.json` with this MCP server."""

    path = (
        Path(settings_path).expanduser().resolve()
        if settings_path
        else Path.home() / ".gemini/settings.json"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    existing: dict[str, object]
    if path.exists():
        backup = path.with_suffix(f".json.bak-{timestamp_for_file()}")
        shutil.copy2(path, backup)
        existing = json.loads(path.read_text(encoding="utf-8") or "{}")
    else:
        backup = None
        existing = {}
    servers = existing.get("mcpServers")
    if not isinstance(servers, dict):
        servers = {}
    entry = mcp_server_entry(
        python_path=python_path,
        config_path=config_path,
        client="gemini-cli",
        clearance="cloud",
    )
    entry["trust"] = True
    entry["timeout"] = 30_000
    servers[SERVER_NAME] = entry
    existing["mcpServers"] = servers
    path.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")
    return {
        "client": "gemini-cli",
        "installed": True,
        "config_path": str(path),
        "backup_path": str(backup) if backup else None,
        "gemini_cli_found": shutil.which("gemini") is not None,
        "restart_required": True,
    }


def install_antigravity_config(
    python_path: str | None = None,
    config_path: str | None = None,
    mcp_config_path: str | None = None,
) -> dict[str, object]:
    """Patch Antigravity `mcp_config.json` with this MCP server."""

    path = (
        Path(mcp_config_path).expanduser().resolve()
        if mcp_config_path
        else Path.home() / ".gemini/antigravity/mcp_config.json"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    existing: dict[str, object]
    if path.exists():
        backup = path.with_suffix(f".json.bak-{timestamp_for_file()}")
        shutil.copy2(path, backup)
        existing = json.loads(path.read_text(encoding="utf-8") or "{}")
    else:
        backup = None
        existing = {}
    servers = existing.get("mcpServers")
    if not isinstance(servers, dict):
        servers = {}
    entry = mcp_server_entry(
        python_path=python_path,
        config_path=config_path,
        client="antigravity",
        clearance="cloud",
    )
    servers[SERVER_NAME] = entry
    existing["mcpServers"] = servers
    path.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")
    return {
        "client": "antigravity",
        "installed": True,
        "config_path": str(path),
        "backup_path": str(backup) if backup else None,
        "restart_required": True,
    }


def install_all_local_client_configs(
    python_path: str | None = None,
    config_path: str | None = None,
) -> dict[str, object]:
    """Install local stdio config for local MCP clients supported by this installer."""

    results: dict[str, object] = {
        "server_entry": mcp_server_entry(
            python_path=python_path,
            config_path=config_path,
            client="unknown",
            clearance="cloud",
        ),
        "claude_desktop": install_claude_desktop_config(
            python_path=python_path, config_path=config_path
        ),
        "codex": install_codex_config(python_path=python_path, config_path=config_path),
        "claude_code": install_claude_code_config(python_path=python_path, config_path=config_path),
        "gemini_cli": install_gemini_config(python_path=python_path, config_path=config_path),
        "antigravity": install_antigravity_config(python_path=python_path, config_path=config_path),
        "chatgpt": {
            "installed": False,
            "reason": (
                "ChatGPT currently supports custom MCP apps/connectors through remote server "
                "URLs, not local stdio servers. See docs/chatgpt_setup.md."
            ),
        },
    }
    return results


def install_librarian_launch_agent(
    python_path: str | None = None,
    config_path: str | None = None,
    load: bool = True,
) -> dict[str, object]:
    """Install a per-user macOS LaunchAgent for the librarian watcher."""

    resolved_config = resolved_config_path(config_path)
    command = resolved_python_path(python_path)
    label = librarian_launch_agent_label()
    plist_path = librarian_launch_agent_path()
    log_dir = Path.home() / ".vault-context-mcp"
    log_dir.mkdir(parents=True, exist_ok=True)
    plist_path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, object] = {
        "Label": label,
        "ProgramArguments": [
            command,
            "-m",
            SERVER_MODULE,
            "librarian-watch",
        ],
        "EnvironmentVariables": {"VAULT_CONTEXT_CONFIG": str(resolved_config)},
        "RunAtLoad": True,
        "KeepAlive": True,
        "StandardOutPath": str(log_dir / "librarian.log"),
        "StandardErrorPath": str(log_dir / "librarian.err.log"),
        "WorkingDirectory": str(Path.cwd()),
    }
    if plist_path.exists():
        backup = plist_path.with_suffix(f".plist.bak-{timestamp_for_file()}")
        shutil.copy2(plist_path, backup)
    else:
        backup = None
    plist_path.write_bytes(plistlib.dumps(payload))
    load_result = None
    kickstart_result = None
    if load:
        domain = f"gui/{os.getuid()}"
        run_command(["launchctl", "bootout", domain, str(plist_path)], timeout_seconds=10)
        load_result = run_command(
            ["launchctl", "bootstrap", domain, str(plist_path)],
            timeout_seconds=10,
        )
        kickstart_result = run_command(
            ["launchctl", "kickstart", "-k", f"{domain}/{label}"],
            timeout_seconds=10,
        )
    return {
        "label": label,
        "plist_path": str(plist_path),
        "backup_path": str(backup) if backup else None,
        "loaded": load_result.returncode == 0 if load_result else False,
        "load_stdout": load_result.stdout.strip() if load_result else "",
        "load_stderr": load_result.stderr.strip() if load_result else "",
        "kickstart_stdout": kickstart_result.stdout.strip() if kickstart_result else "",
        "kickstart_stderr": kickstart_result.stderr.strip() if kickstart_result else "",
        "log_path": str(log_dir / "librarian.log"),
        "error_log_path": str(log_dir / "librarian.err.log"),
    }


def install_capture_launch_agent(
    python_path: str | None = None,
    config_path: str | None = None,
    load: bool = True,
) -> dict[str, object]:
    """Install a per-user macOS LaunchAgent for the localhost capture server."""

    return install_launch_agent(
        label=capture_launch_agent_label(),
        plist_path=capture_launch_agent_path(),
        program_args=[
            resolved_python_path(python_path),
            "-m",
            SERVER_MODULE,
            "serve-capture",
        ],
        config_path=config_path,
        load=load,
        stdout_name="capture.log",
        stderr_name="capture.err.log",
    )


def install_launch_agent(
    label: str,
    plist_path: Path,
    program_args: list[str],
    config_path: str | None,
    load: bool,
    stdout_name: str,
    stderr_name: str,
) -> dict[str, object]:
    """Install and optionally load a per-user macOS LaunchAgent."""

    resolved_config = resolved_config_path(config_path)
    log_dir = Path.home() / ".vault-context-mcp"
    log_dir.mkdir(parents=True, exist_ok=True)
    plist_path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, object] = {
        "Label": label,
        "ProgramArguments": program_args,
        "EnvironmentVariables": {"VAULT_CONTEXT_CONFIG": str(resolved_config)},
        "RunAtLoad": True,
        "KeepAlive": True,
        "StandardOutPath": str(log_dir / stdout_name),
        "StandardErrorPath": str(log_dir / stderr_name),
        "WorkingDirectory": str(Path.cwd()),
    }
    if plist_path.exists():
        backup = plist_path.with_suffix(f".plist.bak-{timestamp_for_file()}")
        shutil.copy2(plist_path, backup)
    else:
        backup = None
    plist_path.write_bytes(plistlib.dumps(payload))
    load_result = None
    kickstart_result = None
    if load:
        domain = f"gui/{os.getuid()}"
        run_command(["launchctl", "bootout", domain, str(plist_path)], timeout_seconds=10)
        load_result = run_command(
            ["launchctl", "bootstrap", domain, str(plist_path)],
            timeout_seconds=10,
        )
        kickstart_result = run_command(
            ["launchctl", "kickstart", "-k", f"{domain}/{label}"],
            timeout_seconds=10,
        )
    return {
        "label": label,
        "plist_path": str(plist_path),
        "backup_path": str(backup) if backup else None,
        "loaded": load_result.returncode == 0 if load_result else False,
        "load_stdout": load_result.stdout.strip() if load_result else "",
        "load_stderr": load_result.stderr.strip() if load_result else "",
        "kickstart_stdout": kickstart_result.stdout.strip() if kickstart_result else "",
        "kickstart_stderr": kickstart_result.stderr.strip() if kickstart_result else "",
        "log_path": str(log_dir / stdout_name),
        "error_log_path": str(log_dir / stderr_name),
    }


def make_capture_server(config: object) -> ThreadingHTTPServer:
    """Create the local HTTP capture server."""

    from vault_context_mcp.config import VaultConfig

    if not isinstance(config, VaultConfig):
        raise TypeError("config must be VaultConfig")
    runtime_config: VaultConfig = config

    class CaptureHandler(BaseHTTPRequestHandler):
        def do_OPTIONS(self) -> None:
            self.send_response(204)
            self._send_cors_headers()
            self.end_headers()

        def do_GET(self) -> None:
            if self.path == "/health":
                self._send_json({"ok": True})
                return
            self._send_json({"error": "not found"}, status=404)

        def do_POST(self) -> None:
            if self.path != "/capture":
                self._send_json({"error": "not found"}, status=404)
                return
            length = int(self.headers.get("Content-Length", "0"))
            payload = self.rfile.read(length)
            try:
                request = request_from_json_payload(payload)
                result = log_llm_session(runtime_config, request)
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=400)
                return
            self._send_json(result.model_dump())

        def log_message(self, format: str, *args: object) -> None:
            return

        def _send_json(self, data: object, status: int = 200) -> None:
            body = json.dumps(data, indent=2).encode("utf-8")
            self.send_response(status)
            self._send_cors_headers()
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_cors_headers(self) -> None:
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")

    return ThreadingHTTPServer(
        (
            runtime_config.session_log.capture_server_host,
            runtime_config.session_log.capture_server_port,
        ),
        CaptureHandler,
    )


def uninstall_librarian_launch_agent() -> dict[str, object]:
    """Unload and remove the librarian LaunchAgent."""

    label = librarian_launch_agent_label()
    plist_path = librarian_launch_agent_path()
    domain = f"gui/{os.getuid()}"
    unload_result = run_command(
        ["launchctl", "bootout", domain, str(plist_path)], timeout_seconds=10
    )
    removed = False
    if plist_path.exists():
        plist_path.unlink()
        removed = True
    return {
        "label": label,
        "plist_path": str(plist_path),
        "unloaded": unload_result.returncode == 0,
        "stderr": unload_result.stderr.strip(),
        "removed": removed,
    }


def uninstall_capture_launch_agent() -> dict[str, object]:
    """Unload and remove the capture server LaunchAgent."""

    return uninstall_launch_agent(capture_launch_agent_label(), capture_launch_agent_path())


def uninstall_launch_agent(label: str, plist_path: Path) -> dict[str, object]:
    """Unload and remove a LaunchAgent."""

    domain = f"gui/{os.getuid()}"
    unload_result = run_command(
        ["launchctl", "bootout", domain, str(plist_path)], timeout_seconds=10
    )
    removed = False
    if plist_path.exists():
        plist_path.unlink()
        removed = True
    return {
        "label": label,
        "plist_path": str(plist_path),
        "unloaded": unload_result.returncode == 0,
        "stderr": unload_result.stderr.strip(),
        "removed": removed,
    }


def librarian_launch_agent_label() -> str:
    """Return the macOS LaunchAgent label."""

    return "com.example.vault-context-mcp.librarian"


def librarian_launch_agent_path() -> Path:
    """Return the macOS LaunchAgent plist path."""

    return Path.home() / "Library/LaunchAgents/com.example.vault-context-mcp.librarian.plist"


def capture_launch_agent_label() -> str:
    """Return the macOS capture server LaunchAgent label."""

    return "com.example.vault-context-mcp.capture"


def capture_launch_agent_path() -> Path:
    """Return the macOS capture server LaunchAgent plist path."""

    return Path.home() / "Library/LaunchAgents/com.example.vault-context-mcp.capture.plist"


def mcp_server_entry(
    python_path: str | None = None,
    config_path: str | None = None,
    client: str = "unknown",
    clearance: str = "cloud",
) -> dict[str, object]:
    """Return a portable stdio MCP server entry."""

    return {
        "type": "stdio",
        "command": resolved_python_path(python_path),
        "args": ["-m", SERVER_MODULE, "serve-mcp"],
        "env": {
            "VAULT_CONTEXT_CONFIG": str(resolved_config_path(config_path)),
            "VAULT_CONTEXT_CLEARANCE": clearance,
            "VAULT_CONTEXT_CLIENT": client,
        },
    }


def remove_mcp_server_from_json_config(config_path: Path, server_name: str) -> dict[str, object]:
    """Remove one entry from a JSON client config's mcpServers block, if present.

    Args:
        config_path: Path to a client's JSON MCP config file.
        server_name: The mcpServers key to remove, e.g. "obsidian-vault".

    Returns:
        Result dict with config_path, removed (bool), and backup_path when a
        removal happened.
    """

    if not config_path.exists():
        return {
            "config_path": str(config_path),
            "removed": False,
            "reason": "config file does not exist",
        }
    existing = json.loads(config_path.read_text(encoding="utf-8") or "{}")
    servers = existing.get("mcpServers")
    if not isinstance(servers, dict) or server_name not in servers:
        return {
            "config_path": str(config_path),
            "removed": False,
            "reason": f"'{server_name}' not present",
        }
    backup = config_path.with_suffix(f".json.bak-{timestamp_for_file()}")
    shutil.copy2(config_path, backup)
    del servers[server_name]
    existing["mcpServers"] = servers
    config_path.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")
    return {
        "config_path": str(config_path),
        "backup_path": str(backup),
        "removed": True,
        "server": server_name,
    }


def remove_obsidian_vault_from_claude_desktop() -> dict[str, object]:
    """Remove the misconfigured 'obsidian-vault' filesystem MCP server (ADR 0036 D4).

    That server grants raw, unfiltered filesystem read/write to the vault
    (including ACME/**) with no sensitivity boundary — it must not remain in
    any client config once vault-context-mcp is the single access engine.
    """

    return remove_mcp_server_from_json_config(claude_desktop_config_path(), "obsidian-vault")


def resolved_config_path(config_path: str | None = None) -> Path:
    """Resolve the config path or raise a clear config error."""

    resolved_config = (
        Path(config_path).expanduser().resolve() if config_path else default_config_path()
    )
    if resolved_config is None:
        raise ConfigError(missing_config_message())
    return resolved_config


def resolved_python_path(python_path: str | None = None) -> str:
    """Return the Python executable used to launch the MCP server."""

    return str(Path(python_path).expanduser().resolve()) if python_path else sys.executable


def run_command(args: list[str], timeout_seconds: int = 30) -> subprocess.CompletedProcess[str]:
    """Run a bounded client configuration command."""

    try:
        return subprocess.run(
            args,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = (
            exc.stdout.decode("utf-8", errors="replace")
            if isinstance(exc.stdout, bytes)
            else exc.stdout
        )
        return subprocess.CompletedProcess(
            args=args,
            returncode=124,
            stdout=stdout or "",
            stderr=f"Timed out after {timeout_seconds} seconds",
        )


def claude_desktop_config_path() -> Path:
    """Return the macOS Claude Desktop config path."""

    return Path.home() / "Library/Application Support/Claude/claude_desktop_config.json"


def timestamp_for_file() -> str:
    """Return timestamp suitable for backup filenames."""

    from datetime import datetime

    return datetime.now().strftime("%Y%m%d%H%M%S")


def os_access_read(path: Path) -> bool:
    """Return whether a path is readable."""

    return path.exists() and path.is_dir() and os_access(path, "read")


def os_access_write(path: Path) -> bool:
    """Return whether a path is writable."""

    return path.exists() and path.is_dir() and os_access(path, "write")


def os_access(path: Path, mode: str) -> bool:
    """Small wrapper around pathlib access checks."""

    import os

    flag = os.R_OK if mode == "read" else os.W_OK
    return bool(os.access(path, flag))


def ollama_available(base_url: str) -> bool:
    """Return whether local Ollama responds."""

    try:
        with urllib.request.urlopen(f"{base_url.rstrip('/')}/api/tags", timeout=2) as response:
            return bool(getattr(response, "status", 0) == 200)
    except (OSError, TimeoutError, urllib.error.URLError):
        return False


def main() -> None:
    """Run the Typer app."""

    app()


if __name__ == "__main__":
    main()
