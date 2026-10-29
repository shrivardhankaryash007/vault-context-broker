#!/usr/bin/env python3
"""Patch Claude Desktop config for vault-context-mcp."""

from __future__ import annotations

import json

from vault_context_mcp.cli import install_claude_desktop_config


def main() -> None:
    """Run the installer and print final instructions."""

    result = install_claude_desktop_config()
    print(json.dumps(result, indent=2))
    print("Restart Claude Desktop after this change.")


if __name__ == "__main__":
    main()
