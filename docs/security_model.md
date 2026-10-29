# Security Model

`vault-context-mcp` retrieval is read-only. Separate allowlisted session capture and owner-approved CLI sensitivity marking have narrow vault write contracts.

1. Context retrieval and librarian tools do not modify vault content.
2. `log_session` may create new Markdown session logs only inside configured session-log folders under the vault root.
3. Session capture may append one line to today's configured daily note when enabled.
4. MCP tools cannot execute shell commands.
5. The vault root is allowlisted in config.
6. Symlinks that escape the vault root are rejected.
7. No file outside the vault root is read except the user-selected config file and the SQLite index.
8. Tool calls are logged locally only when `security.log_tool_calls` is enabled.
9. No cloud calls are made unless the user explicitly configures a future provider.
10. Optional Ollama summarization is local only.
11. The local librarian may write reports outside the vault by default.
12. The local librarian may refresh the SQLite index automatically.
13. CLI-only, raise-only sensitivity marking is separately designed in ADR 0005; the owner accepted its exact Chats scope on 2026-10-23. It is not exposed through MCP.
14. Other write-back beyond session capture requires a separate design and explicit user approval.

The routine writes are the local SQLite index at `index_path`, local tool-call logs when enabled, local librarian reports at `librarian.report_path`, and allowlisted session captures. CLI sensitivity writes require the separately approved scope in ADR 0005.

## Sensitivity boundary (ADR 0036)

Every indexed chunk carries a `sensitivity` class: `open` or `restricted`.
Resolution order (`src/vault_context_mcp/sensitivity.py`):

1. Frontmatter `sensitivity:` field on the note, if present and valid — wins over everything else.
2. Path-rule defaults from `sensitivity_map.yaml` (`sensitivity_map_path` in `config.yaml`, default `~/.vault-context-mcp/sensitivity_map.yaml`) — first matching rule wins.
3. Otherwise `open` (default-restricted-for-unmapped was rejected: it would blank cloud retrieval until a full manual backfill).

Every caller declares a clearance: `cloud` (open chunks only) or `local` (all
chunks). Declared via the `VAULT_CONTEXT_CLEARANCE` environment variable per
transport (each MCP client config sets it); missing or invalid values default
to `cloud` — a misconfigured or new seat is safe by default, not leaky by
default. Filtering happens inside the retriever's SQL (`IndexStore.search`,
`IndexStore.get_chunks_for_paths`), never as a post-hoc filter on already-
returned results, so it holds for every current and future tool built on top
of those two methods.

This is *accidental*-leakage protection for a single-owner local machine, not
an adversarial security boundary — any local process can lie about its
clearance. It stops a cloud LLM seat from being handed restricted content by
a normal query; it does not stop a deliberately malicious local process.

Every tool call is logged with `client`, `clearance`, `chunks_returned`, and
`est_tokens` (`tool_call_log` table) — the ledger-traceability requirement
for the token-economy work.

The leak test that enforces this (fixture vault with `open` + `restricted`
notes; asserts a `cloud`-clearance caller gets zero restricted chunks across
`search_vault`, `get_context_pack`, and a hypothesis property test over
arbitrary query strings) is protected-core — see
`standards/agentic-os/PROTECTED-CORE.md`. No future change may weaken it
without an ADR.
