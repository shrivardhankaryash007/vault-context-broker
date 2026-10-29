# 0002 Local Librarian Is Proposal-First

## Status

Accepted

## Context

The vault is canonical memory for multiple LLM clients. The user wants automatic freshness and organization, but silent automated vault edits could corrupt memory or create cross-client confusion.

## Decision

Add a local librarian that automatically refreshes the SQLite index and writes hygiene reports outside the vault by default. The librarian reports structure, naming, metadata, and chunkability issues. It does not modify vault content unless a future write-back design explicitly enables narrow, auditable operations.

## Consequences

- LLM clients can pull fresher context without scanning the vault.
- The user gets continuous hygiene feedback.
- Vault content remains protected from unattended model edits.
- Future write-back can be added behind explicit diffs, backups, and approvals.
