# vault-context-mcp

`vault-context-mcp` is a local-first MCP server that turns an Obsidian vault into compact, cited context packs for Claude Desktop, Claude Code, Codex, and future MCP-compatible clients.

It is not a chatbot, UI, agent orchestrator, or vault writer. v0 is a read-only context broker.

## Why It Exists

Obsidian is the canonical memory. Frontier LLMs should not spend tokens scanning an entire vault. They should ask a local broker for the smallest useful context slice, with source paths and heading anchors.

## Architecture

```text
Obsidian Vault
    ↓
vault-context-mcp indexer
    ↓
SQLite index
    ↓
MCP tools
    ↓
Claude Desktop / Codex / Claude Code / future clients
```

## Installation

```bash
cd vault-context-mcp
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
cp config.example.yaml config.yaml
```

Edit `config.yaml` and set `vault_root` to your Obsidian vault.

## Configuration

The runtime config is loaded from:

```bash
export VAULT_CONTEXT_CONFIG=/absolute/path/to/config.yaml
```

If no config is provided, `vault-context` explains how to copy `config.example.yaml`.

## Indexing The Vault

```bash
vault-context doctor
vault-context index
```

## Running The CLI

```bash
vault-context search "current state"
vault-context pack "Continue my LLM agnostic Obsidian context broker design"
vault-context pack "Continue ATLAS architecture" --mode standard --project ATLAS
```

Run the retrieval quality gate independently of your vault or configuration:

```bash
vault-context benchmark-retrieval
```

It creates and removes a temporary synthetic vault and index, uses no model or
network service, and prints JSON with named checks. A failed check exits 1.
Checks cover ranking, useful cited context, restricted-content isolation,
source refresh, source preservation and SQLite LIKE fallback. This is synthetic
regression coverage; it does not measure your real vault's retrieval accuracy.
CI runs this same command after the test suite.

To run the bundled sample-vault acceptance path:

```bash
VAULT_CONTEXT_CONFIG="$(pwd)/config.sample.yaml" vault-context doctor
VAULT_CONTEXT_CONFIG="$(pwd)/config.sample.yaml" vault-context index
VAULT_CONTEXT_CONFIG="$(pwd)/config.sample.yaml" vault-context search "ATLAS project state"
VAULT_CONTEXT_CONFIG="$(pwd)/config.sample.yaml" vault-context pack "Continue ATLAS architecture" --mode standard --project ATLAS
```

## Source provenance and freshness

Optional deterministic provenance records source versions and derivation dependencies outside the vault. It never writes source notes or calls a model. Enable a bounded scope in your local configuration:

```yaml
librarian:
  provenance:
    enabled: true
    scope: ["Main_Vault/00_Inbox/Chats"]
    state_dir: "~/.vault-context-mcp/provenance"
```

Run `vault-context provenance-scan` twice to observe discovery followed by a no-op. `provenance-propose ID --dep RELATIVE_PATH`, `provenance-review ID --accept`, and `provenance-report --json` track proposals, review and stale dependencies. `provenance-trace SUBJECT` shows the transition history. Reports show counts by default; `--paths` requests paths under the caller's clearance. Existing librarian refreshes also scan when enabled. Keep state outside the vault, serialize commands, and use a fresh state directory when changing scope. See ADR 0006.

## Running The MCP Server

```bash
vault-context serve-mcp
```

## Claude Desktop Setup

Claude Desktop config path on macOS:

```text
~/Library/Application Support/Claude/claude_desktop_config.json
```

Python module launch:

```json
{
  "mcpServers": {
    "vault-context-mcp": {
      "command": "/absolute/path/to/python",
      "args": [
        "-m",
        "vault_context_mcp",
        "serve-mcp"
      ],
      "env": {
        "VAULT_CONTEXT_CONFIG": "/absolute/path/to/config.yaml"
      }
    }
  }
}
```

Console script launch:

```json
{
  "mcpServers": {
    "vault-context-mcp": {
      "command": "vault-context",
      "args": ["serve-mcp"],
      "env": {
        "VAULT_CONTEXT_CONFIG": "/absolute/path/to/config.yaml"
      }
    }
  }
}
```

You can patch Claude's config safely:

```bash
vault-context install-claude
```

Then restart Claude Desktop.

## Codex Setup

See `docs/codex_setup.md`. In MCP-compatible Codex environments, configure `vault-context` with `serve-mcp` and set `VAULT_CONTEXT_CONFIG` to an absolute config path.

## Multi-Client Setup

Configure supported local MCP clients:

```bash
vault-context install-all-clients
```

See:

- `docs/client_setup.md`
- `docs/claude_desktop_setup.md`
- `docs/claude_code_setup.md`
- `docs/codex_setup.md`
- `docs/gemini_setup.md`
- `docs/chatgpt_setup.md`

## Local Librarian

Run a hygiene audit:

```bash
vault-context librarian-audit
```

Run the watcher in the foreground:

```bash
vault-context librarian-watch
```

Install the macOS background watcher:

```bash
vault-context install-librarian-agent
```

The librarian automatically refreshes the SQLite index when Markdown files change and writes hygiene reports outside the vault by default. See `docs/librarian.md`.

LLM clients can call:

```text
get_librarian_report
```

## Cross-LLM Session Capture

Log useful thinking from Claude, ChatGPT, Gemini, Codex, and local LLMs into one vault trail:

```bash
vault-context log-session --source chatgpt --title "ATLAS review" --project ATLAS --transcript-file transcript.md
```

Run the localhost capture endpoint:

```bash
vault-context serve-capture
```

Install it as a background service:

```bash
vault-context install-capture-agent
```

MCP clients can call `log_session`, `get_recent_sessions`, and `get_session_handoff`. Existing Claude project session logs in `01-Sessions/` and `08-Sessions/` are recognized as first-class handoff context. See `docs/session_capture.md`.

For ChatGPT, Gemini, and Claude browser sessions, install the userscript at `scripts/vault_context_capture.user.js` after starting or installing the local capture endpoint. It adds a `Log to Vault` button that sends selected chat text to the local capture pipeline.

For the Claude-style phrase flow, use the persistent instruction in `docs/frictionless_capture.md`. MCP-capable clients can then treat "log this chat/session" as a direct call to `log_session`.

## Troubleshooting

```bash
vault-context doctor
vault-context pack "test task"
```

Use absolute paths in MCP configs and restart Claude Desktop after config changes.

## Security Model

- Retrieval and librarian tools are read-only for vault content.
- Session capture is an allowlisted write path for preserving LLM thinking.
- MCP tools do not execute shell commands.
- Reads are restricted to the configured vault root.
- Symlinks escaping the vault root are rejected.
- No cloud API is required.
- Optional Ollama summarization is local only.
- The local librarian refreshes the index and writes reports outside the vault by default.

See `docs/security_model.md`.

## Roadmap

- Local embedding provider interface.
- Incremental indexing.
- Better markdown link and tag awareness.
- Optional local Ollama summaries with stricter time budgets.
- Explicitly designed write-back tools in a future version.
