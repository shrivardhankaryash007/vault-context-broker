"""Chunker tests."""

from __future__ import annotations

from vault_context_mcp.chunker import chunk_files
from vault_context_mcp.markdown_scanner import scan_vault
from vault_context_mcp.schemas import ScannedMarkdownFile


def test_chunker_preserves_headings_and_line_numbers(test_config) -> None:  # type: ignore[no-untyped-def]
    files = scan_vault(test_config)
    chunks = chunk_files(files, test_config)

    das = next(chunk for chunk in chunks if chunk.path == "projects/ATLAS/PROJECT_STATE.md")

    assert das.heading == "ATLAS Project State"
    assert das.line_start == 1
    assert das.line_end >= das.line_start
    assert das.metadata["is_canonical"] is True
    assert das.metadata["is_project"] is True


def test_chunker_tolerates_malformed_frontmatter(test_config) -> None:  # type: ignore[no-untyped-def]
    file = ScannedMarkdownFile(
        path="bad.md",
        absolute_path=str(test_config.vault_root_path / "bad.md"),
        modified_time=1,
        size=10,
        raw_text="---\nlayer: {{bad template}}\n---\n# Bad\n\n- Still index this note.",
    )

    chunks = chunk_files([file], test_config)

    assert chunks
    assert chunks[0].metadata["frontmatter"]["frontmatter_parse_error"] is True


def test_chunker_defaults_to_open_when_unmapped(test_config) -> None:  # type: ignore[no-untyped-def]
    files = scan_vault(test_config)
    chunks = chunk_files(files, test_config)

    state = next(chunk for chunk in chunks if chunk.path == "01_CURRENT_STATE.md")

    assert state.sensitivity == "open"


def test_chunker_applies_path_rule_default(test_config) -> None:  # type: ignore[no-untyped-def]
    files = scan_vault(test_config)
    chunks = chunk_files(files, test_config)

    acme_chunks = [chunk for chunk in chunks if chunk.path == "ACME/widget-design-notes.md"]
    journal_chunks = [
        chunk for chunk in chunks if chunk.path == "40-Thinking/Journal/private-reflection.md"
    ]

    assert acme_chunks and all(chunk.sensitivity == "restricted" for chunk in acme_chunks)
    assert journal_chunks and all(chunk.sensitivity == "restricted" for chunk in journal_chunks)


def test_chunker_frontmatter_sensitivity_overrides_path_rule(test_config) -> None:  # type: ignore[no-untyped-def]
    files = scan_vault(test_config)
    chunks = chunk_files(files, test_config)

    # Declares sensitivity: open under ACME/**, which path-rule-defaults to restricted.
    override_chunks = [chunk for chunk in chunks if chunk.path == "ACME/explicit-open-override.md"]

    assert override_chunks and all(chunk.sensitivity == "open" for chunk in override_chunks)


def test_chunker_frontmatter_sensitivity_applies_outside_any_path_rule(test_config) -> None:  # type: ignore[no-untyped-def]
    files = scan_vault(test_config)
    chunks = chunk_files(files, test_config)

    restricted_chunks = [chunk for chunk in chunks if chunk.path == "notes/explicit-restricted.md"]

    assert restricted_chunks and all(
        chunk.sensitivity == "restricted" for chunk in restricted_chunks
    )
