# Claude Code Setup

Claude Code can add local stdio MCP servers with `claude mcp add-json`.

Install:

```bash
vault-context install-claude-code
```

Equivalent manual command:

```bash
claude mcp add-json --scope user vault-context-mcp '{
  "type": "stdio",
  "command": "/path/to/vault-context-mcp/.venv/bin/python",
  "args": ["-m", "vault_context_mcp", "serve-mcp"],
  "env": {
    "VAULT_CONTEXT_CONFIG": "/path/to/vault-context-mcp/config.yaml"
  }
}'
```

Verify:

```bash
claude mcp get vault-context-mcp
```

Inside Claude Code, use `/mcp` to inspect connected servers.

## Session Capture

Claude Code can call:

```text
get_session_handoff
log_session
```

Existing Claude project session logs in `01-Sessions/` and `08-Sessions/` are also scanned, so older high-quality Claude logs remain available to ChatGPT, Gemini, Codex, and local models through the same handoff tool.
