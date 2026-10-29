"""Pydantic schemas returned by the context broker."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

ContextMode = Literal["brief", "standard", "deep", "audit"]
LibrarianSeverity = Literal["info", "warning", "error"]
LLMSource = Literal["claude", "chatgpt", "gemini", "codex", "local", "other"]
Sensitivity = Literal["open", "restricted"]
Clearance = Literal["cloud", "local"]


class SourceRef(BaseModel):
    """Reference to a vault source used in a context pack."""

    path: str
    heading: str | None = None
    line_start: int | None = None
    line_end: int | None = None
    reason: str
    score: float


class RetrievedChunk(BaseModel):
    """Markdown chunk retrieved from the local index."""

    chunk_id: str
    path: str
    heading: str | None
    text: str
    line_start: int
    line_end: int
    score: float
    sensitivity: Sensitivity = "open"
    metadata: dict[str, Any] = Field(default_factory=dict)


class ContextPack(BaseModel):
    """Structured compact context prepared for an MCP client."""

    task: str
    mode: ContextMode
    project: str | None
    generated_at: str
    context_summary: str
    relevant_sources: list[SourceRef]
    current_state: list[str]
    prior_decisions: list[str]
    constraints: list[str]
    open_questions: list[str]
    key_facts: list[str]
    missing_context: list[str]
    suggested_next_files: list[SourceRef]
    confidence: float


class ScannedMarkdownFile(BaseModel):
    """Markdown file read from the configured vault."""

    path: str
    absolute_path: str
    modified_time: float
    size: int
    raw_text: str


class MarkdownChunk(BaseModel):
    """Markdown chunk produced before indexing."""

    chunk_id: str
    path: str
    heading: str | None
    text: str
    line_start: int
    line_end: int
    sensitivity: Sensitivity = "open"
    metadata: dict[str, Any] = Field(default_factory=dict)


class SearchResult(BaseModel):
    """Raw search result from the index before final ranking."""

    chunk: RetrievedChunk
    keyword_score: float


class LibrarianIssue(BaseModel):
    """One vault hygiene issue detected by the librarian."""

    issue_id: str
    severity: LibrarianSeverity
    category: str
    path: str | None = None
    heading: str | None = None
    line_start: int | None = None
    message: str
    recommendation: str
    can_auto_fix: bool = False
    proposed_action: str | None = None


class LibrarianReport(BaseModel):
    """Structured report from the local librarian."""

    generated_at: str
    vault_root: str
    indexed_file_count: int
    indexed_chunk_count: int
    index_refreshed: bool
    issue_count: int
    issues: list[LibrarianIssue]
    next_actions: list[str]


class LLMSessionLogRequest(BaseModel):
    """Request to persist an LLM conversation into the vault."""

    source: LLMSource
    title: str
    transcript: str
    origin: str = "manual"
    project: str | None = None
    domain: str | None = None
    summary: str | None = None
    key_takeaways: list[str] = Field(default_factory=list)
    decisions: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    append_daily_note: bool = True


class LLMSessionLogResult(BaseModel):
    """Result of writing an LLM session log."""

    path: str
    absolute_path: str
    source: LLMSource
    project: str | None
    daily_note_path: str | None = None
    index_refreshed: bool
    message: str


class LLMSessionSummary(BaseModel):
    """Compact summary of a persisted LLM session."""

    path: str
    source: str
    title: str
    captured: str | None = None
    project: str | None = None
    summary: str | None = None
    next_actions: list[str] = Field(default_factory=list)


class SessionHandoff(BaseModel):
    """Recent cross-client thinking handoff."""

    generated_at: str
    project: str | None
    sessions: list[LLMSessionSummary]
    synthesized_handoff: str
    suggested_next_actions: list[str]
