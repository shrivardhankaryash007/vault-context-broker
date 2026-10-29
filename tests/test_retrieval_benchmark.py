"""The synthetic gate must detect failures in real retrieval consumers."""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path

import pytest
from typer.testing import CliRunner

from vault_context_mcp import config, context_builder, index_store, ranker, retriever
from vault_context_mcp.cli import app
from vault_context_mcp.config import VaultConfig
from vault_context_mcp.index_store import IndexStore
from vault_context_mcp.schemas import Clearance, RetrievedChunk, SearchResult
from vault_context_mcp.summarizer import Summarizer


def test_benchmark_runs_without_user_config(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from vault_context_mcp.retrieval_benchmark import run_retrieval_benchmark

    monkeypatch.setenv("VAULT_CONTEXT_CONFIG", str(tmp_path / "must-not-load.yaml"))
    monkeypatch.setenv("VAULT_CONTEXT_CLEARANCE", "local")

    def forbidden_call(*args: object, **kwargs: object) -> None:
        pytest.fail("Synthetic benchmark attempted user config or network access")

    monkeypatch.setattr(config, "load_config", forbidden_call)
    monkeypatch.setattr(urllib.request, "urlopen", forbidden_call)
    report = run_retrieval_benchmark()
    assert report.passed
    assert report.fixture_version == "synthetic-v1"
    assert len(report.checks) >= 10
    assert len({check.name for check in report.checks}) == len(report.checks)
    assert not list(tmp_path.iterdir())
    assert report.model_dump() == run_retrieval_benchmark().model_dump()


def test_benchmark_rejects_empty_search(monkeypatch: pytest.MonkeyPatch) -> None:
    from vault_context_mcp.retrieval_benchmark import run_retrieval_benchmark

    monkeypatch.setattr(IndexStore, "search", lambda *args, **kwargs: [])
    assert not run_retrieval_benchmark().passed


def test_benchmark_rejects_mandatory_restricted_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from vault_context_mcp.retrieval_benchmark import run_retrieval_benchmark

    original = IndexStore.get_chunks_for_paths

    def leaky_paths(
        self: IndexStore, paths: list[str], clearance: Clearance = "cloud"
    ) -> list[RetrievedChunk]:
        return original(self, paths, clearance="local")

    monkeypatch.setattr(IndexStore, "get_chunks_for_paths", leaky_paths)
    report = run_retrieval_benchmark()
    assert not report.passed
    assert any(not check.passed and check.name == "cloud_pack" for check in report.checks)


def test_benchmark_rejects_leak_in_context_text(monkeypatch: pytest.MonkeyPatch) -> None:
    from vault_context_mcp.retrieval_benchmark import run_retrieval_benchmark

    original = context_builder.Summarizer.summarize

    def leaky_summary(
        self: Summarizer, task: str, chunks: list[RetrievedChunk], max_tokens: int
    ) -> str:
        return original(self, task, chunks, max_tokens) + " sealedquartz"

    monkeypatch.setattr(context_builder.Summarizer, "summarize", leaky_summary)
    assert not run_retrieval_benchmark().passed


def test_benchmark_rejects_stale_index(monkeypatch: pytest.MonkeyPatch) -> None:
    from vault_context_mcp.retrieval_benchmark import run_retrieval_benchmark

    monkeypatch.setattr(retriever, "ensure_index", lambda config: None)
    report = run_retrieval_benchmark()
    assert any(not check.passed and check.name == "source_refresh" for check in report.checks)


def test_benchmark_rejects_like_clearance_regression(monkeypatch: pytest.MonkeyPatch) -> None:
    from vault_context_mcp.retrieval_benchmark import run_retrieval_benchmark

    original = IndexStore._search_like

    def leaky_like(
        self: IndexStore, terms: list[str], top_k: int, clearance: Clearance
    ) -> list[SearchResult]:
        return original(self, terms, top_k, clearance="local")

    monkeypatch.setattr(IndexStore, "_search_like", leaky_like)
    report = run_retrieval_benchmark()
    assert any(not check.passed and check.name == "like_cloud" for check in report.checks)


@pytest.mark.parametrize(
    ("boost", "check_name"),
    [("canonical_boost", "canonical_first"), ("project_boost", "project_first")],
)
@pytest.mark.parametrize("fts_enabled", [True, False])
def test_benchmark_rejects_missing_ranking_boost(
    monkeypatch: pytest.MonkeyPatch, boost: str, check_name: str, fts_enabled: bool
) -> None:
    from vault_context_mcp.retrieval_benchmark import run_retrieval_benchmark

    original = ranker.score_chunk
    if not fts_enabled:
        monkeypatch.setattr(index_store, "sqlite_supports_fts5", lambda: False)

    def no_boost(
        chunk: RetrievedChunk,
        keyword_score: float,
        config: VaultConfig,
        query: str,
        project: str | None = None,
    ) -> float:
        altered = config.model_copy(
            update={"retrieval": config.retrieval.model_copy(update={boost: 0})}
        )
        return original(chunk, keyword_score, altered, query, project)

    monkeypatch.setattr(ranker, "score_chunk", no_boost)
    report = run_retrieval_benchmark()
    assert any(not check.passed and check.name == check_name for check in report.checks)


def test_benchmark_without_fts5(monkeypatch: pytest.MonkeyPatch) -> None:
    from vault_context_mcp.retrieval_benchmark import run_retrieval_benchmark

    monkeypatch.setattr(index_store, "sqlite_supports_fts5", lambda: False)
    report = run_retrieval_benchmark()
    assert report.passed
    assert report.fts5_enabled is False


def test_benchmark_cli_json_and_failed_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["benchmark-retrieval"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["passed"] is True
    monkeypatch.setattr(IndexStore, "search", lambda *args, **kwargs: [])
    result = runner.invoke(app, ["benchmark-retrieval"])
    assert result.exit_code == 1, result.output
    assert json.loads(result.output)["passed"] is False
