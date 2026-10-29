"""Sensitivity-class resolution: frontmatter contract + path-rule defaults.

Two classes only (v1): "open" and "restricted". This module is the security
boundary itself — every chunk gets a sensitivity class at index time
(resolve_sensitivity), and every caller gets a clearance at call time
(resolve_clearance). Filtering happens in the retriever's SQL, never
post-hoc. See docs/security_model.md and ADR 0036 (D2) for the full model.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path
from typing import Literal, cast

import yaml

Sensitivity = Literal["open", "restricted"]
Clearance = Literal["cloud", "local"]

CLEARANCE_ENV_VAR = "VAULT_CONTEXT_CLEARANCE"
CLIENT_ENV_VAR = "VAULT_CONTEXT_CLIENT"
UNKNOWN_CLIENT = "unknown"

_VALID_SENSITIVITY = {"open", "restricted"}
_VALID_CLEARANCE = {"cloud", "local"}


class SensitivityMapError(RuntimeError):
    """Raised when sensitivity_map.yaml cannot be parsed."""


@dataclass(frozen=True)
class SensitivityRule:
    """One path-rule default. First matching rule (in file order) wins."""

    pattern: str
    sensitivity: Sensitivity


def load_sensitivity_map(path: Path) -> list[SensitivityRule]:
    """Load path-rule defaults from sensitivity_map.yaml.

    Args:
        path: Path to the sensitivity map YAML file.

    Returns:
        Ordered list of path rules. Empty list when the file does not exist
        (every note is treated as unmapped => "open" by resolve_sensitivity;
        D2 rejected default-restricted-for-unmapped because it would blank
        cloud retrieval until a full backfill).

    Raises:
        SensitivityMapError: If the file exists but is unreadable or invalid.

    Example:
        >>> rules = load_sensitivity_map(Path("~/.vault-context-mcp/sensitivity_map.yaml").expanduser())
    """

    if not path.exists():
        return []
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except OSError as exc:
        raise SensitivityMapError(f"Could not read sensitivity map {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise SensitivityMapError(f"Invalid YAML in sensitivity map {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise SensitivityMapError(f"sensitivity_map.yaml must be a mapping at top level: {path}")
    rules_raw = raw.get("path_rules", [])
    if not isinstance(rules_raw, list):
        raise SensitivityMapError(f"sensitivity_map.yaml 'path_rules' must be a list: {path}")
    rules: list[SensitivityRule] = []
    for entry in rules_raw:
        if not isinstance(entry, dict) or "pattern" not in entry or "sensitivity" not in entry:
            raise SensitivityMapError(
                f"Each path_rules entry needs 'pattern' and 'sensitivity': {entry!r}"
            )
        sensitivity = entry["sensitivity"]
        if sensitivity not in _VALID_SENSITIVITY:
            raise SensitivityMapError(
                f"sensitivity must be 'open' or 'restricted', got {sensitivity!r}"
            )
        rules.append(
            SensitivityRule(
                pattern=str(entry["pattern"]), sensitivity=cast(Sensitivity, sensitivity)
            )
        )
    return rules


def path_matches(relative_path: str, pattern: str) -> bool:
    """Return whether a vault-relative path falls under a rule pattern.

    Args:
        relative_path: POSIX path relative to the vault root, e.g. "ACME/foo.md".
        pattern: Rule pattern, e.g. "ACME/**" or "Main_Vault/40-Thinking/Journal/**".
            A trailing "/**" means "this directory and everything under it."

    Returns:
        True when relative_path is the pattern's directory or a descendant,
        or matches the pattern as an fnmatch glob.
    """

    if fnmatch(relative_path, pattern):
        return True
    normalized = pattern[:-3] if pattern.endswith("/**") else pattern
    normalized = normalized.rstrip("/")
    return relative_path == normalized or relative_path.startswith(normalized + "/")


def path_sensitivity(relative_path: str, rules: list[SensitivityRule]) -> Sensitivity | None:
    """Return the path-rule sensitivity for a path, or None if unmapped.

    Args:
        relative_path: POSIX path relative to the vault root.
        rules: Ordered path rules from load_sensitivity_map.

    Returns:
        The first matching rule's sensitivity, or None when nothing matches.
    """

    for rule in rules:
        if path_matches(relative_path, rule.pattern):
            return rule.sensitivity
    return None


def resolve_sensitivity(
    relative_path: str,
    frontmatter: Mapping[str, object] | None,
    rules: list[SensitivityRule],
) -> Sensitivity:
    """Resolve the sensitivity class for one file.

    Frontmatter `sensitivity:` wins when present and valid. Otherwise the
    first matching path rule applies. Otherwise the file is "open".

    Args:
        relative_path: POSIX path relative to the vault root.
        frontmatter: Parsed frontmatter dict for the file, or None.
        rules: Ordered path rules from load_sensitivity_map.

    Returns:
        "open" or "restricted".

    Example:
        >>> resolve_sensitivity("ACME/notes.md", None, [SensitivityRule("ACME/**", "restricted")])
        'restricted'
    """

    if frontmatter is not None:
        declared = frontmatter.get("sensitivity")
        if isinstance(declared, str) and declared in _VALID_SENSITIVITY:
            return cast(Sensitivity, declared)
    path_rule = path_sensitivity(relative_path, rules)
    if path_rule is not None:
        return path_rule
    return "open"


def resolve_clearance(env: Mapping[str, str] | None = None) -> Clearance:
    """Resolve caller clearance from the environment.

    Missing or invalid declarations resolve to "cloud" (least privilege: a
    misconfigured new seat is safe by default, not leaky by default).

    Args:
        env: Environment mapping. Defaults to os.environ.

    Returns:
        "cloud" or "local".
    """

    mapping = env if env is not None else os.environ
    value = mapping.get(CLEARANCE_ENV_VAR, "cloud").strip().lower()
    return cast(Clearance, value) if value in _VALID_CLEARANCE else "cloud"


def resolve_client(env: Mapping[str, str] | None = None) -> str:
    """Resolve the declared client name from the environment for ledger logging.

    Args:
        env: Environment mapping. Defaults to os.environ.

    Returns:
        The declared client name, or "unknown" when not set or blank.
    """

    mapping = env if env is not None else os.environ
    value = mapping.get(CLIENT_ENV_VAR, "").strip()
    return value or UNKNOWN_CLIENT


def note_sensitivity(
    vault_root: Path, relative_path: str, rules: list[SensitivityRule]
) -> Sensitivity:
    """Resolve one note's sensitivity from its frontmatter and path rules.

    Used by tools that return note metadata (sessions, librarian issues)
    without going through the SQL clearance filter. Fails closed: a path that
    escapes the vault, is missing, or cannot be read resolves to "restricted".

    Args:
        vault_root: Absolute vault root.
        relative_path: Vault-relative note path.
        rules: Ordered path rules from ``load_sensitivity_map``.

    Returns:
        "open" or "restricted".

    Example:
        >>> note_sensitivity(Path("/vault"), "ACME/notes.md", [SensitivityRule("ACME/**", "restricted")])
        'restricted'
    """

    root = vault_root.resolve()
    try:
        path = (root / relative_path).resolve()
        path.relative_to(root)
        text = path.read_text(encoding="utf-8")
    except (OSError, ValueError):
        return "restricted"
    frontmatter: Mapping[str, object] | None = None
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            try:
                parsed = yaml.safe_load(text[3:end])
            except yaml.YAMLError:
                parsed = None
            if isinstance(parsed, dict):
                frontmatter = parsed
    return resolve_sensitivity(relative_path, frontmatter, rules)
