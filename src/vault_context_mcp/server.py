"""FastMCP stdio server and direct tool functions."""

from __future__ import annotations

from collections import Counter
from typing import Any, Literal

from vault_context_mcp.config import VaultConfig, load_config
from vault_context_mcp.context_builder import tool_get_context_pack
from vault_context_mcp.index_store import IndexStore, build_index
from vault_context_mcp.librarian import audit_vault
from vault_context_mcp.retriever import (
    chunks_for_file_name,
)
from vault_context_mcp.retriever import (
    search_vault as retrieve_search,
)
from vault_context_mcp.schemas import ContextMode, LLMSessionLogRequest
from vault_context_mcp.sensitivity import (
    load_sensitivity_map,
    note_sensitivity,
    resolve_clearance,
    resolve_client,
)
from vault_context_mcp.session_logger import (
    build_session_handoff,
    log_llm_session,
    process_unprocessed_sessions,
    recent_sessions,
)

FRICTIONLESS_SESSION_LOGGING_PROMPT = """Use vault-context-mcp as the session memory layer.

At the start of substantial work:
- If the user names a project or ongoing thread, call get_session_handoff(project=...) before answering.
- Use get_context_pack for compact cited vault context when more project context is needed.

At any point:
- If the user says "log this", "log this chat", "log this session", "save this session", "remember this", or equivalent, call log_session immediately.
- Do not ask the user to copy, paste, export, or summarize the chat first.
- Use the current conversation as the transcript.
- Set source to this client name when known: claude, chatgpt, gemini, codex, local, or other.
- Include a concise title, origin/client, project if known, summary, key takeaways, decisions, open questions, and next actions.

At the end of substantial work:
- Offer to log the session only if the user has not already asked.
- If the user agrees, call log_session.
"""


def _estimate_tokens(payload: object) -> int:
    """Rough token estimate for ledger logging (chars / 4, no tokenizer dependency)."""

    import json

    return len(json.dumps(payload, default=str)) // 4


def get_context_pack(
    task: str,
    mode: ContextMode = "standard",
    project: str | None = None,
    config: VaultConfig | None = None,
) -> dict[str, object]:
    """Return a structured context pack."""

    runtime_config = config or load_config()
    clearance = resolve_clearance()
    resolve_client()
    return tool_get_context_pack(
        task=task,
        mode=mode,
        project=project,
        config=runtime_config,
        clearance=clearance,
    )


def search_vault(
    query: str,
    top_k: int = 10,
    project: str | None = None,
    config: VaultConfig | None = None,
) -> list[dict[str, object]]:
    """Search the vault and return compact chunk results."""

    runtime_config = config or load_config()
    clearance = resolve_clearance()
    client = resolve_client()
    chunks = retrieve_search(
        runtime_config, query, top_k=top_k, project=project, clearance=clearance
    )
    if runtime_config.security.log_tool_calls:
        payload = [chunk.model_dump() for chunk in chunks]
        IndexStore(runtime_config.index_file_path).log_tool_call(
            "search_vault",
            {"query": query, "top_k": top_k, "project": project},
            client=client,
            clearance=clearance,
            chunks_returned=len(chunks),
            est_tokens=_estimate_tokens(payload),
        )
    return [chunk.model_dump() for chunk in chunks]


def get_project_state(project: str, config: VaultConfig | None = None) -> list[dict[str, object]]:
    """Return project state chunks for a project."""

    runtime_config = config or load_config()
    clearance = resolve_clearance()
    client = resolve_client()
    chunks = chunks_for_file_name(
        runtime_config, {"PROJECT_STATE.md"}, project=project, clearance=clearance
    )
    if runtime_config.security.log_tool_calls:
        payload = [chunk.model_dump() for chunk in chunks]
        IndexStore(runtime_config.index_file_path).log_tool_call(
            "get_project_state",
            {"project": project},
            client=client,
            clearance=clearance,
            chunks_returned=len(chunks),
            est_tokens=_estimate_tokens(payload),
        )
    return [chunk.model_dump() for chunk in chunks]


def get_decisions(
    topic: str | None = None,
    project: str | None = None,
    config: VaultConfig | None = None,
) -> list[dict[str, object]]:
    """Return decision chunks, optionally filtered by topic or project."""

    runtime_config = config or load_config()
    clearance = resolve_clearance()
    client = resolve_client()
    if topic:
        chunks = retrieve_search(
            runtime_config,
            f"{topic} decisions",
            top_k=12,
            project=project,
            clearance=clearance,
        )
        chunks = [
            chunk
            for chunk in chunks
            if "decision" in chunk.path.lower() or "decision" in chunk.text.lower()
        ]
    else:
        chunks = chunks_for_file_name(
            runtime_config,
            {"03_DECISIONS.md", "DECISIONS.md"},
            project=project,
            clearance=clearance,
        )
    if runtime_config.security.log_tool_calls:
        payload = [chunk.model_dump() for chunk in chunks]
        IndexStore(runtime_config.index_file_path).log_tool_call(
            "get_decisions",
            {"topic": topic, "project": project},
            client=client,
            clearance=clearance,
            chunks_returned=len(chunks),
            est_tokens=_estimate_tokens(payload),
        )
    return [chunk.model_dump() for chunk in chunks]


def get_open_questions(
    project: str | None = None,
    config: VaultConfig | None = None,
) -> list[dict[str, object]]:
    """Return open-question chunks."""

    runtime_config = config or load_config()
    clearance = resolve_clearance()
    client = resolve_client()
    chunks = chunks_for_file_name(
        runtime_config, {"OPEN_QUESTIONS.md"}, project=project, clearance=clearance
    )
    if runtime_config.security.log_tool_calls:
        payload = [chunk.model_dump() for chunk in chunks]
        IndexStore(runtime_config.index_file_path).log_tool_call(
            "get_open_questions",
            {"project": project},
            client=client,
            clearance=clearance,
            chunks_returned=len(chunks),
            est_tokens=_estimate_tokens(payload),
        )
    return [chunk.model_dump() for chunk in chunks]


def refresh_index(force: bool = False, config: VaultConfig | None = None) -> dict[str, object]:
    """Refresh the read-only vault index."""

    runtime_config = config or load_config()
    store = IndexStore(runtime_config.index_file_path)
    if not force and store.chunk_count() > 0:
        return {"refreshed": False, "reason": "index already exists; pass force=true"}
    file_count, chunk_count, fts_enabled = build_index(runtime_config)
    if runtime_config.security.log_tool_calls:
        store.log_tool_call("refresh_index", {"force": force})
    return {
        "refreshed": True,
        "file_count": file_count,
        "chunk_count": chunk_count,
        "fts5_enabled": fts_enabled,
    }


_SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}


def get_librarian_report(
    refresh_index_first: bool = False,
    limit: int = 25,
    config: VaultConfig | None = None,
) -> dict[str, object]:
    """Return a bounded vault hygiene report visible at the caller's clearance.

    Issues on restricted notes are withheld from non-local callers (their paths
    and titles are themselves private). At most ``limit`` issues are returned,
    most severe first; counts by category cover every visible issue.
    """

    runtime_config = config or load_config()
    audit = audit_vault(runtime_config, refresh_index=refresh_index_first)
    clearance = resolve_clearance()
    rules = load_sensitivity_map(runtime_config.sensitivity_map_file_path)
    visible = [
        issue
        for issue in audit.issues
        if clearance == "local"
        or issue.path is None
        or note_sensitivity(runtime_config.vault_root_path, issue.path, rules) == "open"
    ]
    visible.sort(key=lambda issue: _SEVERITY_ORDER.get(issue.severity, 3))
    shown = visible[: max(limit, 0)]
    report: dict[str, object] = audit.model_dump()
    report["issues"] = [issue.model_dump() for issue in shown]
    report["issue_count"] = len(visible)
    report["issues_omitted_count"] = len(visible) - len(shown)
    report["withheld_restricted_count"] = len(audit.issues) - len(visible)
    report["issue_counts_by_category"] = dict(Counter(issue.category for issue in visible))
    if runtime_config.security.log_tool_calls:
        IndexStore(runtime_config.index_file_path).log_tool_call(
            "get_librarian_report",
            {"refresh_index_first": refresh_index_first},
        )
    return report


def log_session(
    source: str,
    title: str,
    transcript: str,
    origin: str = "manual",
    project: str | None = None,
    domain: str | None = None,
    summary: str | None = None,
    key_takeaways: list[str] | None = None,
    decisions: list[str] | None = None,
    open_questions: list[str] | None = None,
    next_actions: list[str] | None = None,
    tags: list[str] | None = None,
    append_daily_note: bool = True,
    config: VaultConfig | None = None,
) -> dict[str, object]:
    """Persist an LLM session log into the vault."""

    runtime_config = config or load_config()
    request = LLMSessionLogRequest.model_validate(
        {
            "source": source,
            "title": title,
            "transcript": transcript,
            "origin": origin,
            "project": project,
            "domain": domain,
            "summary": summary,
            "key_takeaways": key_takeaways or [],
            "decisions": decisions or [],
            "open_questions": open_questions or [],
            "next_actions": next_actions or [],
            "tags": tags or [],
            "append_daily_note": append_daily_note,
        }
    )
    result = log_llm_session(runtime_config, request)
    if runtime_config.security.log_tool_calls:
        IndexStore(runtime_config.index_file_path).log_tool_call(
            "log_session", {"source": source, "title": title, "project": project}
        )
    return result.model_dump()


def get_recent_sessions(
    project: str | None = None,
    source: str | None = None,
    limit: int = 10,
    config: VaultConfig | None = None,
) -> list[dict[str, object]]:
    """Return recent cross-client LLM sessions."""

    runtime_config = config or load_config()
    sessions = recent_sessions(
        runtime_config,
        project=project,
        source=source,
        limit=limit,
        clearance=resolve_clearance(),
    )
    return [session.model_dump() for session in sessions]


def get_session_handoff(
    project: str | None = None,
    limit: int = 8,
    config: VaultConfig | None = None,
) -> dict[str, object]:
    """Return a cross-client handoff from recent LLM sessions."""

    runtime_config = config or load_config()
    return build_session_handoff(
        runtime_config, project=project, limit=limit, clearance=resolve_clearance()
    ).model_dump()


def process_sessions(config: VaultConfig | None = None) -> dict[str, object]:
    """Summarize all unprocessed session captures using the local model."""

    runtime_config = config or load_config()
    updated = process_unprocessed_sessions(runtime_config)
    if runtime_config.security.log_tool_calls:
        IndexStore(runtime_config.index_file_path).log_tool_call(
            "process_sessions", {"updated_count": len(updated)}
        )
    return {"updated": updated, "count": len(updated)}


def create_mcp_server() -> Any:
    """Create the FastMCP server.

    Returns:
        FastMCP server instance.
    """

    import time

    from mcp.server.fastmcp import FastMCP

    from vault_context_mcp import call_log

    def _client_name(server: Any) -> str:
        """Read the initialized MCP client name when available."""

        try:
            raw = server.get_context().session.client_params.clientInfo.name
            return call_log.client_label(raw)
        except Exception:
            # This is a best-effort read of the client label.
            return "unknown"

    class _LoggedFastMCP(FastMCP):
        async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
            started = time.monotonic()
            ok = False
            try:
                result = await super().call_tool(name, arguments)
                ok = True
                return result
            finally:
                call_log.record_call(
                    name,
                    _client_name(self),
                    ok,
                    int((time.monotonic() - started) * 1000),
                )

    mcp = _LoggedFastMCP("vault-context-mcp")

    @mcp.tool(name="get_context_pack")
    def get_context_pack_tool(
        task: str,
        mode: Literal["brief", "standard", "deep", "audit"] = "standard",
        project: str | None = None,
    ) -> dict[str, object]:
        return get_context_pack(task=task, mode=mode, project=project)

    @mcp.tool(name="search_vault")
    def search_vault_tool(
        query: str,
        top_k: int = 10,
        project: str | None = None,
    ) -> list[dict[str, object]]:
        return search_vault(query=query, top_k=top_k, project=project)

    @mcp.tool(name="get_project_state")
    def get_project_state_tool(project: str) -> list[dict[str, object]]:
        return get_project_state(project=project)

    @mcp.tool(name="get_decisions")
    def get_decisions_tool(
        topic: str | None = None,
        project: str | None = None,
    ) -> list[dict[str, object]]:
        return get_decisions(topic=topic, project=project)

    @mcp.tool(name="get_open_questions")
    def get_open_questions_tool(project: str | None = None) -> list[dict[str, object]]:
        return get_open_questions(project=project)

    @mcp.tool(name="refresh_index")
    def refresh_index_tool(force: bool = False) -> dict[str, object]:
        return refresh_index(force=force)

    @mcp.tool(name="get_librarian_report")
    def get_librarian_report_tool(
        refresh_index_first: bool = False, limit: int = 25
    ) -> dict[str, object]:
        return get_librarian_report(refresh_index_first=refresh_index_first, limit=limit)

    @mcp.tool(
        name="log_session",
        description=(
            "Persist the current LLM chat/session into the Obsidian vault. Use this immediately "
            "when the user says phrases like 'log this chat', 'log this session', 'save this', "
            "or 'remember this'; do not ask the user to copy or paste the transcript first."
        ),
    )
    def log_session_tool(
        source: str,
        title: str,
        transcript: str,
        origin: str = "manual",
        project: str | None = None,
        domain: str | None = None,
        summary: str | None = None,
        key_takeaways: list[str] | None = None,
        decisions: list[str] | None = None,
        open_questions: list[str] | None = None,
        next_actions: list[str] | None = None,
        tags: list[str] | None = None,
        append_daily_note: bool = True,
    ) -> dict[str, object]:
        return log_session(
            source=source,
            title=title,
            transcript=transcript,
            origin=origin,
            project=project,
            domain=domain,
            summary=summary,
            key_takeaways=key_takeaways,
            decisions=decisions,
            open_questions=open_questions,
            next_actions=next_actions,
            tags=tags,
            append_daily_note=append_daily_note,
        )

    @mcp.tool(name="get_recent_sessions")
    def get_recent_sessions_tool(
        project: str | None = None,
        source: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, object]]:
        return get_recent_sessions(project=project, source=source, limit=limit)

    @mcp.tool(name="get_session_handoff")
    def get_session_handoff_tool(project: str | None = None, limit: int = 8) -> dict[str, object]:
        return get_session_handoff(project=project, limit=limit)

    @mcp.tool(
        name="process_sessions",
        description=(
            "Summarize all unprocessed session captures using the local Ollama model. "
            "Call this to enrich raw captures with summary, key takeaways, decisions, "
            "open questions, and next actions."
        ),
    )
    def process_sessions_tool() -> dict[str, object]:
        return process_sessions()

    @mcp.prompt(
        name="frictionless_session_logging",
        title="Frictionless Session Logging",
        description=(
            "Client instruction that makes 'log this chat/session' map directly to log_session."
        ),
    )
    def frictionless_session_logging_prompt() -> str:
        return FRICTIONLESS_SESSION_LOGGING_PROMPT

    return mcp


def run_stdio_server() -> None:
    """Run the MCP server over stdio."""

    server: Any = create_mcp_server()
    server.run()
