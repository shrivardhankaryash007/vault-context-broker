# Troubleshooting

## Config Not Found

Copy the example config and edit the vault root:

```bash
cp config.example.yaml config.yaml
export VAULT_CONTEXT_CONFIG="$(pwd)/config.yaml"
```

## No Search Results

Run:

```bash
vault-context index
vault-context search "current state"
```

Confirm that your vault contains Markdown files and that important directories are not listed under `ignore_dirs`.

## Claude Desktop Does Not Show Tools

- Run `vault-context doctor`.
- Confirm Claude Desktop was restarted.
- Confirm the Python path in Claude's config is absolute.
- Confirm `VAULT_CONTEXT_CONFIG` points to an existing YAML config.
- Validate Claude's JSON config.

## FTS5 Unavailable

The package falls back to SQLite `LIKE` search. Results may be less precise, but the broker remains functional.

## Librarian Watcher

Check whether the macOS background watcher is running:

```bash
launchctl print gui/$(id -u)/com.example.vault-context-mcp.librarian
```

Run a one-shot verification:

```bash
vault-context librarian-watch --once
```

Inspect logs:

```bash
tail -n 50 ~/.vault-context-mcp/librarian.log
tail -n 50 ~/.vault-context-mcp/librarian.err.log
```

## Capture Server

Check whether the capture server is running:

```bash
launchctl print gui/$(id -u)/com.example.vault-context-mcp.capture
curl http://127.0.0.1:8765/health
```

Inspect logs:

```bash
tail -n 50 ~/.vault-context-mcp/capture.log
tail -n 50 ~/.vault-context-mcp/capture.err.log
```
