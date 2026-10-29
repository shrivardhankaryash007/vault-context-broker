"""Read Markdown files from the configured vault."""

from __future__ import annotations

from collections.abc import Iterator
from fnmatch import fnmatch
from pathlib import Path

from vault_context_mcp.config import VaultConfig
from vault_context_mcp.schemas import ScannedMarkdownFile
from vault_context_mcp.security import SecurityError, is_relative_to, relative_vault_path


class ScanError(RuntimeError):
    """Raised when vault scanning cannot proceed."""


def _ignored(parts: tuple[str, ...], ignore_dirs: set[str]) -> bool:
    return any(_ignored_part(part, ignore_dirs) for part in parts)


def _ignored_part(part: str, ignore_dirs: set[str]) -> bool:
    part_lower = part.lower()
    return any(fnmatch(part_lower, pattern.lower()) for pattern in ignore_dirs)


def iter_markdown_paths(config: VaultConfig) -> Iterator[Path]:
    """Yield safe Markdown paths under the configured vault root.

    Args:
        config: Runtime configuration.

    Yields:
        Safe Markdown files.

    Raises:
        ScanError: If vault root is missing or unreadable.
    """

    root = config.vault_root_path
    if not root.exists():
        raise ScanError(f"Vault root does not exist: {root}")
    if not root.is_dir():
        raise ScanError(f"Vault root is not a directory: {root}")

    ignore_dirs = set(config.ignore_dirs)
    try:
        for path in root.rglob("*.md"):
            if _ignored(path.relative_to(root).parts[:-1], ignore_dirs):
                continue
            try:
                resolved = path.resolve()
            except OSError as exc:
                raise ScanError(f"Could not resolve path {path}: {exc}") from exc
            if not is_relative_to(resolved, root):
                raise SecurityError(f"Symlink escapes configured vault root: {path}")
            if resolved.is_file():
                yield resolved
    except PermissionError as exc:
        raise ScanError(f"Permission denied while scanning vault {root}: {exc}") from exc


def scan_vault(config: VaultConfig) -> list[ScannedMarkdownFile]:
    """Scan the vault and return Markdown files with raw text.

    Args:
        config: Runtime configuration.

    Returns:
        List of scanned Markdown files sorted by relative path.
    """

    root = config.vault_root_path
    files: list[ScannedMarkdownFile] = []
    for path in iter_markdown_paths(config):
        try:
            stat = path.stat()
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = path.read_text(encoding="utf-8", errors="replace")
            stat = path.stat()
        except OSError as exc:
            raise ScanError(f"Could not read Markdown file {path}: {exc}") from exc
        files.append(
            ScannedMarkdownFile(
                path=relative_vault_path(path, root),
                absolute_path=str(path),
                modified_time=stat.st_mtime,
                size=stat.st_size,
                raw_text=text,
            )
        )
    return sorted(files, key=lambda item: item.path)
