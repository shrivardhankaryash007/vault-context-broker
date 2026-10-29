"""Versioned, local-only contracts for cognitive records.

The broker owns these records so Cosmos, Command Centre, and future clients can
share a provenance-bearing loop without receiving raw vault text or write
authority.  This module defines a contract only; it performs no I/O.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator, model_validator

SchemaVersion = Literal["cognitive-record-v0"]
RecordAuthor = Literal["owner", "deterministic", "model", "external_agent", "trusted_local_adapter"]
Sensitivity = Literal["open", "restricted", "mirror_sealed"]
ReleaseClass = Literal[
    "local_only",
    "approval_required_derived",
    "frontier_eligible",
    "frontier_forbidden",
]
RelationKind = Literal[
    "derived_from",
    "supported_by",
    "contradicted_by",
    "generated_by",
    "attributed_to",
    "responds_to",
    "implements",
    "observes",
    "evaluates",
    "supersedes",
]

_RECORD_ID = re.compile(
    r"^cognitive:[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class ContractModel(BaseModel):
    """Base for strict wire-contract models."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class Relation(ContractModel):
    """A typed relation to another opaque cognitive record."""

    kind: RelationKind
    target_id: str

    @field_validator("target_id")
    @classmethod
    def require_opaque_record_id(cls, value: str) -> str:
        """Reject locators and require a namespaced UUIDv7 record identifier."""
        if not _RECORD_ID.fullmatch(value):
            raise ValueError("target_id must be an opaque cognitive UUIDv7 identifier")
        return value


class EvidencePointer(ContractModel):
    """Content-free provenance for a local or external source snapshot."""

    source_alias: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    integrity_sha256: str

    @field_validator("integrity_sha256")
    @classmethod
    def require_sha256(cls, value: str) -> str:
        """Require a stable hash instead of a source path or embedded source text."""
        if not _SHA256.fullmatch(value):
            raise ValueError("integrity_sha256 must be a lowercase SHA-256 digest")
        return value


class RecordBase(ContractModel):
    """Common provenance and disclosure fields for every immutable record."""

    schema_version: SchemaVersion = "cognitive-record-v0"
    record_id: str
    created_at: datetime
    author: RecordAuthor
    sensitivity: Sensitivity
    release_class: ReleaseClass
    relations: tuple[Relation, ...] = ()

    @field_validator("record_id")
    @classmethod
    def require_uuidv7_id(cls, value: str) -> str:
        """Require an opaque namespaced UUIDv7 and reject source-derived IDs."""
        if not _RECORD_ID.fullmatch(value):
            raise ValueError("record_id must be a namespaced UUIDv7 identifier")
        return value

    @model_validator(mode="after")
    def enforce_mirror_seal(self) -> RecordBase:
        """Keep Mirror-derived records permanently ineligible for frontier release."""
        if self.sensitivity == "mirror_sealed" and self.release_class != "frontier_forbidden":
            raise ValueError("mirror_sealed records must use frontier_forbidden release_class")
        return self


class EvidenceRecord(RecordBase):
    """A provenance-bearing source snapshot or owner observation."""

    kind: Literal["evidence"]
    author: Literal["owner", "deterministic", "external_agent", "trusted_local_adapter"]
    evidence: EvidencePointer


class FactRecord(RecordBase):
    """A proposition whose named verification method has passed."""

    kind: Literal["fact"]
    author: Literal["owner", "deterministic"]
    claim: str = Field(min_length=1, max_length=500)
    verification_method: str = Field(min_length=1, max_length=120)


class InterpretationRecord(RecordBase):
    """A revisable meaning assigned to evidence."""

    kind: Literal["interpretation"]
    author: Literal["owner", "model"]
    claim: str = Field(min_length=1, max_length=500)
    alternatives: tuple[str, ...] = Field(min_length=1, max_length=5)


class HypothesisRecord(RecordBase):
    """A falsifiable proposition awaiting observation."""

    kind: Literal["hypothesis"]
    author: Literal["owner", "model"]
    claim: str = Field(min_length=1, max_length=500)
    falsifiers: tuple[str, ...] = Field(min_length=1, max_length=5)
    observation_ends_at: datetime


class RecommendationRecord(RecordBase):
    """A bounded proposal with explicit uncertainty and counterevidence."""

    kind: Literal["recommendation"]
    author: Literal["owner", "model"]
    question_or_decision: str = Field(min_length=1, max_length=500)
    evidence_refs: tuple[str, ...] = Field(min_length=1, max_length=10)
    counterevidence_refs: tuple[str, ...] = Field(default=(), max_length=10)
    rationale: str = Field(min_length=1, max_length=1_000)
    uncertainty: str = Field(min_length=1, max_length=500)
    alternatives: tuple[str, ...] = Field(min_length=1, max_length=5)
    risks: tuple[str, ...] = Field(min_length=1, max_length=5)
    falsifiers: tuple[str, ...] = Field(min_length=1, max_length=5)
    validity_ends_at: datetime

    @field_validator("evidence_refs", "counterevidence_refs")
    @classmethod
    def require_evidence_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        """Ensure evidence is linked by record identity, not duplicated source content."""
        if any(not _RECORD_ID.fullmatch(value) for value in values):
            raise ValueError("evidence references must be opaque cognitive UUIDv7 identifiers")
        return values


class DecisionRecord(RecordBase):
    """An owner-only choice, including deliberate no-action."""

    kind: Literal["decision"]
    author: Literal["owner"]
    chosen_alternative: str = Field(min_length=1, max_length=500)


class ActionRecord(RecordBase):
    """A bounded operational action with explicit authority and state."""

    kind: Literal["action"]
    author: Literal["owner", "trusted_local_adapter"]
    state: Literal["scheduled", "started", "completed", "cancelled", "failed"]
    authority: Literal["owner", "command_centre"]


class ObservedOutcomeRecord(RecordBase):
    """A separately recorded observation, never a model-created result."""

    kind: Literal["observed_outcome"]
    author: Literal["owner", "trusted_local_adapter"]
    observation: str = Field(min_length=1, max_length=500)
    observed_at: datetime


class CorrectionRecord(RecordBase):
    """An owner-accepted correction to an earlier cognitive record."""

    kind: Literal["correction"]
    author: Literal["owner"]
    reason: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def require_correction_links(self) -> CorrectionRecord:
        """Require both the superseded record and supporting evidence/outcome relation."""
        relation_kinds = {relation.kind for relation in self.relations}
        if "supersedes" not in relation_kinds or "supported_by" not in relation_kinds:
            raise ValueError("correction requires supersedes and supported_by relations")
        return self


CognitiveRecord = Annotated[
    EvidenceRecord
    | FactRecord
    | InterpretationRecord
    | HypothesisRecord
    | RecommendationRecord
    | DecisionRecord
    | ActionRecord
    | ObservedOutcomeRecord
    | CorrectionRecord,
    Field(discriminator="kind"),
]


class CognitiveLoop(ContractModel):
    """A content-free closed loop that future consumers can project independently."""

    records: tuple[CognitiveRecord, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_relations(self) -> CognitiveLoop:
        """Reject duplicate identities and correction support that does not exist in the loop."""
        records_by_id = {record.record_id: record for record in self.records}
        if len(records_by_id) != len(self.records):
            raise ValueError("record_id values must be unique")
        for record in self.records:
            for relation in record.relations:
                if relation.target_id not in records_by_id:
                    raise ValueError(f"relation target does not exist: {relation.target_id}")
            if isinstance(record, CorrectionRecord):
                support_ids = [
                    relation.target_id
                    for relation in record.relations
                    if relation.kind == "supported_by"
                ]
                if not any(
                    isinstance(records_by_id[support_id], (EvidenceRecord, ObservedOutcomeRecord))
                    for support_id in support_ids
                ):
                    raise ValueError(
                        "correction support must reference evidence or an observed_outcome"
                    )
        return self


def validate_cognitive_loop(value: object) -> CognitiveLoop:
    """Validate one cognitive loop without performing storage, retrieval, or transport.

    Args:
        value: JSON-compatible payload to validate.

    Returns:
        The immutable, validated cognitive loop.

    Raises:
        pydantic.ValidationError: If the payload violates the v0 contract.
    """
    return TypeAdapter(CognitiveLoop).validate_python(value)


def cognitive_loop_json_schema() -> dict[str, object]:
    """Return the portable JSON Schema for the v0 loop contract.

    Returns:
        A JSON Schema Draft 2020-12-compatible mapping generated from the strict models.
    """
    return CognitiveLoop.model_json_schema()
