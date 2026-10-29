"""Tests for deterministic frontmatter sensitive marking."""

from __future__ import annotations

import pytest

from vault_context_mcp.sensitive_marker import (
    mark_content_sensitive,
    parse_frontmatter_and_body,
)


def test_parse_frontmatter_and_body_no_frontmatter() -> None:
    content = "# Just a header\n\nNo frontmatter here."
    fm_dict, body, fm_lines = parse_frontmatter_and_body(content)
    assert fm_dict is None
    assert body == content
    assert fm_lines == []


def test_parse_frontmatter_and_body_empty_frontmatter() -> None:
    content = "---\n---\n# Header\nBody content"
    fm_dict, body, fm_lines = parse_frontmatter_and_body(content)
    assert fm_dict == {}
    assert body == "# Header\nBody content"
    assert len(fm_lines) == 2


def test_parse_frontmatter_and_body_valid_frontmatter() -> None:
    content = "---\ntitle: test note\nauthor: Alex\n---\n# Header\nBody content"
    fm_dict, body, fm_lines = parse_frontmatter_and_body(content)
    assert fm_dict == {"title": "test note", "author": "Alex"}
    assert body == "# Header\nBody content"
    assert len(fm_lines) == 4


def test_parse_frontmatter_and_body_invalid_yaml() -> None:
    content = "---\n[invalid yaml: {:\n---\nBody"
    with pytest.raises(ValueError, match="Invalid YAML"):
        parse_frontmatter_and_body(content)


def test_parse_frontmatter_and_body_not_dict() -> None:
    content = "---\n- item 1\n- item 2\n---\nBody"
    with pytest.raises(ValueError, match="Frontmatter must be a YAML mapping"):
        parse_frontmatter_and_body(content)


def test_mark_content_sensitive_no_frontmatter() -> None:
    content = "# Title\n\nBody content here."
    new_content, modified = mark_content_sensitive(content)
    assert modified is True
    assert "sensitivity: restricted" in new_content
    assert "tags:" in new_content
    assert "sensitive" in new_content
    assert new_content.endswith("\n# Title\n\nBody content here.")


def test_mark_content_sensitive_existing_other_keys() -> None:
    content = "---\ntitle: My Note\ncreated: 2026-07-09\n---\nBody text"
    new_content, modified = mark_content_sensitive(content)
    assert modified is True
    assert "title: My Note" in new_content
    assert "created: 2026-07-09" in new_content
    assert "sensitivity: restricted" in new_content
    assert "tags:\n- sensitive" in new_content
    assert new_content.endswith("\nBody text")


def test_mark_content_sensitive_already_marked_idempotency() -> None:
    content = "---\nsensitivity: restricted\ntags:\n- sensitive\ntitle: test\n---\nBody"
    new_content, modified = mark_content_sensitive(content)
    assert modified is False
    assert new_content == content


def test_mark_content_sensitive_merge_tags_list() -> None:
    content = "---\ntitle: Note\ntags:\n- personal\n- journal\n---\nBody"
    new_content, modified = mark_content_sensitive(content)
    assert modified is True
    assert "sensitivity: restricted" in new_content
    assert "personal" in new_content
    assert "journal" in new_content
    assert "sensitive" in new_content


def test_mark_content_sensitive_merge_tags_string() -> None:
    content = "---\ntags: personal, work\n---\nBody"
    new_content, modified = mark_content_sensitive(content)
    assert modified is True
    assert "personal" in new_content
    assert "work" in new_content
    assert "sensitive" in new_content


def test_mark_content_sensitive_preserve_line_endings_crlf() -> None:
    content = "---\r\ntitle: CRLF Note\r\n---\r\nBody text\r\n"
    new_content, modified = mark_content_sensitive(content)
    assert modified is True
    assert "\r\n" in new_content
    assert "\n" not in new_content.replace("\r\n", "")
    assert new_content.endswith("\r\nBody text\r\n")


def test_mark_content_sensitive_preserve_body_exactly() -> None:
    content = "---\ntitle: Preserved\n---\n\n\n# Body Header\n\nMore body\n"
    new_content, modified = mark_content_sensitive(content)
    assert modified is True
    _, body, _ = parse_frontmatter_and_body(new_content)
    assert body == "\n\n# Body Header\n\nMore body\n"
