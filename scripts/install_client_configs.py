#!/usr/bin/env python3
"""Install vault-context-mcp into local MCP-compatible clients."""

from __future__ import annotations

import json

from vault_context_mcp.cli import install_all_local_client_configs


def main() -> None:
    """Patch supported local client configs and print results."""

    print(json.dumps(install_all_local_client_configs(), indent=2))


if __name__ == "__main__":
    main()
