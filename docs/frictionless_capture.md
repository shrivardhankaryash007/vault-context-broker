# Frictionless Capture

The target behavior is simple:

```text
User: log this chat
Client: calls log_session with the current conversation
```

No copy/paste, no manual export, no separate command.

## MCP-Capable Clients

Claude Desktop, Claude Code, Codex, Gemini CLI, and local MCP clients can reach this behavior because they can call `vault-context-mcp` tools.

Add this as a persistent client instruction wherever the client supports custom instructions or project guidance:

```text
Use vault-context-mcp as my session memory layer.

At the start of substantial work:
- If I name a project or ongoing thread, call get_session_handoff(project=...) before answering.
- Use get_context_pack for compact cited vault context when more project context is needed.

When I say "log this", "log this chat", "log this session", "save this session", "remember this", or equivalent:
- Call log_session immediately.
- Do not ask me to copy, paste, export, or summarize the chat first.
- Use the current conversation as the transcript.
- Set source to this client name when known: claude, chatgpt, gemini, codex, local, or other.
- Include a concise title, origin/client, project if known, summary, key takeaways, decisions, open questions, and next actions.

At the end of substantial work:
- Offer to log the session only if I have not already asked.
- If I agree, call log_session.
```

The MCP server also exposes a prompt named `frictionless_session_logging` for clients that can import MCP prompts.

## Client Reality Check

Zero-friction logging requires the LLM client to have tool access. If a client cannot call local tools, the phrase "log this session" stays inside that provider's chat and cannot write to your vault by itself.

Current practical tiers:

- Claude Desktop: zero-friction through local stdio MCP.
- Claude Code: zero-friction through local stdio MCP.
- Codex: zero-friction in MCP-enabled contexts.
- Gemini CLI: zero-friction after MCP config is active.
- Local LLM shells: zero-friction if they support stdio MCP.
- ChatGPT web/browser: use the local userscript bridge.
- ChatGPT Desktop without a local tool bridge: not true zero-friction yet.
- Gemini web without a local tool bridge: not true zero-friction yet.

## Browser Bridge

For browser-only surfaces, install:

```text
scripts/vault_context_capture.user.js
```

This adds a `Log to Vault` button and `Cmd+Shift+L`. It is one-click rather than fully conversational, but still writes through the same local capture pipeline.

## Desktop Bridge

For desktop clients that cannot call MCP directly, the lowest-friction fallback is a small OS-level helper that captures selected or copied text and POSTs it to:

```text
http://127.0.0.1:8765/capture
```

That bridge is necessarily outside the LLM chat unless the desktop app exposes a local tool/plugin interface.
