"""Build structured context packs from retrieved vault chunks."""

from __future__ import annotations

from pathlib import Path

from vault_context_mcp.config import VaultConfig
from vault_context_mcp.index_store import IndexStore
from vault_context_mcp.retriever import retrieve_chunks
from vault_context_mcp.schemas import Clearance, ContextMode, ContextPack, RetrievedChunk, SourceRef
from vault_context_mcp.sensitivity import resolve_clearance
from vault_context_mcp.summarizer import Summarizer
from vault_context_mcp.utils import truncate_words, utc_now_iso


class ContextBuildError(RuntimeError):
    """Raised when a context pack cannot be built."""


def build_context_pack(
    config: VaultConfig,
    task: str,
    mode: ContextMode = "standard",
    project: str | None = None,
    clearance: Clearance = "cloud",
) -> ContextPack:
    """Build a structured context pack.

    Args:
        config: Runtime configuration.
        task: User task.
        mode: Context depth mode.
        project: Optional project hint.
        clearance: Caller clearance for sensitivity filtering.

    Returns:
        ContextPack ready for JSON serialization.
    """

    cleaned_task = task.strip()
    if not cleaned_task:
        raise ContextBuildError("task must not be empty")
    chunks = retrieve_chunks(config, cleaned_task, mode, project, clearance=clearance)
    max_tokens = config.retrieval.max_output_tokens[mode]
    summary = Summarizer(config.summarizer).summarize(cleaned_task, chunks, max_tokens // 3)
    sections = _sections_from_chunks(chunks, max_tokens=max_tokens)
    sources = [_source_ref(chunk, _source_reason(chunk)) for chunk in chunks]
    confidence = _confidence(chunks, project)
    return ContextPack(
        task=cleaned_task,
        mode=mode,
        project=project,
        generated_at=utc_now_iso(),
        context_summary=summary,
        relevant_sources=sources,
        current_state=sections["current_state"],
        prior_decisions=sections["prior_decisions"],
        constraints=sections["constraints"],
        open_questions=sections["open_questions"],
        key_facts=sections["key_facts"],
        missing_context=_missing_context(chunks, sections, project),
        suggested_next_files=sources[: min(5, len(sources))],
        confidence=confidence,
    )


def tool_get_context_pack(
    task: str,
    mode: ContextMode = "standard",
    project: str | None = None,
    config: VaultConfig | None = None,
    clearance: Clearance | None = None,
) -> dict[str, object]:
    """Build a context pack and return JSON-serializable data."""

    from vault_context_mcp.config import load_config

    runtime_config = config or load_config()
    resolved = clearance if clearance is not None else resolve_clearance()
    pack = build_context_pack(runtime_config, task, mode, project, clearance=resolved)
    if runtime_config.security.log_tool_calls:
        IndexStore(runtime_config.index_file_path).log_tool_call(
            "get_context_pack", {"task": task, "mode": mode, "project": project}
        )
    return pack.model_dump()


def _sections_from_chunks(
    chunks: list[RetrievedChunk],
    max_tokens: int,
) -> dict[str, list[str]]:
    max_words = max(int(max_tokens * 0.75), 100)
    per_section = max(max_words // 7, 30)
    sections: dict[str, list[str]] = {
        "current_state": [],
        "prior_decisions": [],
        "constraints": [],
        "open_questions": [],
        "key_facts": [],
    }
    for chunk in chunks:
        category = _chunk_category(chunk)
        lines = _high_signal_lines(chunk)
        if not lines:
            lines = [truncate_words(chunk.text.strip(), 45)]
        for line in lines[:4]:
            if line and line not in sections[category]:
                sections[category].append(line)
    return {key: _limit_items(items, per_section) for key, items in sections.items()}


def _chunk_category(chunk: RetrievedChunk) -> str:
    path = chunk.path.lower()
    text = chunk.text.lower()
    if "open_questions" in path or "open question" in text or "unresolved" in text:
        return "open_questions"
    if "decision" in path or "decided" in text:
        return "prior_decisions"
    if "constraint" in text or "must" in text or "rule" in text or "agents.md" in path:
        return "constraints"
    if "current_state" in path or "project_state" in path or "active_projects" in path:
        return "current_state"
    return "key_facts"


def _high_signal_lines(chunk: RetrievedChunk) -> list[str]:
    lines: list[str] = []
    for line in chunk.text.splitlines():
        clean = line.strip()
        if not clean or clean == "---":
            continue
        lower = clean.lower()
        if clean.startswith("#"):
            continue
        if (
            clean.startswith(("-", "*"))
            or "decision" in lower
            or "decided" in lower
            or "current" in lower
            or "must" in lower
            or "next" in lower
            or "question" in lower
            or "constraint" in lower
            or "todo" in lower
        ):
            lines.append(clean)
    return lines


def _limit_items(items: list[str], max_words: int) -> list[str]:
    output: list[str] = []
    used = 0
    for item in items:
        words = len(item.split())
        if output and used + words > max_words:
            break
        output.append(truncate_words(item, 60))
        used += words
    return output[:12]


def _source_ref(chunk: RetrievedChunk, reason: str) -> SourceRef:
    return SourceRef(
        path=chunk.path,
        heading=chunk.heading,
        line_start=chunk.line_start,
        line_end=chunk.line_end,
        reason=reason,
        score=chunk.score,
    )


def _source_reason(chunk: RetrievedChunk) -> str:
    file_name = Path(chunk.path).name
    if chunk.metadata.get("is_canonical"):
        return f"canonical context file: {file_name}"
    if chunk.metadata.get("is_project"):
        return f"project context file: {file_name}"
    return f"matched task terms in {file_name}"


def _confidence(chunks: list[RetrievedChunk], project: str | None) -> float:
    if not chunks:
        return 0.0
    canonical = sum(1 for chunk in chunks if chunk.metadata.get("is_canonical"))
    project_hits = sum(1 for chunk in chunks if project and project.lower() in chunk.path.lower())
    if canonical >= 2 and (not project or project_hits >= 1):
        return 0.86
    if canonical >= 1 or project_hits >= 1:
        return 0.68
    return 0.42 if len(chunks) >= 3 else 0.25


def _missing_context(
    chunks: list[RetrievedChunk],
    sections: dict[str, list[str]],
    project: str | None,
) -> list[str]:
    missing: list[str] = []
    if not chunks:
        return ["No matching indexed Markdown chunks were found."]
    if not sections["current_state"]:
        missing.append("No clear current-state notes were found.")
    if not sections["prior_decisions"]:
        missing.append("No explicit decision notes were found.")
    if project and not any(project.lower() in chunk.path.lower() for chunk in chunks):
        missing.append(f"No project-specific notes were found for project '{project}'.")
    if not sections["open_questions"]:
        missing.append("No open-question notes were found.")
    return missing
