"""A fixed synthetic retrieval gate with no user configuration or private inputs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from vault_context_mcp.config import (
    LibrarianConfig,
    RetrievalConfig,
    SecurityConfig,
    SummarizerConfig,
    VaultConfig,
)
from vault_context_mcp.context_builder import build_context_pack
from vault_context_mcp.index_store import IndexStore, build_index
from vault_context_mcp.retriever import search_vault


@dataclass(frozen=True)
class BenchmarkCheck:
    """One named assertion with its actual synthetic observations."""

    name: str
    passed: bool
    expected: str
    observed: tuple[str, ...]


@dataclass(frozen=True)
class BenchmarkReport:
    """Results describe synthetic coverage, never real-vault accuracy."""

    checks: tuple[BenchmarkCheck, ...]
    fts5_enabled: bool
    fixture_version: str = "synthetic-v1"

    @property
    def passed(self) -> bool:
        """Reject empty reports and any failed assertion."""
        return bool(self.checks) and all(check.passed for check in self.checks)

    def model_dump(self) -> dict[str, object]:
        """Return stable JSON data without temporary host paths or timestamps."""
        return {
            "fixture_version": self.fixture_version,
            "synthetic_only": True,
            "fts5_enabled": self.fts5_enabled,
            "passed": self.passed,
            "checks": [
                {
                    "name": check.name,
                    "passed": check.passed,
                    "expected": check.expected,
                    "observed": list(check.observed),
                }
                for check in self.checks
            ],
        }


def run_retrieval_benchmark() -> BenchmarkReport:
    """Exercise real consumers using only a fresh, disposable synthetic vault."""
    with TemporaryDirectory(prefix="vault-retrieval-benchmark-") as directory:
        return _run(Path(directory))


def _run(root: Path) -> BenchmarkReport:
    vault = root / "vault"
    notes = {
        "00_CONTEXT_INDEX.md": "# Context\n\n- lanternroute current reference.\n",
        "01_CURRENT_STATE.md": "# Current State\n\n- openlantern current status ready.\n",
        "archive/old.md": "# Context\n\n- lanternroute old reference.\n",
        "notes/distractor.md": "# lanternroute\n\n- current keyword reference.\n",
        "projects/Helios/PROJECT_STATE.md": "# Project State\n\n- orbitplan current work.\n",
        "projects/Zephyr/PROJECT_STATE.md": "# Project State\n\n- orbitplan current work.\n",
        "03_DECISIONS.md": (
            "---\nsensitivity: restricted\n---\n# Decisions\n\n"
            "- sealedquartz restricted mandatory decision.\n"
        ),
        "private/nested/note.md": "# Private\n\n- sealedquartz restricted path note.\n",
    }
    for relative, content in notes.items():
        path = vault / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    sensitivity_map = root / "sensitivity.yaml"
    sensitivity_map.write_text(
        "path_rules:\n  - pattern: private/**\n    sensitivity: restricted\n", encoding="utf-8"
    )
    config = VaultConfig(
        vault_root=str(vault),
        index_path=str(root / "index.sqlite3"),
        sensitivity_map_path=str(sensitivity_map),
        canonical_files=["00_CONTEXT_INDEX.md", "01_CURRENT_STATE.md"],
        retrieval=RetrievalConfig(recency_boost=0),
        summarizer=SummarizerConfig(provider="extractive"),
        librarian=LibrarianConfig(enabled=False, report_path=str(root / "report.md")),
        security=SecurityConfig(log_tool_calls=False),
    )
    _, _, fts_enabled = build_index(config)
    checks: list[BenchmarkCheck] = []

    def check(name: str, passed: bool, expected: str, observed: list[str]) -> None:
        checks.append(BenchmarkCheck(name, passed, expected, tuple(observed)))

    canonical = search_vault(config, "lanternroute", top_k=3)
    canonical_paths = [chunk.path for chunk in canonical]
    check(
        "canonical_first",
        bool(canonical_paths)
        and canonical_paths[0] == "00_CONTEXT_INDEX.md"
        and {"archive/old.md", "notes/distractor.md"} <= set(canonical_paths),
        "canonical reference precedes stronger keyword and archive distractors",
        canonical_paths,
    )
    project = search_vault(config, "orbitplan", top_k=2, project="Zephyr")
    project_paths = [chunk.path for chunk in project]
    check(
        "project_first",
        bool(project_paths) and project_paths[0] == "projects/Zephyr/PROJECT_STATE.md",
        "hinted project precedes equally matching other project",
        project_paths,
    )

    restricted_paths = {"03_DECISIONS.md", "private/nested/note.md"}
    cloud = search_vault(config, "sealedquartz", clearance="cloud")
    local = search_vault(config, "sealedquartz", clearance="local")
    check("cloud_search", not cloud, "no restricted search hits", [chunk.path for chunk in cloud])
    default_cloud = search_vault(config, "sealedquartz")
    check(
        "default_cloud_search",
        not default_cloud,
        "omitted clearance stays cloud-safe",
        [chunk.path for chunk in default_cloud],
    )
    check(
        "local_search",
        restricted_paths <= {chunk.path for chunk in local},
        "both frontmatter and path-restricted notes found locally",
        [chunk.path for chunk in local],
    )
    missing = search_vault(config, "absentcobalt")
    check("no_match", not missing, "no invented match", [chunk.path for chunk in missing])

    for clearance in ("cloud", "local"):
        pack = build_context_pack(config, "openlantern", clearance=clearance)
        paths = [source.path for source in pack.relevant_sources]
        serialized = pack.model_dump_json()
        if clearance == "cloud":
            check(
                "cloud_pack",
                "sealedquartz" not in serialized and not restricted_paths.intersection(paths),
                "no restricted source or text anywhere in cloud pack",
                paths,
            )
            check(
                "useful_cloud_pack",
                "01_CURRENT_STATE.md" in paths and "openlantern" in pack.context_summary,
                "nonempty cited open state and summary",
                paths,
            )
        else:
            check(
                "local_pack",
                "03_DECISIONS.md" in paths and "sealedquartz" in serialized,
                "restricted mandatory decision is available locally",
                paths,
            )

    state = vault / "01_CURRENT_STATE.md"
    notes["01_CURRENT_STATE.md"] += "- freshcobalt added after indexing.\n"
    state.write_text(notes["01_CURRENT_STATE.md"], encoding="utf-8")
    refreshed = search_vault(config, "freshcobalt")
    check(
        "source_refresh",
        any(
            chunk.path == "01_CURRENT_STATE.md" and "freshcobalt" in chunk.text
            for chunk in refreshed
        ),
        "new content found without explicit reindex",
        [chunk.path for chunk in refreshed],
    )

    # Force the supported FTS-error fallback in this disposable index only.
    if fts_enabled:
        with IndexStore(config.index_file_path).connect() as connection:
            connection.execute("DROP TABLE chunks_fts")
    like_cloud = search_vault(config, "sealedquartz", clearance="cloud")
    like_local = search_vault(config, "sealedquartz", clearance="local")
    check(
        "like_cloud",
        not like_cloud,
        "LIKE fallback excludes restricted hits",
        [chunk.path for chunk in like_cloud],
    )
    check(
        "like_local",
        restricted_paths <= {chunk.path for chunk in like_local},
        "LIKE fallback retains both restricted local hits",
        [chunk.path for chunk in like_local],
    )
    unchanged = all(
        (vault / relative).read_bytes() == content.encode("utf-8")
        for relative, content in notes.items()
    )
    check("source_unchanged", unchanged, "all consumers preserve fixture source bytes", [])
    return BenchmarkReport(tuple(checks), fts_enabled)
