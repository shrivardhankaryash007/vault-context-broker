# Context Pack Schema

The primary MCP tool, `get_context_pack`, returns a JSON-serializable object with these top-level fields:

- `task`: user task being prepared for.
- `mode`: one of `brief`, `standard`, `deep`, or `audit`.
- `project`: optional project hint.
- `generated_at`: UTC timestamp.
- `context_summary`: compact extractive summary.
- `relevant_sources`: cited source references with path, heading, line range, reason, and score.
- `current_state`: extracted current-state bullets.
- `prior_decisions`: extracted decision bullets.
- `constraints`: extracted constraints, rules, and requirements.
- `open_questions`: extracted unknowns and unresolved items.
- `key_facts`: other high-signal facts.
- `missing_context`: what the broker could not confidently find.
- `suggested_next_files`: source references worth opening next.
- `confidence`: score from 0.0 to 1.0.

## Ranking Policy

Every retrieved chunk receives a transparent score. The current v0 score combines:

- Keyword relevance from query-term overlap and SQLite search rank.
- Canonical-file boost for configured files like `01_CURRENT_STATE.md`, `03_DECISIONS.md`, and `PROJECT_STATE.md`.
- Project boost when a project hint matches the path or file content.
- Recency boost based on file modification time.
- Archive penalty for paths under ignored archive-like folders.
- Title and heading match boosts.
- Path match boosts.
- Extra boosts for current-state, decision, open-question, and next-action files.

This policy intentionally favors canonical operating-memory files over random old notes. The tradeoff is that unusual but relevant notes may rank lower until embeddings are added.
