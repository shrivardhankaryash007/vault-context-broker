# Cross-LLM Session Capture

The session capture layer prevents useful thinking from staying trapped inside one LLM platform.

It supports three capture paths:

1. MCP tools for Claude Desktop, Claude Code, Codex, Gemini CLI, and local MCP clients.
2. CLI capture from stdin or a transcript file.
3. A localhost HTTP capture endpoint for browser scripts, shortcuts, or small desktop helpers.

Existing structured Claude session logs are also indexed as first-class session history. The handoff reader scans both:

- New universal logs under `Main_Vault/00_Inbox/Chats/<Source>/`
- Existing project logs under `01-Sessions/` and `08-Sessions/`

## MCP Tools

Log a session:

```text
log_session(
  source="chatgpt",
  title="ATLAS architecture continuation",
  transcript="...",
  origin="chatgpt desktop",
  project="ATLAS",
  summary="What changed in one sentence",
  key_takeaways=["..."],
  decisions=["..."],
  open_questions=["..."],
  next_actions=["..."]
)
```

Read recent sessions:

```text
get_recent_sessions(project="ATLAS", limit=10)
```

Build a cross-client handoff:

```text
get_session_handoff(project="ATLAS", limit=8)
```

Suggested prompt in any MCP-capable client:

```text
Before we continue, call get_session_handoff for this project. At the end, call log_session with the transcript summary, decisions, open questions, and next actions.
```

## CLI Capture

From a file:

```bash
vault-context log-session \
  --source chatgpt \
  --title "ATLAS architecture review" \
  --project ATLAS \
  --origin "ChatGPT Desktop" \
  --summary "Reviewed ATLAS architecture tradeoffs." \
  --transcript-file /path/to/transcript.md
```

From stdin:

```bash
pbpaste | vault-context log-session \
  --source gemini \
  --title "Gemini ATLAS critique" \
  --project ATLAS \
  --origin "Gemini CLI"
```

## Local Capture Server

Run in the foreground:

```bash
vault-context serve-capture
```

Install as a macOS background service:

```bash
vault-context install-capture-agent
```

Endpoint:

```text
POST http://127.0.0.1:8765/capture
```

Payload:

```json
{
  "source": "chatgpt",
  "title": "Desktop capture",
  "origin": "https://chatgpt.com/c/example",
  "project": "ATLAS",
  "summary": "Captured a useful architecture thread.",
  "transcript": "**You:** ...\n\n**ChatGPT:** ...",
  "key_takeaways": [],
  "decisions": [],
  "open_questions": [],
  "next_actions": []
}
```

Curl test:

```bash
curl -X POST http://127.0.0.1:8765/capture \
  -H 'Content-Type: application/json' \
  -d '{"source":"chatgpt","title":"Capture test","transcript":"hello","origin":"manual"}'
```

## Browser Capture

Install a userscript manager such as Tampermonkey or Violentmonkey, then add:

```text
scripts/vault_context_capture.user.js
```

The script runs on ChatGPT, Gemini, and Claude web pages. It adds a `Log to Vault` button and a `Cmd+Shift+L` shortcut.

Recommended flow:

1. Select the useful part of the chat transcript.
2. Click `Log to Vault`.
3. Enter a title, optional project, and optional summary.
4. The script posts to `http://127.0.0.1:8765/capture`.

If no text is selected, the script asks before capturing visible page text. Very large captures are truncated only after confirmation.

This is the lowest-friction current path for ChatGPT and Gemini browser sessions. It does not give the browser shell access or arbitrary vault write access; it can only POST a session payload to the local capture endpoint.

## Storage

Default destinations:

- Claude: `Main_Vault/00_Inbox/Chats/Claude/`
- ChatGPT: `Main_Vault/00_Inbox/Chats/ChatGPT/`
- Gemini: `Main_Vault/00_Inbox/Chats/Gemini/`
- Codex: `Main_Vault/00_Inbox/Chats/Codex/`
- Local: `Main_Vault/00_Inbox/Chats/Local/`

Each capture includes frontmatter, structured summary sections, transcript, and optional daily-note append.

## Safety

This is an allowlisted write path. The capture tool can write only to configured session-log folders under the vault root. It cannot execute shell commands or write arbitrary paths.
