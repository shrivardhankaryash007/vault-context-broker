# Local Librarian

The local librarian keeps `vault-context-mcp` useful after the vault changes.

It has two jobs:

1. Keep the SQLite context index fresh.
2. Report vault hygiene issues that can confuse LLM clients.

It is not a chatbot and does not rewrite notes by default.

## Commands

Run one audit:

```bash
vault-context librarian-audit
```

Refresh the index and audit:

```bash
vault-context librarian-audit --refresh-index
```

Watch for Markdown changes:

```bash
vault-context librarian-watch
```

Install the macOS background service:

```bash
vault-context install-librarian-agent
```

Uninstall it:

```bash
vault-context uninstall-librarian-agent
```

## What It Checks

- Missing canonical memory files such as `README.md`, `00_CONTEXT_INDEX.md`, `01_CURRENT_STATE.md`, `02_ACTIVE_PROJECTS.md`, and `03_DECISIONS.md`
- Duplicate note names that may confuse citations
- Missing or repeated H1 headings
- Unresolved template placeholders near the top of a note
- Oversized notes that should be split or indexed

## Reports

By default reports are written outside the vault:

```text
~/.vault-context-mcp/librarian_report.md
~/.vault-context-mcp/librarian_report.json
```

This keeps v0 safe: the librarian can observe and propose, but it does not silently alter canonical memory.

## MCP Tool

Clients can call:

```text
get_librarian_report(refresh_index_first=false)
```

Use this before important work when you want the LLM to know whether the vault is fresh and well-structured.

## Write Policy

Vault write-back is disabled by default. Future write-back should be implemented as a separate design with:

- Explicit allowlisted operations
- Diffs before writes
- Backups
- Manual approval for every content change until the rules are proven
- No model-authored silent rewrites
