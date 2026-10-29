# ADR 0007: Isolated synthetic retrieval gate

Status: accepted, class 1. Date: 2026-10-26.

## Context

Oldest unresolved engineering queue loop 4bd73909 asks for better memory retrieval
quality gates. Existing individual tests cover ranking and clearance but expose
no installed end-to-end diagnostic. The owner authorized an autonomous queued
task through observed operation on 2026-10-26.

## Decision

Add a fixed, config-independent `vault-context benchmark-retrieval` command using
a disposable synthetic vault, actual index/search/context consumers and extractive
summarization. Run it in existing CI. Retain keyword ranking and the clearance
policy unchanged. A benchmark is a smaller reversible step than adding unmeasured
hybrid/graph ranking or using private content to evaluate quality.

Explicitly override vault/index/sensitivity/report paths; do not load user config,
use network inference, install background work, or modify actual vault data.
Cloud-negative checks require local and useful-open positive controls. Report
synthetic assertions and actual paths, never measured real-vault accuracy.

## Consequences and verification

Thirteen named checks pass in two actual installed CLI runs. Twelve new tests
prove regressions are detected, including missing ranking boosts with and without
FTS5, serialized context leaks and stale refresh. Full project gate passes with
168 tests. Independent spec and code-quality review pass. Existing protected-core
checks remain intact. Actual client config reload is still a separate owner task.

Reversal: `git revert <delivery commit containing this ADR>`; no data migration,
host configuration or service rollback is required. See the delivery commit via
`git log -1 -- docs/decisions/0007-synthetic-retrieval-gate.md`.
