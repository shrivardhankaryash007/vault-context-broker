"""Independent provenance checks for filesystem and recovery boundaries."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vault_context_mcp import provenance
from vault_context_mcp.config import VaultConfig


def prepare(config: VaultConfig, tmp_path: Path) -> Path:
    """Configure a fresh synthetic scope and external state directory."""
    scope = config.vault_root_path / "proof"
    scope.mkdir()
    (scope / "note.md").write_text("source", encoding="utf-8")
    config.librarian.provenance.enabled = True
    config.librarian.provenance.scope = ["proof"]
    config.librarian.provenance.state_dir = str(tmp_path / "state")
    return scope


def test_state_inside_vault_is_rejected(test_config: VaultConfig, tmp_path: Path) -> None:
    """A caller cannot make provenance write into the read-only vault."""
    prepare(test_config, tmp_path)
    state = test_config.vault_root_path / "state"
    test_config.librarian.provenance.state_dir = str(state)
    with pytest.raises(provenance.ProvenanceError):
        provenance.scan(test_config)
    assert not state.exists()


def test_symlink_scope_is_rejected(test_config: VaultConfig, tmp_path: Path) -> None:
    """A scope cannot bypass the skip-symlinks contract through resolution."""
    prepare(test_config, tmp_path)
    (test_config.vault_root_path / "alias").symlink_to("proof", target_is_directory=True)
    test_config.librarian.provenance.scope = ["alias"]
    with pytest.raises(provenance.ProvenanceError):
        provenance.scan(test_config)


@pytest.mark.parametrize("value", [[], None, {"seq": 1}, {"seq": True}])
def test_malformed_log_object_is_typed_error(
    test_config: VaultConfig, tmp_path: Path, value: object
) -> None:
    """Valid JSON with an invalid event schema is corruption, not a torn tail."""
    prepare(test_config, tmp_path)
    state = test_config.librarian.provenance.state_path
    state.mkdir()
    log = state / "transitions.jsonl"
    log.write_text(json.dumps(value) + "\n", encoding="utf-8")
    before = log.read_bytes()
    with pytest.raises(provenance.ProvenanceError):
        provenance.load(test_config)
    assert log.read_bytes() == before


def test_deleted_restricted_frontmatter_stays_hidden(
    test_config: VaultConfig, tmp_path: Path
) -> None:
    """Deletion must not disclose a previously restricted title to cloud seats."""
    scope = prepare(test_config, tmp_path)
    note = scope / "note.md"
    note.write_text("---\nsensitivity: restricted\n---\nsource", encoding="utf-8")
    provenance.scan(test_config)
    provenance.propose(test_config, "derived", ["proof/note.md"])
    note.unlink()
    provenance.scan(test_config)
    cloud = provenance.report(test_config, "cloud", show_paths=True)
    local = provenance.report(test_config, "local", show_paths=True)
    assert cloud["paths"] == []
    assert cloud["derivation_deps"] == {"derived": []}
    assert cloud["hidden"] == 2
    assert local["paths"] == ["proof/note.md"]


def test_empty_load_has_no_writes(test_config: VaultConfig, tmp_path: Path) -> None:
    """Missing state means empty state without creating files during a read."""
    prepare(test_config, tmp_path)
    state = provenance.load(test_config)
    assert state.manifest["applied_seq"] == 0
    assert not test_config.librarian.provenance.state_path.exists()


@pytest.mark.parametrize("field", ["sources", "derivations"])
def test_structured_manifest_corruption_rebuilds_from_log(
    test_config: VaultConfig, tmp_path: Path, field: str
) -> None:
    """A valid JSON cache with invalid records cannot override the durable log."""
    prepare(test_config, tmp_path)
    provenance.scan(test_config)
    expected = provenance.load(test_config).manifest
    broken = dict(expected)
    broken[field] = {"broken-record": None}
    manifest = test_config.librarian.provenance.state_path / "manifest.json"
    manifest.write_text(json.dumps(broken), encoding="utf-8")
    assert provenance.load(test_config).manifest == expected


@pytest.mark.parametrize(
    ("kind", "detail", "at"),
    [
        ("source_discovered", {}, "2026-10-21T00:00:00+00:00"),
        ("source_deleted", {"version": True}, "2026-10-21T00:00:00+00:00"),
        ("derivation_proposed", {"deps": {}, "note": ""}, "2026-10-21T00:00:00+00:00"),
        ("derivation_stale", {"reason": [], "source": "x"}, "2026-10-21T00:00:00+00:00"),
        ("derivation_accepted", {}, "bad-time"),
        ("derivation_accepted", {}, "2026-10-21T00:00:00"),
    ],
)
def test_invalid_event_details_preserve_log_and_raise_typed_error(
    test_config: VaultConfig, tmp_path: Path, kind: str, detail: object, at: str
) -> None:
    """Malformed event fields never crash replay or discard the durable record."""
    prepare(test_config, tmp_path)
    state = test_config.librarian.provenance.state_path
    state.mkdir()
    log = state / "transitions.jsonl"
    log.write_text(
        json.dumps({"seq": 1, "kind": kind, "subject": "x", "detail": detail, "at": at}) + "\n",
        encoding="utf-8",
    )
    before = log.read_bytes()
    with pytest.raises(provenance.ProvenanceError):
        provenance.load(test_config)
    assert log.read_bytes() == before
