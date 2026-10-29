# Gemini Setup

Gemini CLI supports MCP servers through `mcpServers` in `settings.json`.

User settings path:

```text
~/.gemini/settings.json
```

Install:

```bash
vault-context install-gemini
```

Expected entry:

```json
{
  "mcpServers": {
    "vault-context-mcp": {
      "type": "stdio",
      "command": "/path/to/vault-context-mcp/.venv/bin/python",
      "args": ["-m", "vault_context_mcp", "serve-mcp"],
      "env": {
        "VAULT_CONTEXT_CONFIG": "/path/to/vault-context-mcp/config.yaml"
      },
      "trust": true,
      "timeout": 30000
    }
  }
}
```

If `gemini` is not installed yet, the installer still writes the config. Install Gemini CLI later, then run:

```bash
gemini mcp list
```

Inside Gemini CLI, use `/mcp` to inspect server status.

## Session Capture

In Gemini CLI, ask Gemini to call:

```text
get_session_handoff(project="...")
```

before substantive work, and:

```text
log_session(source="gemini", ...)
```

at the end of the session.

For frictionless behavior, add the persistent instruction from `docs/frictionless_capture.md` to Gemini CLI guidance. After that, "log this session" should call `log_session` directly when the MCP server is connected.

For non-MCP Gemini surfaces, pipe or paste the transcript into:

```bash
vault-context log-session --source gemini --title "..." --origin "Gemini" --project "..."
```
