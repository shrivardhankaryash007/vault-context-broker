# 0003 Cross-LLM Session Capture

## Status

Accepted

## Context

Important thinking increasingly happens inside Claude, ChatGPT, Gemini, Codex, and local LLM sessions. If session outputs remain siloed in platform histories, later LLMs lose continuity and repeat work. Existing Claude session logs are high-quality indicators because they capture context, decisions, open threads, and next-session agenda.

## Decision

Add an allowlisted session-capture write path. New captures land under configured `00_Inbox/Chats/<Source>/` folders with a universal schema. The handoff reader also recognizes existing structured Claude logs in `01-Sessions/` and `08-Sessions/` so prior high-quality logs remain first-class context.

## Consequences

- Claude, ChatGPT, Gemini, Codex, and local clients can share a common thinking trail.
- New session logs refresh the index immediately.
- Existing Claude logs become available to other LLMs through `get_session_handoff`.
- Writes are narrow and auditable, but this intentionally expands v0 beyond read-only retrieval.
