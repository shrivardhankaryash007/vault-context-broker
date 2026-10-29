"""Typed YAML configuration for the context broker."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator

from vault_context_mcp.schemas import ContextMode
from vault_context_mcp.utils import expand_path

CONFIG_ENV_VAR = "VAULT_CONTEXT_CONFIG"


class ConfigError(RuntimeError):
    """Raised when runtime configuration cannot be loaded."""


def default_max_chunks() -> dict[ContextMode, int]:
    """Return default chunk limits by mode."""

    return {"brief": 8, "standard": 18, "deep": 40, "audit": 60}


def default_max_output_tokens() -> dict[ContextMode, int]:
    """Return default output token budgets by mode."""

    return {"brief": 1000, "standard": 3000, "deep": 8000, "audit": 12000}


class RetrievalConfig(BaseModel):
    """Retrieval and output limits."""

    default_mode: ContextMode = "standard"
    max_chunks: dict[ContextMode, int] = Field(default_factory=default_max_chunks)
    max_output_tokens: dict[ContextMode, int] = Field(default_factory=default_max_output_tokens)
    canonical_boost: float = 2.5
    project_boost: float = 2.0
    recency_boost: float = 0.4
    archive_penalty: float = 0.3
    raw_penalty: float = 0.3


class SummarizerConfig(BaseModel):
    """Summarizer configuration."""

    provider: Literal["extractive", "ollama"] = "extractive"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1:8b"
    timeout_seconds: int = 30


class ProvenanceConfig(BaseModel):
    """Optional provenance tracking settings."""

    enabled: bool = False
    scope: list[str] = Field(default_factory=list)
    state_dir: str = "~/.vault-context-mcp/provenance"

    @property
    def state_path(self) -> Path:
        """Return the expanded provenance state directory."""

        return expand_path(self.state_dir)


class LibrarianConfig(BaseModel):
    """Local librarian automation settings."""

    enabled: bool = True
    watch_interval_seconds: int = 30
    debounce_seconds: int = 5
    auto_refresh_index: bool = True
    audit_on_refresh: bool = True
    write_reports_to_vault: bool = False
    report_path: str = "~/.vault-context-mcp/librarian_report.md"
    max_issues: int = 100
    require_manual_approval_for_vault_writes: bool = True
    auto_apply_fixes: bool = False
    provenance: ProvenanceConfig = Field(default_factory=ProvenanceConfig)


class SessionLogConfig(BaseModel):
    """Cross-LLM session logging settings."""

    enabled: bool = True
    base_path: str = "Main_Vault/00_Inbox/Chats"
    daily_notes_path: str = "Main_Vault/10-Daily"
    append_daily_note: bool = True
    create_daily_note: bool = False
    refresh_index_after_write: bool = True
    capture_server_host: str = "127.0.0.1"
    capture_server_port: int = 8765
    max_transcript_chars: int = 200_000
    summarize_on_capture: bool = True
    summarize_unprocessed_on_watch: bool = True
    source_paths: dict[str, str] = Field(
        default_factory=lambda: {
            "claude": "Main_Vault/00_Inbox/Chats/Claude",
            "chatgpt": "Main_Vault/00_Inbox/Chats/ChatGPT",
            "gemini": "Main_Vault/00_Inbox/Chats/Gemini",
            "codex": "Main_Vault/00_Inbox/Chats/Codex",
            "local": "Main_Vault/00_Inbox/Chats/Local",
            "other": "Main_Vault/00_Inbox/Chats/Other",
        }
    )


class SecurityConfig(BaseModel):
    """Security posture configuration."""

    readonly: bool = True
    allow_outside_vault: bool = False
    log_tool_calls: bool = True

    @field_validator("readonly")
    @classmethod
    def require_readonly(cls, value: bool) -> bool:
        """Reject write-enabled v0 configs."""

        if not value:
            raise ValueError("v0 is read-only; security.readonly must be true")
        return value


class VaultConfig(BaseModel):
    """Top-level runtime configuration."""

    vault_root: str
    index_path: str = "~/.vault-context-mcp/index.sqlite3"
    sensitivity_map_path: str = "~/.vault-context-mcp/sensitivity_map.yaml"
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)
    canonical_files: list[str] = Field(default_factory=list)
    ignore_dirs: list[str] = Field(default_factory=list)
    summarizer: SummarizerConfig = Field(default_factory=SummarizerConfig)
    librarian: LibrarianConfig = Field(default_factory=LibrarianConfig)
    session_log: SessionLogConfig = Field(default_factory=SessionLogConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)

    @property
    def vault_root_path(self) -> Path:
        """Return expanded vault root path."""

        return expand_path(self.vault_root)

    @property
    def index_file_path(self) -> Path:
        """Return expanded SQLite index path."""

        return expand_path(self.index_path)

    @property
    def sensitivity_map_file_path(self) -> Path:
        """Return expanded sensitivity_map.yaml path."""

        return expand_path(self.sensitivity_map_path)

    @property
    def canonical_file_names(self) -> set[str]:
        """Return canonical file names normalized case-insensitively."""

        return {Path(name).name.lower() for name in self.canonical_files}


def default_config_path(cwd: Path | None = None) -> Path | None:
    """Resolve the default runtime config path.

    Args:
        cwd: Optional working directory used for tests.

    Returns:
        Config path from env or `config.yaml` in the current working directory.
    """

    env_path = os.environ.get(CONFIG_ENV_VAR)
    if env_path:
        return expand_path(env_path)
    candidate = (cwd or Path.cwd()) / "config.yaml"
    if candidate.exists():
        return candidate.resolve()
    return None


def missing_config_message() -> str:
    """Return an actionable missing-config message."""

    return (
        "No vault-context-mcp config found. Copy config.example.yaml to config.yaml, "
        "edit vault_root, or set VAULT_CONTEXT_CONFIG=/absolute/path/to/config.yaml."
    )


def load_config(path: str | Path | None = None) -> VaultConfig:
    """Load the YAML runtime config.

    Args:
        path: Optional explicit config path.

    Returns:
        Validated VaultConfig.

    Raises:
        ConfigError: If config is missing, unreadable, or invalid.
    """

    config_path = expand_path(str(path)) if path is not None else default_config_path()
    if config_path is None:
        raise ConfigError(missing_config_message())
    if not config_path.exists():
        raise ConfigError(f"Config file does not exist: {config_path}")
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except OSError as exc:
        raise ConfigError(f"Could not read config file {config_path}: {exc}") from exc
    try:
        return VaultConfig.model_validate(raw)
    except ValidationError as exc:
        raise ConfigError(f"Invalid config file {config_path}: {exc}") from exc
