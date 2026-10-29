"""Ranker tests."""

from __future__ import annotations

from vault_context_mcp.ranker import score_chunk
from vault_context_mcp.schemas import RetrievedChunk


def test_project_boost_increases_score(test_config) -> None:  # type: ignore[no-untyped-def]
    chunk = RetrievedChunk(
        chunk_id="1",
        path="projects/ATLAS/PROJECT_STATE.md",
        heading="ATLAS Project State",
        text="Current ATLAS architecture state.",
        line_start=1,
        line_end=3,
        score=0,
        metadata={"is_canonical": True, "modified_time": 1},
    )

    score_without_project = score_chunk(chunk, 1.0, test_config, "ATLAS project state")
    score_with_project = score_chunk(
        chunk, 1.0, test_config, "ATLAS project state", project="ATLAS"
    )

    assert score_with_project > score_without_project


def test_raw_path_penalty_lowers_score(test_config) -> None:  # type: ignore[no-untyped-def]
    raw_chunk = RetrievedChunk(
        chunk_id="1",
        path="Main_Vault/40-Thinking/Self-Model/_raw/extract-batch-01.md",
        heading=None,
        text="Raw chat dump content.",
        line_start=1,
        line_end=3,
        score=0,
        metadata={"modified_time": 1},
    )
    non_raw_chunk = raw_chunk.model_copy(
        update={"path": "Main_Vault/40-Thinking/Self-Model/Self-Model-v2026-06.md"}
    )

    raw_score = score_chunk(raw_chunk, 1.0, test_config, "self model")
    non_raw_score = score_chunk(non_raw_chunk, 1.0, test_config, "self model")

    assert raw_score < non_raw_score
    assert non_raw_score - raw_score == test_config.retrieval.raw_penalty
