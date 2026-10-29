"""Pure validation of provenance log events and rebuildable manifest caches."""

from __future__ import annotations

from datetime import datetime, timedelta

KNOWN_KINDS = frozenset(
    {
        "source_discovered",
        "source_changed",
        "source_deleted",
        "source_restored",
        "derivation_proposed",
        "derivation_accepted",
        "derivation_rejected",
        "derivation_stale",
    }
)


class ProvenanceError(RuntimeError):
    """Raised when provenance state or a requested operation is invalid."""


def _is_strict_int(val: object, minimum: int = 0) -> bool:
    """Exclude booleans when validating numeric JSON fields."""
    return type(val) is int and val >= minimum


def _validate_log_entry(item: object, expected_seq: int) -> None:
    """Reject malformed structured records without discarding durable history."""
    error = ProvenanceError(f"log corrupt at seq {expected_seq}")
    if not isinstance(item, dict):
        raise error
    seq, kind, detail = item.get("seq"), item.get("kind"), item.get("detail")
    if (
        not _is_strict_int(seq, 1)
        or seq != expected_seq
        or not isinstance(kind, str)
        or kind not in KNOWN_KINDS
        or not isinstance(item.get("subject"), str)
        or not isinstance(detail, dict)
        or not isinstance(item.get("at"), str)
    ):
        raise error
    try:
        timestamp = datetime.fromisoformat(item["at"])
        if timestamp.utcoffset() != timedelta(0):
            raise error
    except ValueError as exc:
        raise error from exc
    valid = True
    if kind in {"source_discovered", "source_changed", "source_restored"}:
        valid = (
            isinstance(detail.get("sha256"), str)
            and _is_strict_int(detail.get("size"))
            and _is_strict_int(detail.get("version"), 1)
        )
    elif kind == "source_deleted":
        valid = _is_strict_int(detail.get("version"), 1)
    elif kind == "derivation_proposed":
        deps = detail.get("deps")
        valid = (
            isinstance(deps, dict)
            and bool(deps)
            and isinstance(detail.get("note"), str)
            and all(isinstance(k, str) and _is_strict_int(v, 1) for k, v in deps.items())
        )
    elif kind == "derivation_stale":
        valid = detail.get("reason") in ("changed", "deleted") and isinstance(
            detail.get("source"), str
        )
    if not valid:
        raise error


def _is_valid_manifest(value: object) -> bool:
    """Treat malformed cache records as rebuildable from the authoritative log."""
    if (
        not isinstance(value, dict)
        or value.get("schema_version") != 1
        or not _is_strict_int(value.get("applied_seq"))
        or not isinstance(value.get("sources"), dict)
        or not isinstance(value.get("derivations"), dict)
    ):
        return False
    for record in value["sources"].values():
        if (
            not isinstance(record, dict)
            or record.get("state") not in ("present", "deleted")
            or not isinstance(record.get("sha256"), str)
            or not _is_strict_int(record.get("size"))
            or not _is_strict_int(record.get("version"), 1)
        ):
            return False
    for record in value["derivations"].values():
        if (
            not isinstance(record, dict)
            or record.get("state") not in ("proposed", "accepted", "rejected", "stale")
            or not isinstance(record.get("deps"), dict)
            or not isinstance(record.get("note"), str)
            or not all(
                isinstance(k, str) and _is_strict_int(v, 1) for k, v in record["deps"].items()
            )
        ):
            return False
    return True
