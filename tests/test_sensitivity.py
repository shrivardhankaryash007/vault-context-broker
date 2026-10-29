"""Tests for the sensitivity-class resolution boundary."""

from __future__ import annotations

from pathlib import Path

import pytest

from vault_context_mcp.sensitivity import (
    SensitivityMapError,
    SensitivityRule,
    load_sensitivity_map,
    path_matches,
    resolve_clearance,
    resolve_client,
    resolve_sensitivity,
)

ACME_RULE = SensitivityRule(pattern="ACME/**", sensitivity="restricted")
JOURNAL_RULE = SensitivityRule(
    pattern="Main_Vault/40-Thinking/Journal/**", sensitivity="restricted"
)
RULES = [ACME_RULE, JOURNAL_RULE]


def test_path_matches_directory_prefix() -> None:
    assert path_matches("ACME/03-Design/foo.md", "ACME/**")
    assert path_matches("ACME", "ACME/**")
    assert not path_matches("ACME-adjacent/foo.md", "ACME/**")
    assert not path_matches("Main_Vault/foo.md", "ACME/**")


def test_path_sensitivity_first_match_wins() -> None:
    from vault_context_mcp.sensitivity import path_sensitivity

    assert path_sensitivity("ACME/foo.md", RULES) == "restricted"
    assert path_sensitivity("Main_Vault/00_Inbox/foo.md", RULES) is None


def test_resolve_sensitivity_frontmatter_overrides_path_rule() -> None:
    assert resolve_sensitivity("ACME/foo.md", {"sensitivity": "open"}, RULES) == "open"


def test_resolve_sensitivity_path_rule_when_no_frontmatter() -> None:
    assert resolve_sensitivity("ACME/foo.md", None, RULES) == "restricted"
    assert resolve_sensitivity("ACME/foo.md", {}, RULES) == "restricted"


def test_resolve_sensitivity_defaults_to_open_when_unmapped() -> None:
    assert resolve_sensitivity("Main_Vault/00_Inbox/foo.md", None, RULES) == "open"


def test_resolve_sensitivity_ignores_invalid_frontmatter_value() -> None:
    assert resolve_sensitivity("ACME/foo.md", {"sensitivity": "top-secret"}, RULES) == "restricted"


def test_load_sensitivity_map_missing_file_returns_empty(tmp_path: Path) -> None:
    assert load_sensitivity_map(tmp_path / "missing.yaml") == []


def test_load_sensitivity_map_parses_path_rules(tmp_path: Path) -> None:
    path = tmp_path / "sensitivity_map.yaml"
    path.write_text(
        "path_rules:\n"
        "  - pattern: 'ACME/**'\n"
        "    sensitivity: restricted\n"
        "  - pattern: 'Main_Vault/40-Thinking/Journal/**'\n"
        "    sensitivity: restricted\n",
        encoding="utf-8",
    )
    rules = load_sensitivity_map(path)
    assert rules == RULES


def test_load_sensitivity_map_rejects_invalid_sensitivity(tmp_path: Path) -> None:
    path = tmp_path / "sensitivity_map.yaml"
    path.write_text(
        "path_rules:\n  - pattern: 'ACME/**'\n    sensitivity: top-secret\n", encoding="utf-8"
    )
    with pytest.raises(SensitivityMapError):
        load_sensitivity_map(path)


def test_load_sensitivity_map_rejects_missing_fields(tmp_path: Path) -> None:
    path = tmp_path / "sensitivity_map.yaml"
    path.write_text("path_rules:\n  - pattern: 'ACME/**'\n", encoding="utf-8")
    with pytest.raises(SensitivityMapError):
        load_sensitivity_map(path)


def test_resolve_clearance_defaults_to_cloud_when_missing() -> None:
    assert resolve_clearance({}) == "cloud"


def test_resolve_clearance_defaults_to_cloud_when_invalid() -> None:
    assert resolve_clearance({"VAULT_CONTEXT_CLEARANCE": "admin"}) == "cloud"


def test_resolve_clearance_reads_local() -> None:
    assert resolve_clearance({"VAULT_CONTEXT_CLEARANCE": "local"}) == "local"


def test_resolve_clearance_is_case_insensitive() -> None:
    assert resolve_clearance({"VAULT_CONTEXT_CLEARANCE": "LOCAL"}) == "local"


def test_resolve_client_defaults_to_unknown() -> None:
    assert resolve_client({}) == "unknown"


def test_resolve_client_reads_declared_name() -> None:
    assert resolve_client({"VAULT_CONTEXT_CLIENT": "codex"}) == "codex"
