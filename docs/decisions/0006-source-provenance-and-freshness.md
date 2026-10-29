# 0006: External provenance and freshness state

Status: accepted, 2026-10-21. Owner authorized K2 takeover and completion in chat.

Context: capture and retrieval exist, but derived conclusions need traceable source versions and invalidation without rewriting notes. K2's returned implementation needed filesystem containment, typed recovery failures and working lint/types.

Decision: keep an append-first, fsynced transition log and atomic manifest outside the vault. Track only configured Markdown prefixes. Proposed/accepted derivations become stale when dependencies change or disappear; source and derivation history remain. The librarian calls the scan after a changed fingerprint. Defaults remain disabled. Cloud reports use the existing sensitivity classifier and hide missing/restricted paths. CLI uses local deterministic operations; no inference, network, canonical note write or new dependency is introduced.

Use a small pure `provenance_schema.py` helper for schema validation and the shared error, re-exported from `provenance.py` so the public contract remains intact. This keeps the operational module below the inherited 420-line limit without compressing code. The parent reviewed and extracted this helper from Gemini's textual patch after native headless tools were denied. No floor or authentication policy was changed.

Consequences: log replay repairs an interrupted manifest update; a torn final JSON line is recoverable, other malformed records raise a typed error. State cannot be placed inside the vault. Scope symlinks are rejected. Counts can be reported without raw paths. This is source versioning, not semantic compilation or automatic answer filing. Use a fresh state directory when changing tracked scope; serialize provenance commands in this first version. A multi-writer transaction guarantee is not claimed.

Rollback: revert the K2 landing commit and remove only the `librarian.provenance` key from the ignored local configuration. Retain external state as recoverable history.
