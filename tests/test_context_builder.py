"""Context builder tests."""

from __future__ import annotations

from vault_context_mcp.context_builder import build_context_pack
from vault_context_mcp.index_store import build_index


def test_context_pack_has_valid_schema_and_sources(test_config) -> None:  # type: ignore[no-untyped-def]
    build_index(test_config)

    pack = build_context_pack(
        test_config, "Continue ATLAS architecture", mode="standard", project="ATLAS"
    )

    assert pack.task == "Continue ATLAS architecture"
    assert pack.mode == "standard"
    assert pack.generated_at
    assert pack.context_summary
    assert pack.relevant_sources
    assert pack.current_state
    assert pack.prior_decisions
    assert pack.open_questions
    assert pack.key_facts or pack.constraints
    assert pack.confidence > 0


def test_context_pack_standard_mode_stays_concise(test_config) -> None:  # type: ignore[no-untyped-def]
    build_index(test_config)

    pack = build_context_pack(
        test_config, "Continue ATLAS architecture", mode="standard", project="ATLAS"
    )

    assert len(pack.model_dump_json().split()) < 3000


def test_context_pack_excludes_restricted_sources_under_cloud_clearance(test_config) -> None:  # type: ignore[no-untyped-def]
    build_index(test_config)

    cloud_pack = build_context_pack(
        test_config, "widget gear actuator", mode="deep", clearance="cloud"
    )
    local_pack = build_context_pack(
        test_config, "widget gear actuator", mode="deep", clearance="local"
    )

    assert all(
        source.path != "ACME/widget-design-notes.md" for source in cloud_pack.relevant_sources
    )
    assert any(
        source.path == "ACME/widget-design-notes.md" for source in local_pack.relevant_sources
    )


def test_context_pack_defaults_to_cloud_clearance(test_config) -> None:  # type: ignore[no-untyped-def]
    build_index(test_config)

    pack = build_context_pack(test_config, "widget gear actuator", mode="deep")

    assert all(source.path != "ACME/widget-design-notes.md" for source in pack.relevant_sources)
