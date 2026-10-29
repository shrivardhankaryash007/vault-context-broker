"""Deterministic source provenance and derivation freshness ledger."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast

from vault_context_mcp.config import VaultConfig
from vault_context_mcp.provenance_schema import ProvenanceError as ProvenanceError
from vault_context_mcp.provenance_schema import _is_valid_manifest, _validate_log_entry
from vault_context_mcp.sensitivity import load_sensitivity_map, note_sensitivity


@dataclass
class State:
    """Loaded provenance manifest and transition log."""

    # JSON manifests and transition records hold heterogeneous values.
    manifest: dict[str, Any]
    transitions: list[dict[str, Any]]


@dataclass(frozen=True)
class ScanResult:
    """Counts of source and derivation changes during a scan."""

    discovered: int = 0
    changed: int = 0
    deleted: int = 0
    restored: int = 0
    invalidated: int = 0
    unchanged: int = 0


def _empty() -> dict[str, Any]:
    return {"schema_version": 1, "applied_seq": 0, "sources": {}, "derivations": {}}


def apply(manifest: dict[str, Any], transition: dict[str, Any]) -> dict[str, Any]:
    """Apply one transition to a copied manifest."""
    result: dict[str, Any] = cast(dict[str, Any], json.loads(json.dumps(manifest)))
    kind, subject, detail = transition["kind"], transition["subject"], transition["detail"]
    sources, derivations = result["sources"], result["derivations"]
    if kind in {"source_discovered", "source_changed", "source_restored"}:
        sources[subject] = {**detail, "state": "present"}
    elif kind == "source_deleted":
        if subject not in sources:
            raise ProvenanceError(f"log corrupt at seq {transition['seq']}")
        previous = sources.get(subject, {})
        sources[subject] = {**previous, "version": detail["version"], "state": "deleted"}
    elif kind == "derivation_proposed":
        derivations[subject] = {"state": "proposed", **detail}
    elif kind.startswith("derivation_"):
        if subject not in derivations:
            raise ProvenanceError(f"log corrupt at seq {transition['seq']}")
        derivations[subject]["state"] = kind.removeprefix("derivation_")
    result["applied_seq"] = transition["seq"]
    return result


def _check_state_path(config: VaultConfig) -> Path:
    """Reject state placement inside the read-only vault before any mutation."""
    path = config.librarian.provenance.state_path
    if path.resolve().is_relative_to(config.vault_root_path.resolve()):
        raise ProvenanceError("provenance state must be outside the vault")
    return path


def _atomic_manifest(state_path: Path, manifest: dict[str, Any]) -> None:
    state_path.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix="manifest.", suffix=".tmp", dir=state_path)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(manifest, stream, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, state_path / "manifest.json")
    finally:
        if os.path.exists(name):
            os.unlink(name)


def _commit(state: State, transitions: list[dict[str, Any]], state_path: Path) -> None:
    if not transitions:
        return
    state_path.mkdir(parents=True, exist_ok=True)
    log = state_path / "transitions.jsonl"
    for offset, item in enumerate(transitions, start=len(state.transitions) + 1):
        item["seq"] = offset
    with log.open("a", encoding="utf-8") as stream:
        for item in transitions:
            stream.write(json.dumps(item, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    for item in transitions:
        state.manifest = apply(state.manifest, item)
        state.transitions.append(item)
    _atomic_manifest(state_path, state.manifest)


def load(config: VaultConfig) -> State:
    """Load state, repair a torn tail, and replay committed log entries."""
    path = _check_state_path(config)
    log = path / "transitions.jsonl"
    manifest_path = path / "manifest.json"
    if not log.exists() and not manifest_path.exists():
        return State(_empty(), [])
    raw = log.read_bytes() if log.exists() else b""
    lines = raw.splitlines(keepends=True)
    transitions: list[dict[str, Any]] = []
    good_end = 0
    expected = 1
    for index, line in enumerate(lines):
        try:
            item = json.loads(line)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            if index == len(lines) - 1:
                with log.open("r+b") as stream:
                    stream.truncate(good_end)
                break
            raise ProvenanceError(f"log corrupt at seq {expected}") from exc
        _validate_log_entry(item, expected)
        transitions.append(cast(dict[str, Any], item))
        expected += 1
        good_end += len(line)
    rebuild_from_log = False
    manifest: dict[str, Any] = _empty()
    applied_seq = 0
    if manifest_path.exists():
        try:
            loaded_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if not _is_valid_manifest(loaded_manifest):
                rebuild_from_log = True
            else:
                manifest = cast(dict[str, Any], loaded_manifest)
                applied_seq = cast(int, manifest["applied_seq"])
        except (OSError, ValueError):
            rebuild_from_log = True
    elif transitions:
        rebuild_from_log = True
    if manifest_path.exists() and rebuild_from_log and not log.exists():
        raise ProvenanceError("invalid manifest and no transition log available")
    if applied_seq > len(transitions):
        raise ProvenanceError("applied_seq greater than last log seq")
    for item in transitions[applied_seq:]:
        manifest = apply(manifest, item)
    if transitions and (applied_seq < len(transitions) or rebuild_from_log):
        _atomic_manifest(path, manifest)
    return State(manifest, transitions)


def _next(state: State, kind: str, subject: str, detail: dict[str, Any]) -> dict[str, Any]:
    return {
        "seq": len(state.transitions) + 1,
        "kind": kind,
        "subject": subject,
        "detail": detail,
        "at": datetime.now(UTC).isoformat(),
    }


def scan(config: VaultConfig) -> ScanResult:
    """Hash scoped Markdown sources and record lifecycle and stale transitions."""
    state = load(config)
    sources = state.manifest["sources"]
    found: dict[str, tuple[str, int]] = {}
    root = config.vault_root_path.resolve()
    for scope in config.librarian.provenance.scope:
        norm_scope = Path(scope)
        if norm_scope.is_absolute() or any(part == ".." for part in norm_scope.parts):
            raise ProvenanceError(f"invalid provenance scope: {scope}")
        curr = root
        for part in norm_scope.parts:
            curr = curr / part
            if curr.is_symlink():
                raise ProvenanceError(f"symlinks not allowed in provenance scope: {scope}")
        candidate = root / scope
        try:
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(root)
        except (OSError, ValueError) as exc:
            raise ProvenanceError(f"invalid provenance scope: {scope}") from exc
        if not resolved.is_dir():
            raise ProvenanceError(f"invalid provenance scope: {scope}")
        for path in sorted(resolved.rglob("*.md")):
            relative_parts = path.relative_to(root).parts
            if any(part.startswith(".") for part in relative_parts) or path.is_symlink():
                continue
            if not path.is_file():
                continue
            data = path.read_bytes()
            rel = path.relative_to(root).as_posix()
            found[rel] = (hashlib.sha256(data).hexdigest(), len(data))
    events: list[dict[str, Any]] = []
    counts: dict[str, int] = dict.fromkeys(
        ("discovered", "changed", "deleted", "restored", "invalidated", "unchanged"), 0
    )
    for rel in sorted(found):
        digest, size = found[rel]
        previous = sources.get(rel)
        if previous is None:
            kind, version = "source_discovered", 1
            counts["discovered"] += 1
        elif previous["state"] == "deleted":
            kind, version = "source_restored", previous["version"] + 1
            counts["restored"] += 1
        elif previous["sha256"] != digest:
            kind, version = "source_changed", previous["version"] + 1
            counts["changed"] += 1
        else:
            counts["unchanged"] += 1
            continue
        events.append(_next(state, kind, rel, {"sha256": digest, "size": size, "version": version}))
    for rel, previous in sorted(sources.items()):
        if previous["state"] == "present" and rel not in found:
            counts["deleted"] += 1
            events.append(_next(state, "source_deleted", rel, {"version": previous["version"]}))
    projected = state.manifest
    for event in events:
        projected = apply(projected, event)
    for derivation_id, record in sorted(projected["derivations"].items()):
        if record["state"] not in {"proposed", "accepted"}:
            continue
        for rel, version in sorted(record["deps"].items()):
            source = projected["sources"].get(rel)
            if source is None or source["state"] == "deleted":
                reason = "deleted"
            elif source["version"] != version:
                reason = "changed"
            else:
                continue
            events.append(
                _next(state, "derivation_stale", derivation_id, {"reason": reason, "source": rel})
            )
            projected = apply(projected, events[-1])
            counts["invalidated"] += 1
            break
    _commit(state, events, config.librarian.provenance.state_path)
    return ScanResult(**counts)


def propose(config: VaultConfig, derivation_id: str, deps: list[str], note: str = "") -> None:
    """Record a derivation proposal against current source versions."""
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,79}", derivation_id) or not deps:
        raise ProvenanceError("invalid derivation id or empty dependencies")
    state = load(config)
    sources = state.manifest["sources"]
    versions: dict[str, int] = {}
    for rel in sorted(set(deps)):
        source = sources.get(rel)
        if source is None or source["state"] != "present":
            raise ProvenanceError(f"dependency is not present: {rel}")
        versions[rel] = source["version"]
    old = state.manifest["derivations"].get(derivation_id)
    if old and old["state"] == "proposed" and old["deps"] == versions:
        return
    if old and old["state"] != "stale":
        raise ProvenanceError(f"derivation already exists: {derivation_id}")
    event = _next(state, "derivation_proposed", derivation_id, {"deps": versions, "note": note})
    _commit(state, [event], config.librarian.provenance.state_path)


def review(config: VaultConfig, derivation_id: str, accept: bool) -> None:
    """Accept or reject a proposed derivation record."""
    state = load(config)
    current = state.manifest["derivations"].get(derivation_id, {}).get("state")
    target = "accepted" if accept else "rejected"
    if current == target:
        return
    if current != "proposed":
        raise ProvenanceError(f"derivation is not proposed: {derivation_id}")
    _commit(
        state,
        [_next(state, f"derivation_{target}", derivation_id, {})],
        config.librarian.provenance.state_path,
    )


def trace(config: VaultConfig, subject: str) -> list[dict[str, Any]]:
    """Return source or derivation transitions in sequence order."""
    state = load(config)
    return [
        item
        for item in state.transitions
        if item["subject"] == subject
        or (item["kind"] == "derivation_stale" and item["detail"].get("source") == subject)
    ]


def report(
    config: VaultConfig, clearance: Literal["cloud", "local"], show_paths: bool = False
) -> dict[str, Any]:
    """Summarize provenance counts and optionally clearance-filtered paths."""
    state = load(config)
    sources, derivations = state.manifest["sources"], state.manifest["derivations"]
    result: dict[str, Any] = {
        "sources": {
            key: sum(item["state"] == key for item in sources.values())
            for key in ("present", "deleted")
        },
        "derivations": {
            key: sum(item["state"] == key for item in derivations.values())
            for key in ("proposed", "accepted", "rejected", "stale")
        },
        "applied_seq": state.manifest["applied_seq"],
        "hidden": 0,
    }
    if not show_paths:
        return result
    rules = load_sensitivity_map(config.sensitivity_map_file_path) if clearance == "cloud" else []
    hidden = 0

    def visible(rel: str) -> bool:
        nonlocal hidden
        if clearance == "local" or note_sensitivity(config.vault_root_path, rel, rules) == "open":
            return True
        hidden += 1
        return False

    result["paths"] = [rel for rel in sorted(sources) if visible(rel)]
    result["derivation_deps"] = {
        ident: [rel for rel in sorted(record["deps"]) if visible(rel)]
        for ident, record in sorted(derivations.items())
    }
    result["hidden"] = hidden
    return result
