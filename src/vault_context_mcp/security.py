"""Filesystem safety helpers."""

from __future__ import annotations

from pathlib import Path


class SecurityError(RuntimeError):
    """Raised when a path violates the vault security model."""


def is_relative_to(path: Path, root: Path) -> bool:
    """Return whether path is inside root.

    Args:
        path: Candidate path.
        root: Required root.

    Returns:
        True when path is root or a descendant.
    """

    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def resolve_and_validate_path(path: str | Path, vault_root: str | Path) -> Path:
    """Resolve a path and ensure it stays under the vault root.

    Args:
        path: Candidate path, absolute or relative to the vault root.
        vault_root: Configured vault root.

    Returns:
        Resolved safe path.

    Raises:
        SecurityError: If the path escapes the vault root.
    """

    root = Path(vault_root).expanduser().resolve()
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve()
    if not is_relative_to(resolved, root):
        raise SecurityError(f"Path escapes configured vault root: {path}")
    return resolved


def relative_vault_path(path: str | Path, vault_root: str | Path) -> str:
    """Return a validated path relative to the vault root.

    Args:
        path: Candidate path.
        vault_root: Configured vault root.

    Returns:
        POSIX relative path.
    """

    root = Path(vault_root).expanduser().resolve()
    return resolve_and_validate_path(path, root).relative_to(root).as_posix()
