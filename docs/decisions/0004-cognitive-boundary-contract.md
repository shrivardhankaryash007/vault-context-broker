# ADR 0004: Adopt a strict local cognitive-record contract

**Status:** accepted
**Date:** 2026-07-12

## Context

Cosmos and Command Centre need to consume the same provenance-bearing account
of evidence, interpretation, recommendation, owner decision, action, observed
outcome, and correction. `universe.json` is a derived render ephemeris and
must not become that canonical record. The local context broker already owns
retrieval and sensitivity boundaries, so it is the appropriate future owner.

## Decision

The broker defines `cognitive-record-v0` as a strict, local-only wire contract.
It uses opaque namespaced UUIDv7 identifiers, content-free source aliases plus
hashes, immutable typed relations, separate sensitivity and release-class
axes, and owner/deterministic authority rules. The initial slice exposes no
storage, MCP tool, API, transport, UI, model invocation, or real-vault data.

Mirror-sealed records must always use `frontier_forbidden`. Models may author
interpretations, hypotheses, and recommendations, but never facts, decisions,
actions, observed outcomes, or corrections. Corrections require both a
superseded record and evidence or an observed outcome.

## Consequences

Future Cosmos and Command Centre integrations can validate the same synthetic
closed loop without duplicating authority or privacy semantics. Persistence,
projection, local mission handoff, egress policy, packet preview, and return
quarantine remain separate approved slices. This ADR adds no runtime
dependency or behaviour.
