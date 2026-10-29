# Codex Setup

Codex discovers repository instructions by walking up from the working directory and reading files such as `AGENTS.md`. Keep this repository's `AGENTS.md` committed so Codex and other agents preserve the read-only, local-first design.

For MCP-compatible Codex environments, use a config entry equivalent to:

```toml
[mcp_servers.vault-context-mcp]
command = "vault-context"
args = ["serve-mcp"]

[mcp_servers.vault-context-mcp.env]
VAULT_CONTEXT_CONFIG = "/absolute/path/to/config.yaml"
```

If your Codex installation expects JSON instead of TOML, the shape is:

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

Run this from the project before connecting a client:

```bash
vault-context doctor
vault-context index
vault-context pack "Continue my current project"
```

## Install Automatically

```bash
vault-context install-codex
```

This uses:

```bash
codex mcp add vault-context-mcp \
  --env VAULT_CONTEXT_CONFIG=/path/to/vault-context-mcp/config.yaml \
  -- /path/to/vault-context-mcp/.venv/bin/python -m vault_context_mcp serve-mcp
```

Verify:

```bash
codex mcp list
```

## Session Capture

Before continuing a project:

```text
Call get_session_handoff for this project.
```

At the end of substantive work:

```text
Call log_session with source="codex", the session summary, key decisions, open questions, next actions, and concise transcript.
```
