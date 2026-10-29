"""Deterministic frontmatter sensitive marker."""

from __future__ import annotations

import re
from typing import Any

import yaml


def parse_frontmatter_and_body(content: str) -> tuple[dict[str, Any] | None, str, list[str]]:
    """Split file content into frontmatter dict, note body, and raw frontmatter lines.

    Args:
        content: Raw note content.

    Returns:
        A tuple of (frontmatter_dict, body_content, raw_frontmatter_lines).

    Raises:
        ValueError: If frontmatter has invalid YAML or is not a mapping.
    """

    lines = content.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return None, content, []

    closing_idx = -1
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            closing_idx = idx
            break

    if closing_idx == -1:
        return None, content, []

    fm_raw = "".join(lines[1:closing_idx])
    body = "".join(lines[closing_idx + 1 :])
    fm_lines = lines[: closing_idx + 1]

    try:
        fm_dict = yaml.safe_load(fm_raw)
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML in frontmatter: {exc}") from exc

    if fm_dict is None:
        fm_dict = {}
    elif not isinstance(fm_dict, dict):
        raise ValueError(
            f"Frontmatter must be a YAML mapping (dict), got: {type(fm_dict).__name__}"
        )

    return fm_dict, body, fm_lines


def mark_content_sensitive(content: str) -> tuple[str, bool]:
    """Mark file content as restricted and sensitive in frontmatter.

    Args:
        content: Raw note content.

    Returns:
        A tuple of (new_content, modified).

    Raises:
        ValueError: If frontmatter has invalid YAML.
    """

    try:
        fm_dict, body, _ = parse_frontmatter_and_body(content)
    except ValueError as exc:
        raise exc

    line_ending = "\r\n" if "\r\n" in content else "\n"

    if fm_dict is None:
        new_fm = {
            "sensitivity": "restricted",
            "tags": ["sensitive"],
        }
        fm_yaml = yaml.safe_dump(new_fm, sort_keys=False, allow_unicode=True)
        # Ensure proper formatting of new frontmatter document
        fm_yaml_lines = [line.rstrip() for line in fm_yaml.splitlines() if line.strip()]
        fm_yaml_str = line_ending.join(fm_yaml_lines)
        new_content = f"---{line_ending}{fm_yaml_str}{line_ending}---{line_ending}{content}"
        return new_content, True

    modified = False

    curr_sensitivity = fm_dict.get("sensitivity")
    if curr_sensitivity != "restricted":
        fm_dict["sensitivity"] = "restricted"
        modified = True

    curr_tags = fm_dict.get("tags")
    if curr_tags is None:
        fm_dict["tags"] = ["sensitive"]
        modified = True
    else:
        if isinstance(curr_tags, list):
            # check for exact match
            if "sensitive" not in curr_tags:
                curr_tags.append("sensitive")
                modified = True
        elif isinstance(curr_tags, str):
            tag_list = [t.strip() for t in re.split(r"[\s,]+", curr_tags) if t.strip()]
            if "sensitive" not in tag_list:
                tag_list.append("sensitive")
                fm_dict["tags"] = tag_list
                modified = True
        else:
            fm_dict["tags"] = ["sensitive"]
            modified = True

    if not modified:
        return content, False

    fm_yaml = yaml.safe_dump(fm_dict, sort_keys=False, allow_unicode=True)
    fm_yaml_lines = [line.rstrip() for line in fm_yaml.splitlines() if line.strip()]
    fm_yaml_str = line_ending.join(fm_yaml_lines)

    new_content = f"---{line_ending}{fm_yaml_str}{line_ending}---{line_ending}{body}"
    return new_content, True
