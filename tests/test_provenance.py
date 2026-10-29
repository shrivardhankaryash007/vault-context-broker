"""Contract tests for provenance tracking and its safety boundaries."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import cast

import pytest
import yaml
from typer.testing import CliRunner

from vault_context_mcp import provenance
from vault_context_mcp.cli import app
from vault_context_mcp.config import VaultConfig, load_config
from vault_context_mcp.librarian import refresh_if_changed


def configure_provenance(config: VaultConfig, state_dir: Path) -> None:
    """Enable provenance for the fixture's ACME directory."""

    config.librarian.provenance.enabled = True
    config.librarian.provenance.scope = ["ACME"]
    config.librarian.provenance.state_dir = str(state_dir)


def write_note(config: VaultConfig, relative_path: str, content: bytes) -> Path:
    """Write a note into the isolated fixture vault."""

    path = config.vault_root_path / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def manifest_path(config: VaultConfig) -> Path:
    """Return the test's isolated provenance manifest path."""

    return config.librarian.provenance.state_path / "manifest.json"


def log_path(config: VaultConfig) -> Path:
    """Return the test's isolated transition log path."""

    return config.librarian.provenance.state_path / "transitions.jsonl"


def read_manifest(config: VaultConfig) -> dict[str, object]:
    """Read the persisted manifest as JSON data."""

    return cast(dict[str, object], json.loads(manifest_path(config).read_text(encoding="utf-8")))


def read_transitions(config: VaultConfig) -> list[dict[str, object]]:
    """Read persisted transition records in order."""

    return [
        cast(dict[str, object], json.loads(line))
        for line in log_path(config).read_text(encoding="utf-8").splitlines()
    ]


def vault_snapshot(root: Path) -> dict[str, tuple[str, int]]:
    """Capture content hashes and timestamps for every regular vault file."""

    snapshot: dict[str, tuple[str, int]] = {}
    for path in root.rglob("*"):
        if path.is_file() and not path.is_symlink():
            snapshot[path.relative_to(root).as_posix()] = (
                hashlib.sha256(path.read_bytes()).hexdigest(),
                path.stat().st_mtime_ns,
            )
    return snapshot


def test_scan_discovers_scoped_notes_and_is_idempotent(
    test_config: VaultConfig, tmp_path: Path
) -> None:
    """Scanning skips hidden entries and leaves state untouched on a no-op."""

    configure_provenance(test_config, tmp_path / "prov")
    hidden_dir = test_config.vault_root_path / "ACME" / ".private"
    hidden_dir.mkdir()
    (hidden_dir / "hidden.md").write_text("hidden", encoding="utf-8")
    visible = write_note(test_config, "ACME/visible.md", b"visible")
    link = test_config.vault_root_path / "ACME" / "linked.md"
    try:
        link.symlink_to(visible)
    except (OSError, NotImplementedError):
        link = Path()

    first = provenance.scan(test_config)
    manifest_before = manifest_path(test_config).stat().st_mtime_ns
    log_lines_before = len(read_transitions(test_config))
    assert first.discovered >= 2
    assert "ACME/visible.md" in cast(dict[str, object], read_manifest(test_config)["sources"])
    assert "ACME/.private/hidden.md" not in cast(
        dict[str, object], read_manifest(test_config)["sources"]
    )
    if link != Path():
        assert "ACME/linked.md" not in cast(
            dict[str, object], read_manifest(test_config)["sources"]
        )

    second = provenance.scan(test_config)

    assert second.discovered == 0
    assert second.changed == 0
    assert second.deleted == 0
    assert second.restored == 0
    assert second.invalidated == 0
    assert second.unchanged >= 1
    assert len(read_transitions(test_config)) == log_lines_before
    assert manifest_path(test_config).stat().st_mtime_ns == manifest_before


def test_scan_tracks_change_delete_and_restore_versions(
    test_config: VaultConfig, tmp_path: Path
) -> None:
    """Source versions advance on edits and restoration."""

    configure_provenance(test_config, tmp_path / "prov")
    note = write_note(test_config, "ACME/lifecycle.md", b"one")
    provenance.scan(test_config)
    note.write_bytes(b"two")
    changed = provenance.scan(test_config)
    note.unlink()
    deleted = provenance.scan(test_config)
    note.write_bytes(b"two")
    restored = provenance.scan(test_config)

    sources = cast(dict[str, dict[str, object]], read_manifest(test_config)["sources"])
    assert changed.changed == 1
    assert deleted.deleted == 1
    assert restored.restored == 1
    assert sources["ACME/lifecycle.md"]["version"] == 3
    assert sources["ACME/lifecycle.md"]["state"] == "present"


def test_provenance_operations_do_not_write_vault_files(
    test_config: VaultConfig, tmp_path: Path
) -> None:
    """Scan and record operations change only the external provenance state."""

    configure_provenance(test_config, tmp_path / "prov")
    write_note(test_config, "ACME/untouched.md", b"unchanged bytes")
    before = vault_snapshot(test_config.vault_root_path)
    provenance.scan(test_config)
    provenance.propose(test_config, "safe-record", ["ACME/untouched.md"])
    provenance.review(test_config, "safe-record", accept=True)
    provenance.report(test_config, clearance="local", show_paths=True)

    assert vault_snapshot(test_config.vault_root_path) == before


def test_scan_invalidates_changed_and_deleted_dependencies_but_not_rejected(
    test_config: VaultConfig, tmp_path: Path
) -> None:
    """Active derivations become stale while rejected records remain unchanged."""

    configure_provenance(test_config, tmp_path / "prov")
    changed_note = write_note(test_config, "ACME/changed.md", b"before")
    deleted_note = write_note(test_config, "ACME/deleted.md", b"before")
    rejected_note = write_note(test_config, "ACME/rejected.md", b"before")
    provenance.scan(test_config)
    for derivation_id, relative in (
        ("changed-record", "ACME/changed.md"),
        ("deleted-record", "ACME/deleted.md"),
        ("rejected-record", "ACME/rejected.md"),
    ):
        provenance.propose(test_config, derivation_id, [relative])
    provenance.review(test_config, "changed-record", accept=True)
    provenance.review(test_config, "deleted-record", accept=True)
    provenance.review(test_config, "rejected-record", accept=False)
    changed_note.write_bytes(b"after")
    deleted_note.unlink()

    result = provenance.scan(test_config)

    derivations = cast(dict[str, dict[str, object]], read_manifest(test_config)["derivations"])
    stale = [
        transition
        for transition in read_transitions(test_config)
        if transition["kind"] == "derivation_stale"
    ]
    details = {cast(dict[str, object], item["detail"])["source"]: item for item in stale}
    assert result.invalidated == 2
    assert derivations["changed-record"]["state"] == "stale"
    assert derivations["deleted-record"]["state"] == "stale"
    assert derivations["rejected-record"]["state"] == "rejected"
    assert cast(dict[str, object], details["ACME/changed.md"]["detail"])["reason"] == "changed"
    assert cast(dict[str, object], details["ACME/deleted.md"]["detail"])["reason"] == "deleted"
    assert rejected_note.exists()


def test_propose_and_review_idempotence_conflicts_and_validation(
    test_config: VaultConfig, tmp_path: Path
) -> None:
    """Derivation operations reject invalid requests and avoid duplicate log entries."""

    configure_provenance(test_config, tmp_path / "prov")
    note = write_note(test_config, "ACME/dep.md", b"v1")
    provenance.scan(test_config)
    provenance.propose(test_config, "repeatable", ["ACME/dep.md"], note="review me")
    first_count = len(read_transitions(test_config))
    provenance.propose(test_config, "repeatable", ["ACME/dep.md"], note="review me")
    provenance.review(test_config, "repeatable", accept=True)
    accepted_count = len(read_transitions(test_config))
    provenance.review(test_config, "repeatable", accept=True)
    assert len(read_transitions(test_config)) == accepted_count
    assert accepted_count == first_count + 1
    with pytest.raises(provenance.ProvenanceError):
        provenance.propose(test_config, "repeatable", ["ACME/other.md"])
    with pytest.raises(provenance.ProvenanceError):
        provenance.propose(test_config, "Bad ID", ["ACME/dep.md"])
    with pytest.raises(provenance.ProvenanceError):
        provenance.propose(test_config, "empty-deps", [])
    with pytest.raises(provenance.ProvenanceError):
        provenance.propose(test_config, "missing-dep", ["ACME/missing.md"])

    note.write_bytes(b"v2")
    provenance.scan(test_config)
    provenance.propose(test_config, "repeatable", ["ACME/dep.md"], note="updated")
    derivations = cast(dict[str, dict[str, object]], read_manifest(test_config)["derivations"])
    assert derivations["repeatable"]["state"] == "proposed"
    assert derivations["repeatable"]["deps"] == {"ACME/dep.md": 2}


def test_trace_includes_source_and_derivation_history(
    test_config: VaultConfig, tmp_path: Path
) -> None:
    """Trace returns matching transition records in sequence order."""

    configure_provenance(test_config, tmp_path / "prov")
    note = write_note(test_config, "ACME/traced.md", b"v1")
    provenance.scan(test_config)
    provenance.propose(test_config, "trace-record", ["ACME/traced.md"])
    provenance.review(test_config, "trace-record", accept=True)
    note.write_bytes(b"v2")
    provenance.scan(test_config)

    source_trace = provenance.trace(test_config, "ACME/traced.md")
    derivation_trace = provenance.trace(test_config, "trace-record")
    source_kinds = [item["kind"] for item in source_trace]
    assert source_kinds[0] == "source_discovered"
    assert "source_changed" in source_kinds
    stale_trace = next(item for item in source_trace if item["kind"] == "derivation_stale")
    assert cast(dict[str, object], stale_trace["detail"])["source"] == "ACME/traced.md"
    assert [item["kind"] for item in derivation_trace] == [
        "derivation_proposed",
        "derivation_accepted",
        "derivation_stale",
    ]


def test_manifest_is_replayable_from_transition_log(
    test_config: VaultConfig, tmp_path: Path
) -> None:
    """Applying every persisted transition reconstructs the stored manifest."""

    configure_provenance(test_config, tmp_path / "prov")
    note = write_note(test_config, "ACME/replay.md", b"first")
    provenance.scan(test_config)
    provenance.propose(test_config, "replay-record", ["ACME/replay.md"], note="record")
    provenance.review(test_config, "replay-record", accept=True)
    note.write_bytes(b"second")
    provenance.scan(test_config)
    replayed: dict[str, object] = {
        "schema_version": 1,
        "applied_seq": 0,
        "sources": {},
        "derivations": {},
    }
    for transition in read_transitions(test_config):
        replayed = provenance.apply(replayed, transition)

    assert replayed == read_manifest(test_config)


def test_load_repairs_manifest_after_interrupted_commit(
    test_config: VaultConfig, tmp_path: Path
) -> None:
    """Load replays log entries when the manifest reflects an earlier commit."""

    configure_provenance(test_config, tmp_path / "prov")
    note = write_note(test_config, "ACME/crash.md", b"first")
    provenance.scan(test_config)
    previous_manifest = manifest_path(test_config).read_bytes()
    note.write_bytes(b"second")
    provenance.scan(test_config)
    expected = read_manifest(test_config)
    lines_before = len(read_transitions(test_config))
    manifest_path(test_config).write_bytes(previous_manifest)

    provenance.load(test_config)
    following_scan = provenance.scan(test_config)

    assert read_manifest(test_config) == expected
    assert following_scan.changed == 0
    assert len(read_transitions(test_config)) == lines_before


def test_load_repairs_torn_tail_and_rejects_corrupt_log(
    test_config: VaultConfig, tmp_path: Path
) -> None:
    """Only a malformed final log record is treated as a recoverable torn write."""

    configure_provenance(test_config, tmp_path / "prov")
    write_note(test_config, "ACME/log.md", b"one")
    provenance.scan(test_config)
    provenance.propose(test_config, "log-record", ["ACME/log.md"])
    log = log_path(test_config)
    good_bytes = log.read_bytes()
    with log.open("ab") as stream:
        stream.write(b'{"seq":')
    provenance.load(test_config)
    assert log.read_bytes() == good_bytes
    (test_config.librarian.provenance.state_path / "manifest.json.tmp").write_text(
        "irrelevant", encoding="utf-8"
    )
    provenance.load(test_config)

    lines = good_bytes.splitlines()
    lines[0] = b"{broken"
    log.write_bytes(b"\n".join(lines) + b"\n")
    with pytest.raises(provenance.ProvenanceError, match="log corrupt at seq"):
        provenance.load(test_config)

    transitions = [cast(dict[str, object], json.loads(line)) for line in good_bytes.splitlines()]
    transitions[1]["seq"] = 4
    log.write_text("".join(json.dumps(item) + "\n" for item in transitions), encoding="utf-8")
    with pytest.raises(provenance.ProvenanceError, match="log corrupt at seq"):
        provenance.load(test_config)


def test_report_filters_restricted_paths_for_cloud_clearance(
    test_config: VaultConfig, tmp_path: Path
) -> None:
    """Cloud reports hide restricted paths and deps while counts stay complete."""

    configure_provenance(test_config, tmp_path / "prov")
    restricted = write_note(test_config, "ACME/Private/hidden.md", b"hidden")
    open_note = write_note(test_config, "ACME/public.md", b"open")
    sensitivity_map = tmp_path / "sensitivity.yaml"
    sensitivity_map.write_text(
        "path_rules:\n  - pattern: 'ACME/Private/**'\n    sensitivity: restricted\n",
        encoding="utf-8",
    )
    test_config.sensitivity_map_path = str(sensitivity_map)
    provenance.scan(test_config)
    provenance.propose(test_config, "reported", ["ACME/Private/hidden.md"])

    cloud = provenance.report(test_config, clearance="cloud", show_paths=True)
    local = provenance.report(test_config, clearance="local", show_paths=True)

    assert cloud["sources"] == local["sources"]
    assert cloud["derivations"] == local["derivations"]
    assert "ACME/Private/hidden.md" not in cloud["paths"]
    assert "ACME/Private/hidden.md" not in cloud["derivation_deps"]["reported"]
    assert cloud["hidden"] >= 2
    assert "ACME/Private/hidden.md" in local["paths"]
    assert "ACME/Private/hidden.md" in local["derivation_deps"]["reported"]
    assert local["hidden"] == 0
    assert "ACME/public.md" in cloud["paths"]
    assert restricted.exists() and open_note.exists()


def test_scan_rejects_escaping_and_missing_scope(test_config: VaultConfig, tmp_path: Path) -> None:
    """Scopes must name existing directories contained by the vault root."""

    configure_provenance(test_config, tmp_path / "prov")
    test_config.librarian.provenance.scope = ["../outside"]
    with pytest.raises(provenance.ProvenanceError):
        provenance.scan(test_config)
    test_config.librarian.provenance.scope = ["not-present"]
    with pytest.raises(provenance.ProvenanceError):
        provenance.scan(test_config)


def test_librarian_refresh_scans_only_when_provenance_enabled(
    test_config: VaultConfig, tmp_path: Path
) -> None:
    """A changed refresh creates provenance state only when explicitly enabled."""

    enabled_state = tmp_path / "enabled-provenance"
    configure_provenance(test_config, enabled_state)
    refresh_if_changed(test_config)
    assert manifest_path(test_config).exists()
    assert log_path(test_config).exists()

    disabled_state = tmp_path / "disabled-provenance"
    test_config.librarian.provenance.enabled = False
    test_config.librarian.provenance.state_dir = str(disabled_state)
    refresh_if_changed(test_config, previous_fingerprint="different")
    assert not disabled_state.exists()


def test_provenance_cli_uses_config_and_hides_paths_by_default(
    test_config: VaultConfig, tmp_path: Path
) -> None:
    """CLI commands load isolated YAML config and require explicit path output."""

    configure_provenance(test_config, tmp_path / "prov")
    write_note(test_config, "ACME/cli.md", b"cli")
    config_file = tmp_path / "config.yaml"
    config_file.write_text(yaml.safe_dump(test_config.model_dump()), encoding="utf-8")
    runner = CliRunner()

    scanned = runner.invoke(
        app,
        ["provenance-scan"],
        env={"VAULT_CONTEXT_CONFIG": str(config_file)},
    )
    report = runner.invoke(
        app,
        ["provenance-report"],
        env={"VAULT_CONTEXT_CONFIG": str(config_file), "VAULT_CONTEXT_CLEARANCE": "local"},
    )
    unknown_review = runner.invoke(
        app,
        ["provenance-review", "unknown", "--accept"],
        env={"VAULT_CONTEXT_CONFIG": str(config_file)},
    )

    assert scanned.exit_code == 0
    for count_name in ("discovered", "changed", "deleted", "restored", "invalidated", "unchanged"):
        assert f"{count_name}=" in scanned.output
    assert report.exit_code == 0
    assert str(test_config.vault_root_path) not in report.output
    assert unknown_review.exit_code == 1


def test_old_config_without_provenance_loads_disabled(
    test_config: VaultConfig, tmp_path: Path
) -> None:
    """Configuration files created before provenance retain disabled defaults."""

    data = test_config.model_dump()
    data["librarian"].pop("provenance", None)
    config_file = tmp_path / "old-config.yaml"
    config_file.write_text(yaml.safe_dump(data), encoding="utf-8")

    loaded = load_config(config_file)

    assert loaded.librarian.provenance.enabled is False
