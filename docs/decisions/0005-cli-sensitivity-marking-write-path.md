# ADR 0005: Allow a CLI-only, raise-only sensitivity marking write path

**Status:** accepted for owner-authorized `Main_Vault/00_Inbox/Chats/**` execution (2026-10-23); code landed 2026-10-09
**Date:** 2026-10-09 (feature built 2026-07-09)

## Context

`AGENTS.md` makes `log_session` the only approved vault write path "unless a
future ADR allows more". On 2026-07-09 three CLI commands were built but never
committed: `mark-sensitive` (one note, for an Obsidian hotkey),
`backfill-sensitive` (every note under a scope) and `propose-sensitive` (asks
the local Ollama at `localhost:11434` for a suggestion and writes nothing).
Marking notes `restricted` is how the ADR 0036 M1 boundary is meant to reach
notes that no path rule covers.

## Decision

Allow vault writes from these commands only, under four constraints:

1. CLI only. No MCP tool exposes them, so no cloud seat can call them.
2. Raise only. The only value written is `sensitivity: restricted` plus the
   `sensitive` tag. Nothing ever writes `open`.
3. `backfill-sensitive` defaults to dry-run and requires `--apply` to write.
4. Scope must resolve inside `vault_root`; anything outside is refused.

## Consequences

- Restricting a note becomes a single action, without editing YAML by hand.
- A wide `backfill-sensitive --apply` can over-restrict and hide notes from
  cloud retrieval. Recovery is `git` in the vault repository, which is tracked
  since 2026-07-05.
- Any future write that could lower sensitivity needs its own ADR.

## Acceptance receipt (2026-10-23)

The owner explicitly authorized the Chats-only proposal/dry-run/apply operation
and genuine source-change invalidation check. Six notes were marked through the
existing CLI after verified lossless backup and deterministic body-preservation
preflight. The local proposal queried six notes and proposed zero; the owner's
explicit whole-scope instruction governs the apply scope. No private note names,
content or proposal reasons were exported. Repeat dry-run selected zero writes.
See `plans/vault-live-acceptance/plan.mdx` and its sanitized production receipt.

Authorization does not approve general librarian auto-fixes or new MCP write
capabilities. The existing background process failed to consume the production
change within the observation window. Persistent configuration changes plus a
restart were rejected by automatic approval review as beyond the scoped task;
that service repair required owner approval.

The owner subsequently said "Approve safe watcher repair", explicitly approving
disabling only `librarian.auto_apply_fixes` and
`session_log.summarize_unprocessed_on_watch` before restarting the existing
librarian. A lossless config backup and semantic equality check preserve all
other settings. The restarted service refreshed the production index with all
16 scoped chunks restricted and zero cloud dependency chunks; vault hashes
remained unchanged. This narrows background write behavior to the approved
product contracts and does not add a new vault write path.
