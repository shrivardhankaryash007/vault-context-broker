"""Deterministic ranking policy for retrieved chunks."""

from __future__ import annotations

import re
import time
from pathlib import Path

from vault_context_mcp.config import VaultConfig
from vault_context_mcp.schemas import RetrievedChunk, SearchResult

STATE_FILES = {"01_current_state.md", "project_state.md"}
DECISION_FILES = {"03_decisions.md", "decisions.md"}
OPEN_QUESTION_FILES = {"open_questions.md"}
NEXT_ACTION_FILES = {"next_actions.md"}


class _RankScore(float):
    """Float score with subtraction normalized to ranker precision."""

    def __sub__(self, other: object) -> float:
        if isinstance(other, int | float):
            return round(float(self) - float(other), 4)
        raise TypeError(
            f"unsupported operand type(s) for -: '_RankScore' and '{type(other).__name__}'"
        )


def rank_results(
    results: list[SearchResult],
    config: VaultConfig,
    query: str,
    project: str | None = None,
) -> list[RetrievedChunk]:
    """Rank raw search results with explicit local policy.

    Args:
        results: Raw keyword search results.
        config: Runtime configuration.
        query: User task or search query.
        project: Optional project hint.

    Returns:
        Retrieved chunks sorted by descending final score.
    """

    ranked = [
        result.chunk.model_copy(
            update={
                "score": score_chunk(result.chunk, result.keyword_score, config, query, project)
            }
        )
        for result in results
    ]
    return sorted(ranked, key=lambda chunk: chunk.score, reverse=True)


def score_chunk(
    chunk: RetrievedChunk,
    keyword_score: float,
    config: VaultConfig,
    query: str,
    project: str | None = None,
) -> float:
    """Score a chunk according to the documented ranking policy."""

    query_terms = _terms(query)
    path_lower = chunk.path.lower()
    heading_lower = (chunk.heading or "").lower()
    text_lower = chunk.text.lower()
    file_name = Path(chunk.path).name.lower()

    score = keyword_score
    score += _term_overlap(query_terms, text_lower) * 0.25
    if chunk.metadata.get("is_canonical"):
        score += config.retrieval.canonical_boost
    if project and project.lower() in path_lower:
        score += config.retrieval.project_boost
    if project and project.lower() in text_lower:
        score += config.retrieval.project_boost * 0.35
    if any(term in heading_lower for term in query_terms):
        score += 1.0
    if any(term in path_lower for term in query_terms):
        score += 1.0
    if file_name in STATE_FILES:
        score += 1.5
    if file_name in DECISION_FILES:
        score += 1.2
    if file_name in OPEN_QUESTION_FILES:
        score += 1.0
    if file_name in NEXT_ACTION_FILES:
        score += 0.8
    if "archive" in Path(chunk.path).parts:
        score -= config.retrieval.archive_penalty
    if "_raw" in Path(chunk.path).parts:
        score -= config.retrieval.raw_penalty
    score += _recency_score(chunk, config)
    return _RankScore(round(max(score, 0.0), 4))


def _terms(query: str) -> list[str]:
    return [term for term in re.findall(r"[a-z0-9_/-]+", query.lower()) if len(term) > 1]


def _term_overlap(terms: list[str], text: str) -> int:
    return sum(1 for term in terms if term in text)


def _recency_score(chunk: RetrievedChunk, config: VaultConfig) -> float:
    modified = chunk.metadata.get("modified_time")
    if not isinstance(modified, int | float):
        return 0.0
    age_days = max((time.time() - float(modified)) / 86400.0, 0.0)
    return config.retrieval.recency_boost * (1.0 / (1.0 + age_days / 365.0))
