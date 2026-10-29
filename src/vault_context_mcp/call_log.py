"""Append metadata-only records for MCP tool calls."""

from __future__ import annotations

import json
import logging
import os
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path

DEFAULT_LOG_PATH: Path = Path.home() / ".local/share/agentic-os/mcp/vault-context-mcp.jsonl"
LOG_ENV = "AGENTIC_OS_VAULT_MCP_LOG"
_CLIENT_RE = re.compile(r"[A-Za-z0-9._-]{1,40}")


def log_path() -> Path | None:
    """Return the configured call-log path, or None when logging is disabled.

    Returns:
        The environment-configured path, the default path, or None.

    Example:
        ``log_path()`` returns the default path when the environment is unset.
    """

    configured = os.environ.get(LOG_ENV)
    if configured is None:
        return DEFAULT_LOG_PATH
    if configured == "":
        return None
    return Path(configured)


def client_label(raw: object) -> str:
    """Return a safe client label or ``unknown``.

    Args:
        raw: The client name supplied during MCP initialization.

    Returns:
        The validated client name or ``unknown``.

    Example:
        ``client_label("claude-code")`` returns ``"claude-code"``.
    """

    if isinstance(raw, str) and _CLIENT_RE.fullmatch(raw):
        return raw
    return "unknown"


def record_call(
    tool: str,
    client: str,
    ok: bool,
    ms: int,
    *,
    now: datetime | None = None,
) -> None:
    """Append one metadata-only MCP call record.

    Args:
        tool: The called tool name.
        client: The sanitized client label.
        ok: Whether the tool call completed successfully.
        ms: The call duration in milliseconds.
        now: Optional timestamp override for deterministic callers.

    Returns:
        None.

    Example:
        ``record_call("search_vault", "claude-code", True, 12)`` appends a
        single JSON line to the configured log.
    """

    path = log_path()
    if path is None:
        return

    timestamp = (now or datetime.now(UTC)).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    line = (
        json.dumps(
            {
                "ts": timestamp,
                "call_id": uuid.uuid4().hex,
                "tool": tool,
                "client": client,
                "ok": ok,
                "ms": ms,
            },
            separators=(",", ":"),
        )
        + "\n"
    )

    fd: int | None = None
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        os.fchmod(fd, 0o600)
        os.write(fd, line.encode("utf-8"))
    except (OSError, ValueError) as exc:
        logging.getLogger(__name__).debug("Could not append MCP call log: %s", exc)
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError as exc:
                logging.getLogger(__name__).debug("Could not close MCP call log: %s", exc)
