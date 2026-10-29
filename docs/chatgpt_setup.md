# ChatGPT Setup

ChatGPT custom MCP apps/connectors currently use remote MCP servers, not local stdio servers.

That means this local-first server is immediately usable from local clients such as Claude Desktop, Claude Code, Codex, Gemini CLI, Cursor, VS Code-style MCP clients, and local LLM shells that can launch stdio MCP servers.

For ChatGPT, the current paths are:

1. Keep this as a local stdio server for local desktop/CLI clients.
2. Build a separate remote MCP deployment that proxies the same read-only context broker over HTTPS.
3. In ChatGPT, enable developer mode and add the remote MCP app/connector from Settings or Workspace Settings.

Do not expose the vault directly to the internet. A future ChatGPT bridge should:

- Keep the vault on the local machine or a trusted private host.
- Require authentication.
- Expose only read-only tools.
- Log access locally.
- Avoid returning raw full-vault content.
- Prefer a private VPN/tunnel or trusted deployment boundary over a public unauthenticated URL.

Current local stdio command:

```bash
vault-context serve-mcp
```

Future remote bridge target:

```text
https://your-private-domain.example/mcp
```

Until that remote bridge exists, ChatGPT Desktop cannot directly launch this local stdio MCP server.

## Practical Local Capture Path

ChatGPT sessions can still be captured locally through the localhost capture endpoint:

```bash
vault-context install-capture-agent
```

Then send JSON to:

```text
http://127.0.0.1:8765/capture
```

This is useful for browser userscripts, Shortcuts, or small desktop helpers that can read/copy the visible transcript and POST it locally. Captures land in:

```text
Main_Vault/00_Inbox/Chats/ChatGPT/
```

For ChatGPT in a browser, install the userscript at:

```text
scripts/vault_context_capture.user.js
```

It adds a `Log to Vault` button and `Cmd+Shift+L` shortcut on ChatGPT pages. Select the useful part of a conversation before logging it so the vault receives compact, intentional session notes.

This is not the same as Claude Desktop's "log this session" flow because ChatGPT cannot call this local stdio MCP server directly. True phrase-based logging requires a ChatGPT-accessible tool bridge or remote MCP app that can authenticate back to this local broker.
