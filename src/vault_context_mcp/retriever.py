"""High-level retrieval flows over the SQLite index."""

from __future__ import annotations

from pathlib import Path

from vault_context_mcp.config import VaultConfig
from vault_context_mcp.index_store import IndexStore, ensure_index
from vault_context_mcp.ranker import rank_results, score_chunk
from vault_context_mcp.schemas import Clearance, ContextMode, RetrievedChunk

MANDATORY_ROOT_FILES = ["01_CURRENT_STATE.md", "02_ACTIVE_PROJECTS.md", "03_DECISIONS.md"]
MANDATORY_PROJECT_FILES = ["PROJECT_STATE.md", "DECISIONS.md", "OPEN_QUESTIONS.md"]


def retrieve_chunks(
    config: VaultConfig,
    task: str,
    mode: ContextMode = "standard",
    project: str | None = None,
    clearance: Clearance = "cloud",
) -> list[RetrievedChunk]:
    """Retrieve ranked chunks for a context pack.

    Args:
        config: Runtime configuration.
        task: User task.
        mode: Retrieval mode.
        project: Optional project hint.

    Returns:
        Ranked chunks constrained by mode limits.
    """

    ensure_index(config)
    store = IndexStore(config.index_file_path)
    limit = config.retrieval.max_chunks[mode]
    raw = store.search(task, top_k=max(limit * 4, 20), clearance=clearance)
    ranked = rank_results(raw, config, task, project)
    mandatory = _mandatory_chunks(store, config, task, project, clearance)
    by_id: dict[str, RetrievedChunk] = {}
    for chunk in [*mandatory, *ranked]:
        by_id.setdefault(chunk.chunk_id, chunk)
    return sorted(by_id.values(), key=lambda chunk: chunk.score, reverse=True)[:limit]


def search_vault(
    config: VaultConfig,
    query: str,
    top_k: int = 10,
    project: str | None = None,
    clearance: Clearance = "cloud",
) -> list[RetrievedChunk]:
    """Search vault chunks and return ranked results."""

    ensure_index(config)
    store = IndexStore(config.index_file_path)
    raw = store.search(query, top_k=max(top_k * 4, 20), clearance=clearance)
    return rank_results(raw, config, query, project)[:top_k]


def _mandatory_chunks(
    store: IndexStore,
    config: VaultConfig,
    task: str,
    project: str | None,
    clearance: Clearance,
) -> list[RetrievedChunk]:
    paths = store.list_paths()
    selected: list[str] = []
    for file_name in MANDATORY_ROOT_FILES:
        selected.extend(path for path in paths if Path(path).name == file_name)
    if project:
        project_lower = project.lower()
        for path in paths:
            parts = [part.lower() for part in Path(path).parts]
            if "projects" not in parts or project_lower not in parts:
                continue
            if Path(path).name in MANDATORY_PROJECT_FILES:
                selected.append(path)
    chunks = store.get_chunks_for_paths(sorted(set(selected)), clearance=clearance)
    return [
        chunk.model_copy(update={"score": score_chunk(chunk, 0.2, config, task, project)})
        for chunk in chunks
    ]


def chunks_for_file_name(
    config: VaultConfig,
    file_names: set[str],
    project: str | None = None,
    clearance: Clearance = "cloud",
) -> list[RetrievedChunk]:
    """Return chunks whose file names match the given names."""

    ensure_index(config)
    store = IndexStore(config.index_file_path)
    paths = []
    project_lower = project.lower() if project else None
    for path in store.list_paths():
        if Path(path).name.upper() not in {name.upper() for name in file_names}:
            continue
        if project_lower and project_lower not in path.lower():
            continue
        paths.append(path)
    chunks = store.get_chunks_for_paths(paths, clearance=clearance)
    return [
        chunk.model_copy(
            update={"score": score_chunk(chunk, 0.2, config, " ".join(file_names), project)}
        )
        for chunk in chunks
    ]
