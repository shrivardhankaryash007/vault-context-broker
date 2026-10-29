"""Tests for the local-only cognitive-record contract."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema
import pytest
from pydantic import ValidationError

from vault_context_mcp.cognitive_contracts import (
    CognitiveLoop,
    cognitive_loop_json_schema,
    validate_cognitive_loop,
)

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "cognitive_loop_v0.json"


def load_fixture() -> dict[str, Any]:
    """Load the synthetic, content-free closed-loop fixture."""
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def test_complete_synthetic_loop_validates() -> None:
    """The v0 schema represents the full evidence-to-correction loop."""
    loop = validate_cognitive_loop(load_fixture())

    assert len(loop.records) == 9
    assert [record.kind for record in loop.records] == [
        "evidence",
        "fact",
        "interpretation",
        "hypothesis",
        "recommendation",
        "decision",
        "action",
        "observed_outcome",
        "correction",
    ]


@pytest.mark.parametrize("kind", ["fact", "decision", "action", "observed_outcome", "correction"])
def test_model_cannot_create_authority_bearing_records(kind: str) -> None:
    """Models can propose interpretations, hypotheses, and recommendations only."""
    payload = load_fixture()
    record = next(item for item in payload["records"] if item["kind"] == kind)
    record["author"] = "model"

    with pytest.raises(ValidationError):
        CognitiveLoop.model_validate(payload)


def test_mirror_sealed_record_cannot_be_released() -> None:
    """Mirror material is permanently blocked from every frontier release class."""
    payload = load_fixture()
    payload["records"][0]["sensitivity"] = "mirror_sealed"
    payload["records"][0]["release_class"] = "frontier_eligible"

    with pytest.raises(ValidationError, match="mirror_sealed"):
        CognitiveLoop.model_validate(payload)


@pytest.mark.parametrize("field", ["raw_text", "source_path", "absolute_path"])
def test_raw_content_and_path_fields_are_rejected(field: str) -> None:
    """The contract accepts aliases and hashes, never raw content or vault locators."""
    payload = load_fixture()
    payload["records"][0][field] = "/Users/owner/private-vault/note.md"

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        CognitiveLoop.model_validate(payload)


def test_recommendation_requires_every_decision_field() -> None:
    """A recommendation cannot hide its evidence, uncertainty, risks, or falsifiers."""
    payload = load_fixture()
    recommendation = next(item for item in payload["records"] if item["kind"] == "recommendation")
    del recommendation["falsifiers"]

    with pytest.raises(ValidationError):
        CognitiveLoop.model_validate(payload)


def test_correction_requires_supersedes_and_observed_support() -> None:
    """Corrections remain linked to both the replaced record and observed support."""
    payload = load_fixture()
    correction = next(item for item in payload["records"] if item["kind"] == "correction")
    correction["relations"] = [correction["relations"][0]]

    with pytest.raises(ValidationError, match="correction requires"):
        CognitiveLoop.model_validate(payload)


def test_exported_json_schema_validates_fixture_without_pydantic() -> None:
    """The portable JSON Schema independently validates the synthetic loop fixture."""
    jsonschema.Draft202012Validator(cognitive_loop_json_schema()).validate(load_fixture())


def test_unknown_relation_target_is_rejected() -> None:
    """Consumers cannot create dangling provenance edges."""
    payload = load_fixture()
    payload["records"][1]["relations"][0]["target_id"] = (
        "cognitive:019f577e-048a-7000-8000-000000000099"
    )

    with pytest.raises(ValidationError, match="relation target does not exist"):
        CognitiveLoop.model_validate(payload)
