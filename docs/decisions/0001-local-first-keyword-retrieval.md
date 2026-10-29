# 0001 Local-First Keyword Retrieval

## Status

Accepted

## Context

`vault-context-mcp` must work without cloud APIs and without requiring a vector database. The first acceptance target is reliable Claude Desktop stdio launch plus compact, cited context packs from a local Obsidian vault.

## Decision

Use SQLite as the local index with FTS5 keyword search when available and a LIKE fallback when FTS5 is unavailable. Apply an explicit deterministic ranker for canonical files, project files, recency, path matches, headings, and archive penalties.

## Consequences

- v0 is easy to install, inspect, and back up.
- Retrieval is explainable and deterministic.
- Semantic recall is limited compared with embeddings.
- A future embedding provider can be added without changing the MCP tool contract.
