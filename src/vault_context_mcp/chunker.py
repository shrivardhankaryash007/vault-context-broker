"""Heading-aware Markdown chunking."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

import yaml

from vault_context_mcp.config import VaultConfig
from vault_context_mcp.schemas import MarkdownChunk, ScannedMarkdownFile
from vault_context_mcp.sensitivity import load_sensitivity_map, resolve_sensitivity
from vault_context_mcp.utils import truncate_words

HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
FRONTMATTER_BOUNDARY = "---"


def _parse_frontmatter(lines: list[str]) -> tuple[dict[str, Any], int]:
    if not lines or lines[0].strip() != FRONTMATTER_BOUNDARY:
        return {}, 0
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == FRONTMATTER_BOUNDARY:
            raw = "\n".join(lines[1:index])
            try:
                parsed = yaml.safe_load(raw) if raw.strip() else {}
            except yaml.YAMLError:
                parsed = {"raw_frontmatter": raw, "frontmatter_parse_error": True}
            return (parsed if isinstance(parsed, dict) else {"frontmatter": parsed}, index + 1)
    return {}, 0


def _chunk_id(path: str, line_start: int, heading: str | None, text: str) -> str:
    digest = hashlib.sha1(f"{path}:{line_start}:{heading}:{text[:120]}".encode()).hexdigest()[:16]
    return f"{path}:{line_start}:{digest}"


def _heading_label(stack: list[tuple[int, str]]) -> str | None:
    if not stack:
        return None
    return " > ".join(title for _, title in stack)


def _split_oversized(text: str, max_words: int = 1200) -> list[str]:
    if len(text.split()) <= max_words:
        return [text]
    paragraphs = [paragraph.strip() for paragraph in text.split("\n\n") if paragraph.strip()]
    chunks: list[str] = []
    current: list[str] = []
    current_words = 0
    for paragraph in paragraphs:
        paragraph_words = len(paragraph.split())
        if current and current_words + paragraph_words > max_words:
            chunks.append("\n\n".join(current))
            current = []
            current_words = 0
        if paragraph_words > max_words:
            chunks.append(truncate_words(paragraph, max_words))
            continue
        current.append(paragraph)
        current_words += paragraph_words
    if current:
        chunks.append("\n\n".join(current))
    return chunks


def _metadata_for_file(file: ScannedMarkdownFile, config: VaultConfig) -> dict[str, Any]:
    path = Path(file.path)
    lower_parts = [part.lower() for part in path.parts]
    return {
        "modified_time": file.modified_time,
        "size": file.size,
        "is_canonical": path.name.lower() in config.canonical_file_names,
        "is_project": "projects" in lower_parts,
        "file_name": path.name,
    }


def chunk_markdown_file(file: ScannedMarkdownFile, config: VaultConfig) -> list[MarkdownChunk]:
    """Chunk one Markdown file by heading hierarchy.

    Args:
        file: Scanned Markdown file.
        config: Runtime configuration.

    Returns:
        Heading-aware chunks with line ranges and metadata.
    """

    lines = file.raw_text.splitlines()
    frontmatter, content_start = _parse_frontmatter(lines)
    rules = load_sensitivity_map(config.sensitivity_map_file_path)
    sensitivity = resolve_sensitivity(file.path, frontmatter or None, rules)
    base_metadata = _metadata_for_file(file, config)
    if frontmatter:
        base_metadata["frontmatter"] = frontmatter

    chunks: list[MarkdownChunk] = []
    heading_stack: list[tuple[int, str]] = []
    current_lines: list[tuple[int, str]] = []
    current_heading = None

    def flush() -> None:
        nonlocal current_lines
        if not current_lines:
            return
        text = "\n".join(line for _, line in current_lines).strip()
        if not text:
            current_lines = []
            return
        line_start = current_lines[0][0]
        line_end = current_lines[-1][0]
        splits = _split_oversized(text)
        for offset, split in enumerate(splits):
            chunks.append(
                MarkdownChunk(
                    chunk_id=_chunk_id(file.path, line_start + offset, current_heading, split),
                    path=file.path,
                    heading=current_heading,
                    text=split,
                    line_start=line_start,
                    line_end=line_end,
                    sensitivity=sensitivity,
                    metadata=base_metadata.copy(),
                )
            )
        current_lines = []

    for number, line in enumerate(lines[content_start:], start=content_start + 1):
        match = HEADING_RE.match(line)
        if match:
            flush()
            level = len(match.group(1))
            title = match.group(2).strip()
            heading_stack = [
                (h_level, h_title) for h_level, h_title in heading_stack if h_level < level
            ]
            heading_stack.append((level, title))
            current_heading = _heading_label(heading_stack)
        current_lines.append((number, line))
    flush()

    if not chunks and file.raw_text.strip():
        text = file.raw_text.strip()
        chunks.append(
            MarkdownChunk(
                chunk_id=_chunk_id(file.path, 1, None, text),
                path=file.path,
                heading=None,
                text=text,
                line_start=1,
                line_end=max(1, len(lines)),
                sensitivity=sensitivity,
                metadata=base_metadata,
            )
        )
    return chunks


def chunk_files(files: list[ScannedMarkdownFile], config: VaultConfig) -> list[MarkdownChunk]:
    """Chunk scanned Markdown files.

    Args:
        files: Scanned Markdown files.
        config: Runtime configuration.

    Returns:
        All Markdown chunks.
    """

    chunks: list[MarkdownChunk] = []
    for file in files:
        chunks.extend(chunk_markdown_file(file, config))
    return chunks
