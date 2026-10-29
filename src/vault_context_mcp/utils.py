"""Small shared utilities."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path


def utc_now_iso() -> str:
    """Return a compact UTC timestamp.

    Returns:
        ISO-8601 UTC timestamp with second precision.
    """

    return datetime.now(UTC).replace(microsecond=0).isoformat()


def expand_path(path: str) -> Path:
    """Expand a user path.

    Args:
        path: User supplied filesystem path.

    Returns:
        Expanded absolute path.
    """

    return Path(path).expanduser().resolve()


def normalize_posix(path: str | Path) -> str:
    """Normalize a path to stable POSIX separators.

    Args:
        path: Path-like value.

    Returns:
        POSIX path string.
    """

    return Path(path).as_posix()


def truncate_words(text: str, max_words: int) -> str:
    """Truncate text by words without inventing content.

    Args:
        text: Input text.
        max_words: Maximum number of words to keep.

    Returns:
        Original text or a word-truncated version.
    """

    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]).rstrip() + " ..."
