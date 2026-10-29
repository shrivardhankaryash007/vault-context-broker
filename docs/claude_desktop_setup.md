# Claude Desktop Setup

Claude Desktop can launch local MCP servers from its JSON config on macOS:

```text
~/Library/Application Support/Claude/claude_desktop_config.json
```

Use absolute paths. A Python module launch looks like this:

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

If installed as a console script, this also works:

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

You can patch the config safely with:

```bash
vault-context install-claude
```

The installer backs up the existing Claude config and preserves other MCP servers.

## Session Capture

Claude Desktop can call these MCP tools:

```text
get_session_handoff
log_session
```

Recommended end-of-session prompt:

```text
Log this session.
```

For fully frictionless behavior, add the persistent instruction from `docs/frictionless_capture.md` to Claude's project/custom instructions. Then "log this chat" should map directly to `log_session` without a copy/paste/export step.

## Troubleshooting

- Restart Claude Desktop after config changes.
- Run `vault-context doctor`.
- Run `vault-context pack "test task"` before launching Claude.
- Use absolute paths for Python and config.
- Check that the Python environment has `vault-context-mcp` installed.
- Validate `claude_desktop_config.json` as JSON.
- Do not use relative paths in Claude Desktop config.
