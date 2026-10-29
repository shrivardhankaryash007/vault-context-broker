# Client Setup

`vault-context-mcp` is a local stdio MCP server. Any local MCP-compatible client that can launch a command can use this server with:

```json
{
  "mcpServers": {
    "vault-context-mcp": {
      "type": "stdio",
      "command": "/path/to/vault-context-mcp/.venv/bin/python",
      "args": ["-m", "vault_context_mcp", "serve-mcp"],
      "env": {
        "VAULT_CONTEXT_CONFIG": "/path/to/vault-context-mcp/config.yaml"
      }
    }
  }
}
```

## One-command local setup

```bash
vault-context install-all-clients
```

This configures:

- Claude Desktop via `claude_desktop_config.json`
- Claude Code via `claude mcp add-json --scope user`
- Codex via `codex mcp add`
- Gemini CLI via `~/.gemini/settings.json`

Restart each client after changing MCP config.

## Verification

```bash
vault-context doctor
vault-context index
vault-context pack "What is my current ATLAS project state?" --mode standard
```

In a client, ask:

```text
Use the vault-context-mcp context broker to get a context pack for my current ATLAS project state.
```

The client should call `get_context_pack`.

For freshness and vault hygiene, clients can also call:

```text
get_librarian_report(refresh_index_first=true)
```

For continuity, clients can call:

```text
get_session_handoff(project="ATLAS")
log_session(...)
```

## Frictionless Session Logging

To make "log this chat" work the way it does in Claude Desktop, add the persistent instruction from:

```text
docs/frictionless_capture.md
```

The server also exposes an MCP prompt named `frictionless_session_logging` for clients that can import MCP prompts.
