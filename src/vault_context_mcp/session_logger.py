"""Cross-LLM session capture and handoff."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from vault_context_mcp.config import VaultConfig
from vault_context_mcp.index_store import build_index
from vault_context_mcp.markdown_scanner import scan_vault
from vault_context_mcp.schemas import (
    LLMSessionLogRequest,
    LLMSessionLogResult,
    LLMSessionSummary,
    SessionHandoff,
)
from vault_context_mcp.security import resolve_and_validate_path
from vault_context_mcp.sensitivity import (
    Clearance,
    load_sensitivity_map,
    note_sensitivity,
)
from vault_context_mcp.utils import truncate_words, utc_now_iso

LOCAL_TZ = ZoneInfo("Asia/Kolkata")
SESSION_TAG = "llm-session"


class SessionLogError(RuntimeError):
    """Raised when a session cannot be logged safely."""


def log_llm_session(config: VaultConfig, request: LLMSessionLogRequest) -> LLMSessionLogResult:
    """Persist an LLM session into the configured vault.

    Args:
        config: Runtime configuration.
        request: Session capture request.

    Returns:
        Write result with vault-relative path.
    """

    if not config.session_log.enabled:
        raise SessionLogError("session_log.enabled is false")
    if not request.transcript.strip():
        raise SessionLogError("transcript must not be empty")
    if len(request.transcript) > config.session_log.max_transcript_chars:
        raise SessionLogError(
            f"transcript is too large; max is {config.session_log.max_transcript_chars} chars"
        )

    target_dir = _source_dir(config, request.source)
    target_dir.mkdir(parents=True, exist_ok=True)
    captured = datetime.now(LOCAL_TZ)
    slug = slugify(request.title)
    path = unique_session_path(target_dir, f"{captured:%Y-%m-%d}-{slug}.md")
    markdown = format_session_markdown(request, captured)
    path.write_text(markdown, encoding="utf-8")
    enriched_request = _try_summarize_and_update(config, path, request, captured) or request
    daily_note_path = append_daily_note(config, enriched_request, path, captured)
    index_refreshed = False
    if config.session_log.refresh_index_after_write:
        build_index(config)
        index_refreshed = True
    return LLMSessionLogResult(
        path=path.relative_to(config.vault_root_path).as_posix(),
        absolute_path=str(path),
        source=request.source,
        project=request.project,
        daily_note_path=(
            daily_note_path.relative_to(config.vault_root_path).as_posix()
            if daily_note_path is not None
            else None
        ),
        index_refreshed=index_refreshed,
        message="LLM session logged to vault",
    )


def format_session_markdown(
    request: LLMSessionLogRequest, captured: datetime, processed: bool = False
) -> str:
    """Format a session capture as Markdown."""

    state_tag = "processed" if processed else "unprocessed"
    tags = [state_tag, SESSION_TAG, f"source/{request.source}", *request.tags]
    if request.project:
        tags.append(f"project/{slugify(request.project)}")
    frontmatter = {
        "captured": captured.isoformat(),
        "source": request.source,
        "origin": request.origin,
        "type": "llm-session-log",
        "tier": "working",
        "project": request.project,
        "domain": request.domain,
        "tags": sorted(dict.fromkeys(tag for tag in tags if tag)),
        "why": request.summary or "",
    }
    lines = [
        "---",
        yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=False).strip(),
        "---",
        "",
        f"# {request.title.strip()}",
        "",
        f"- **Source:** `{request.source}`",
        f"- **Origin:** {request.origin}",
        f"- **Captured:** {captured.isoformat()}",
        f"- **Project:** {request.project or ''}",
        "",
    ]
    if request.summary:
        lines.extend(["## Summary", "", request.summary.strip(), ""])
    lines.extend(_list_section("Key Takeaways", request.key_takeaways))
    lines.extend(_list_section("Decisions", request.decisions))
    lines.extend(_list_section("Open Questions", request.open_questions))
    lines.extend(_list_section("Next Actions", request.next_actions))
    lines.extend(["## Transcript", "", normalize_transcript(request.transcript), ""])
    return "\n".join(lines).rstrip() + "\n"


def append_daily_note(
    config: VaultConfig,
    request: LLMSessionLogRequest,
    session_path: Path,
    captured: datetime,
) -> Path | None:
    """Append a one-line LLM session entry to today's daily note when configured."""

    if not request.append_daily_note or not config.session_log.append_daily_note:
        return None
    daily_dir = resolve_and_validate_path(
        config.session_log.daily_notes_path, config.vault_root_path
    )
    daily_dir.mkdir(parents=True, exist_ok=True)
    daily_path = daily_dir / f"{captured:%Y-%m-%d}.md"
    if not daily_path.exists():
        if not config.session_log.create_daily_note:
            return None
        daily_path.write_text(f"# {captured:%Y-%m-%d}\n\n## LLM Sessions\n", encoding="utf-8")
    text = daily_path.read_text(encoding="utf-8")
    if "## LLM Sessions" not in text:
        text = text.rstrip() + "\n\n## LLM Sessions\n"
    rel_session = session_path.relative_to(config.vault_root_path).with_suffix("").as_posix()
    summary = request.summary or truncate_words(request.transcript.replace("\n", " "), 24)
    entry = (
        f"- **{request.title.strip()}:** What changed: {summary} | "
        f"Source: `{request.source}` | Landed? [[{rel_session}]] | "
        f"Next: {request.next_actions[0] if request.next_actions else ''}"
    )
    if entry not in text:
        text = text.rstrip() + "\n" + entry + "\n"
        daily_path.write_text(text, encoding="utf-8")
    return daily_path


def recent_sessions(
    config: VaultConfig,
    project: str | None = None,
    source: str | None = None,
    limit: int = 10,
    clearance: Clearance = "cloud",
) -> list[LLMSessionSummary]:
    """Return recent logged LLM sessions visible at ``clearance``.

    Restricted notes (path rule or ``sensitivity: restricted`` frontmatter)
    are skipped unless ``clearance`` is "local"; the default is least privilege.
    """

    rules = load_sensitivity_map(config.sensitivity_map_file_path)
    paths = sorted(
        _session_candidate_paths(config), key=lambda item: item.stat().st_mtime, reverse=True
    )
    summaries: list[LLMSessionSummary] = []
    for path in paths:
        summary = parse_session_summary(config, path)
        if summary is None:
            continue
        if project and (summary.project or "").lower() != project.lower():
            continue
        if source and summary.source.lower() != source.lower():
            continue
        if clearance != "local" and (
            note_sensitivity(config.vault_root_path, summary.path, rules) == "restricted"
        ):
            continue
        summaries.append(summary)
        if len(summaries) >= limit:
            break
    return summaries


def build_session_handoff(
    config: VaultConfig,
    project: str | None = None,
    limit: int = 8,
    clearance: Clearance = "cloud",
) -> SessionHandoff:
    """Build a compact handoff from recent LLM sessions visible at ``clearance``."""

    sessions = recent_sessions(config, project=project, limit=limit, clearance=clearance)
    lines: list[str] = []
    next_actions: list[str] = []
    for session in sessions:
        if session.summary:
            lines.append(f"- {session.title} ({session.source}): {session.summary}")
        for action in session.next_actions:
            if action not in next_actions:
                next_actions.append(action)
    if not lines:
        lines.append("- No recent LLM session logs found.")
    return SessionHandoff(
        generated_at=utc_now_iso(),
        project=project,
        sessions=sessions,
        synthesized_handoff="\n".join(lines),
        suggested_next_actions=next_actions[:8],
    )


def parse_session_summary(config: VaultConfig, path: Path) -> LLMSessionSummary | None:
    """Parse a session note into compact metadata."""

    safe_path = resolve_and_validate_path(path, config.vault_root_path)
    text = safe_path.read_text(encoding="utf-8")
    if not _looks_like_session_note(config, safe_path, text):
        return None
    frontmatter = _frontmatter(text)
    title_match = re.search(r"^#\s+(.+)$", text, flags=re.MULTILINE)
    title = title_match.group(1).strip() if title_match else safe_path.stem
    summary = (
        _section_text(text, "Summary")
        or _section_text(text, "TL;DR — What happened today")
        or _section_text(text, "Context")
    )
    next_actions = (
        _section_bullets(text, "Next Actions")
        or _section_bullets(text, "Next Session Agenda")
        or _numbered_section_items(text, "Pickup cues for next session")
    )
    project = _project_from_frontmatter_or_path(frontmatter, safe_path, config)
    source = str(
        frontmatter.get("source") or _source_from_frontmatter_or_text(frontmatter, text, safe_path)
    )
    return LLMSessionSummary(
        path=safe_path.relative_to(config.vault_root_path).as_posix(),
        source=source,
        title=title,
        captured=str(frontmatter.get("captured")) if frontmatter.get("captured") else None,
        project=project,
        summary=summary,
        next_actions=next_actions,
    )


def process_unprocessed_sessions(config: VaultConfig) -> list[str]:
    """Summarize any session notes still tagged 'unprocessed'.

    Args:
        config: Runtime configuration.

    Returns:
        Vault-relative paths of sessions that were updated.
    """

    updated: list[str] = []
    for path in _session_candidate_paths(config):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if "unprocessed" not in text[:1200]:
            continue
        summary = parse_session_summary(config, path)
        if summary is None:
            continue
        transcript = _section_text(text, "Transcript") or ""
        if not transcript.strip():
            continue
        from vault_context_mcp.summarizer import Summarizer  # avoid circular at module level

        extracted = Summarizer(config.summarizer).summarize_session_transcript(
            transcript, summary.title, summary.project
        )
        if not extracted:
            continue
        _patch_session_file(path, extracted)
        updated.append(path.relative_to(config.vault_root_path).as_posix())
    if updated:
        build_index(config)
    return updated


def _try_summarize_and_update(
    config: VaultConfig,
    path: Path,
    request: LLMSessionLogRequest,
    captured: datetime,
) -> LLMSessionLogRequest | None:
    """After capture, attempt Ollama extraction and rewrite the file as processed.

    Returns:
        Enriched request with extracted fields merged in, or None if extraction
        was skipped or unavailable. The returned request is suitable for the
        daily-note appendage so the summary line reflects the model's output.
    """

    if not config.session_log.summarize_on_capture:
        return None
    if request.summary and request.key_takeaways:
        _mark_processed(path)
        return None
    from vault_context_mcp.summarizer import Summarizer

    extracted = Summarizer(config.summarizer).summarize_session_transcript(
        request.transcript, request.title, request.project
    )
    if not extracted:
        return None
    updated = request.model_copy(
        update={
            "summary": extracted.get("summary") or request.summary,
            "key_takeaways": extracted.get("key_takeaways") or request.key_takeaways,
            "decisions": extracted.get("decisions") or request.decisions,
            "open_questions": extracted.get("open_questions") or request.open_questions,
            "next_actions": extracted.get("next_actions") or request.next_actions,
        }
    )
    path.write_text(format_session_markdown(updated, captured, processed=True), encoding="utf-8")
    return updated


def _mark_processed(path: Path) -> None:
    """Replace the 'unprocessed' state tag with 'processed' in a session file."""

    text = path.read_text(encoding="utf-8")
    if "unprocessed" not in text[:1200]:
        return
    path.write_text(text.replace("- unprocessed\n", "- processed\n", 1), encoding="utf-8")


def _patch_session_file(path: Path, extracted: dict[str, object]) -> None:
    """Inject extracted summary fields into an existing session file."""

    text = path.read_text(encoding="utf-8")
    summary = str(extracted.get("summary") or "").strip()
    key_takeaways: list[str] = extracted.get("key_takeaways") or []  # type: ignore[assignment]
    decisions: list[str] = extracted.get("decisions") or []  # type: ignore[assignment]
    open_questions: list[str] = extracted.get("open_questions") or []  # type: ignore[assignment]
    next_actions: list[str] = extracted.get("next_actions") or []  # type: ignore[assignment]

    insertion = ""
    if summary and "## Summary" not in text:
        insertion += f"## Summary\n\n{summary}\n\n"
    for heading, items in (
        ("Key Takeaways", key_takeaways),
        ("Decisions", decisions),
        ("Open Questions", open_questions),
        ("Next Actions", next_actions),
    ):
        if items and f"## {heading}" not in text:
            insertion += f"## {heading}\n\n" + "\n".join(f"- {i}" for i in items) + "\n\n"

    if insertion:
        text = text.replace("\n## Transcript\n", f"\n{insertion}## Transcript\n", 1)
    text = text.replace("- unprocessed\n", "- processed\n", 1)
    path.write_text(text, encoding="utf-8")


def unique_session_path(directory: Path, filename: str) -> Path:
    """Return a unique path without overwriting existing session logs."""

    candidate = directory / filename
    if not candidate.exists():
        return candidate
    stem = candidate.stem
    suffix = candidate.suffix
    for index in range(2, 10_000):
        next_candidate = directory / f"{stem}-{index}{suffix}"
        if not next_candidate.exists():
            return next_candidate
    raise SessionLogError(f"Could not allocate unique session path in {directory}")


def slugify(value: str) -> str:
    """Return a filesystem-safe slug."""

    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return slug[:80] or "llm-session"


def normalize_transcript(transcript: str) -> str:
    """Normalize transcript line endings and ensure final newline stability."""

    return transcript.replace("\r\n", "\n").replace("\r", "\n").strip()


def _source_dir(config: VaultConfig, source: str) -> Path:
    relative = config.session_log.source_paths.get(source, f"{config.session_log.base_path}/Other")
    path = resolve_and_validate_path(relative, config.vault_root_path)
    base = resolve_and_validate_path(config.session_log.base_path, config.vault_root_path)
    try:
        path.relative_to(base)
    except ValueError as exc:
        raise SessionLogError(f"Session log path escapes configured base path: {relative}") from exc
    return path


def _list_section(title: str, items: list[str]) -> list[str]:
    if not items:
        return []
    lines = [f"## {title}", ""]
    lines.extend(f"- {item.strip()}" for item in items if item.strip())
    lines.append("")
    return lines


def _frontmatter(text: str) -> dict[str, object]:
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---", 4)
    if end == -1:
        return {}
    parsed = yaml.safe_load(text[4:end]) or {}
    return parsed if isinstance(parsed, dict) else {}


def _section_text(text: str, heading: str) -> str | None:
    pattern = rf"^##\s+{re.escape(heading)}\s*\n(?P<body>.*?)(?=^##\s+|\Z)"
    match = re.search(pattern, text, flags=re.MULTILINE | re.DOTALL)
    if not match:
        return None
    body = match.group("body").strip()
    body = re.sub(r"\n---\s*$", "", body).strip()
    return body or None


def _section_bullets(text: str, heading: str) -> list[str]:
    body = _section_text(text, heading)
    if not body:
        return []
    return [line[2:].strip() for line in body.splitlines() if line.startswith("- ")]


def _numbered_section_items(text: str, heading: str) -> list[str]:
    body = _section_text(text, heading)
    if not body:
        return []
    return [
        re.sub(r"^\d+\.\s+", "", line).strip()
        for line in body.splitlines()
        if re.match(r"^\d+\.\s+", line)
    ]


def _session_candidate_paths(config: VaultConfig) -> list[Path]:
    paths: dict[Path, None] = {}
    base = resolve_and_validate_path(config.session_log.base_path, config.vault_root_path)
    if base.exists():
        for path in base.rglob("*.md"):
            paths[path] = None
    for scanned_file in scan_vault(config):
        path = config.vault_root_path / scanned_file.path
        lower_parts = {part.lower() for part in path.parts}
        if "01-sessions" in lower_parts or "08-sessions" in lower_parts:
            paths[path] = None
    return list(paths)


def _looks_like_session_note(config: VaultConfig, path: Path, text: str) -> bool:
    relative = path.relative_to(config.vault_root_path).as_posix().lower()
    front = text[:1200].lower()
    return (
        SESSION_TAG in front
        or "type: llm-session-log" in front
        or "type: session" in front
        or "/01-sessions/" in f"/{relative}"
        or "/08-sessions/" in f"/{relative}"
    )


def _project_from_frontmatter_or_path(
    frontmatter: dict[str, object],
    path: Path,
    config: VaultConfig,
) -> str | None:
    project = frontmatter.get("project")
    if isinstance(project, str) and project.strip():
        return project.strip()
    tags = frontmatter.get("tags")
    if isinstance(tags, list):
        for tag in tags:
            if isinstance(tag, str) and tag.startswith("project/"):
                return tag.split("/", 1)[1]
    parts = path.relative_to(config.vault_root_path).parts
    for index, part in enumerate(parts[:-1]):
        if part in {"20-Projects", "04-Projects"} and index + 1 < len(parts):
            return parts[index + 1]
    if len(parts) >= 2 and parts[1] == "08-Sessions":
        return parts[0]
    return None


def _source_from_frontmatter_or_text(frontmatter: dict[str, object], text: str, path: Path) -> str:
    tags = frontmatter.get("tags")
    if isinstance(tags, list) and any(str(tag).lower() == "system/claude" for tag in tags):
        return "claude"
    lower = text[:2000].lower()
    if (
        "author: claude" in lower
        or "model used:** claude" in lower
        or "logged via obsidian mcp" in lower
    ):
        return "claude"
    if "chatgpt" in lower:
        return "chatgpt"
    if "gemini" in lower:
        return "gemini"
    if "codex" in lower:
        return "codex"
    if "01-sessions" in {part.lower() for part in path.parts}:
        return "claude"
    return "unknown"


def request_from_json_payload(payload: bytes) -> LLMSessionLogRequest:
    """Parse JSON request bytes from the local capture server."""

    raw = json.loads(payload.decode("utf-8"))
    return LLMSessionLogRequest.model_validate(raw)
