#!/usr/bin/env python3
"""Small local smoke test for a configured vault."""

from __future__ import annotations

import json

from vault_context_mcp.config import load_config
from vault_context_mcp.context_builder import build_context_pack
from vault_context_mcp.index_store import build_index
from vault_context_mcp.retriever import search_vault


def main() -> None:
    """Build the index, search, and print one context pack."""

    config = load_config()
    file_count, chunk_count, fts_enabled = build_index(config)
    results = search_vault(config, "current state", top_k=3)
    pack = build_context_pack(config, "Continue current project")
    print(
        json.dumps(
            {
                "files": file_count,
                "chunks": chunk_count,
                "fts5_enabled": fts_enabled,
                "top_results": [result.path for result in results],
                "pack": pack.model_dump(),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
