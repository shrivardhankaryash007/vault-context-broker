---
type: session
domain: technical
status: active
created: 2026-04-22
tags:
  - domain/technical
  - project/orion
  - orion/session
  - system/claude
---

# 2026-04-22 Session 03 — Claude-Vault Bridge Setup

## Context

Wanted vault skills available as callable commands in Claude Code and as live skills in claude.ai.

## Key Insights

- Claude Code slash commands and claude.ai are separate environments.
- Obsidian vault skills doc = definition layer; Claude Code commands = execution layer.

## Decisions Made

- Use natural language to trigger vault skills in claude.ai.

## Open Threads (parked — do not lose)

- Confirm MCP write permission in claude.ai.

## Next Session Agenda

- Test full write loop: draft -> approve -> write to vault.
