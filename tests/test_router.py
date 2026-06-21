"""Unit tests for the router — the single model boundary plus deterministic glue.

Routing is exercised entirely with :class:`replykit.ScriptedModel`, so there is
no provider and no network. The model proposes (one ``emit_query`` call); the
deterministic parser + schema validator dispose (accept vs clarify). Tests pin:
the happy path, invalid emitted queries (no second model call), a turn with no
``emit_query`` at all, the comma-split / unknown-key folding of
``parse_intent_payload``, and telemetry recording.
"""

from __future__ import annotations

from replykit import ScriptedModel, ToolRegistry

from slack_glue.router import (
    EMIT_TOOL,
    ROUTING_PREAMBLE,
    RouteOutcome,
    Router,
    build_routing_registry,
    parse_intent_payload,
)
from slack_glue.schema import IntentQuery

# --- build_routing_registry ------------------------------------------------


def test_registry_exposes_exactly_one_emit_query_tool() -> None:
    registry = build_routing_registry()
    assert isinstance(registry, ToolRegistry)
    assert len(registry) == 1
    assert EMIT_TOOL in registry
    spec = registry.specs()[0]
    assert spec.name == EMIT_TOOL
    arg_names = {a.name for a in spec.args}
    assert {"endpoint", "status", "reel", "dept", "tags", "asset_type", "sequence"} == arg_names
    # All args optional so the model can emit only the fields it needs.
    assert all(not a.required for a in spec.args)


# --- parse_intent_payload (pure string work, no model) ---------------------


def test_parse_splits_tags_on_commas() -> None:
    raw = parse_intent_payload({"endpoint": "/api/v1/shots", "tags": "greenscreen, hero ,crowd"})
    assert raw == {
        "endpoint": "/api/v1/shots",
        "filters": {"tags": ["greenscreen", "hero", "crowd"]},
    }


def test_parse_drops_empty_args() -> None:
    raw = parse_intent_payload(
        {"endpoint": "/api/v1/shots", "status": "approved", "dept": "", "reel": "  "}
    )
    assert raw == {"endpoint": "/api/v1/shots", "filters": {"status": "approved"}}


def test_parse_folds_unknown_keys_into_filters() -> None:
    # An unknown key is folded through so the validator can report it.
    raw = parse_intent_payload({"endpoint": "/api/v1/shots", "frame_rate": "24"})
    assert raw["filters"] == {"frame_rate": "24"}


def test_parse_empty_tags_yields_no_tags_filter() -> None:
    raw = parse_intent_payload({"endpoint": "/api/v1/shots", "tags": " , , "})
    assert raw == {"endpoint": "/api/v1/shots", "filters": {}}


def test_parse_missing_endpoint_is_empty_string() -> None:
    raw = parse_intent_payload({"status": "approved"})
    assert raw["endpoint"] == ""
    assert raw["filters"] == {"status": "approved"}


def test_parse_skips_none_values() -> None:
    # Defensive: a None arg is not a constraint and is dropped, not folded.
    raw = parse_intent_payload({"endpoint": "/api/v1/shots", "status": None})
    assert raw == {"endpoint": "/api/v1/shots", "filters": {}}


def test_parse_accepts_pre_split_tag_list() -> None:
    # Defensive: if tags arrives already a list (not a comma string), keep it.
    raw = parse_intent_payload({"endpoint": "/api/v1/shots", "tags": ["a", "b"]})
    assert raw == {"endpoint": "/api/v1/shots", "filters": {"tags": ["a", "b"]}}


# --- Router.route ----------------------------------------------------------


def test_route_happy_path(scripted_router) -> None:
    router = scripted_router(
        endpoint="/api/v1/shots", status="approved", dept="vfx", reel="3", tags="greenscreen"
    )
    outcome = router.route("approved vfx shots from reel 3 with green screen")
    assert isinstance(outcome, RouteOutcome)
    assert outcome.ok is True
    assert isinstance(outcome.query, IntentQuery)
    assert outcome.query.endpoint == "/api/v1/shots"
    assert outcome.query.filters == {
        "status": "approved",
        "dept": "vfx",
        "reel": 3,
        "tags": ["greenscreen"],
    }
    assert outcome.issues == []
    assert outcome.raw_intent["endpoint"] == "/api/v1/shots"


def test_route_records_telemetry(scripted_router) -> None:
    router = scripted_router(endpoint="/api/v1/shots", status="approved")
    outcome = router.route("approved shots")
    # At least the routing call is recorded; cost/tokens accounted.
    assert len(outcome.telemetry.calls) >= 1
    assert outcome.telemetry.total_input_tokens > 0


def test_route_invalid_emitted_query_no_second_model_call(emit_block) -> None:
    # The model emits a single bad-enum query; validation rejects it. Only the
    # one emit turn + a terminating answer are scripted — no repair / re-ask.
    block = emit_block(endpoint="/api/v1/shots", status="greenlit")
    model = ScriptedModel([block, "Done."])
    router = Router(model)
    outcome = router.route("greenlit shots")
    assert outcome.ok is False
    assert outcome.query is None
    assert [i.code for i in outcome.issues] == ["bad_enum"]
    # The raw intent the model emitted is preserved for debugging.
    assert outcome.raw_intent["filters"] == {"status": "greenlit"}


def test_route_unknown_endpoint_rejected(emit_block) -> None:
    block = emit_block(endpoint="/api/v1/widgets")
    router = Router(ScriptedModel([block, "Done."]))
    outcome = router.route("widgets please")
    assert outcome.ok is False
    assert [i.code for i in outcome.issues] == ["unknown_endpoint"]


def test_route_no_emit_query_block_yields_no_query_issue() -> None:
    # The model never emits emit_query — single deterministic no_query issue.
    router = Router(ScriptedModel(["I'm not sure what you need."]))
    outcome = router.route("hi there")
    assert outcome.ok is False
    assert [i.code for i in outcome.issues] == ["no_query"]
    assert outcome.query is None
    assert outcome.raw_intent == {}


def test_route_uses_last_emit_query_when_several(emit_block) -> None:
    first = emit_block(endpoint="/api/v1/shots", status="pending")
    second = emit_block(endpoint="/api/v1/shots", status="approved")
    # Two emit turns then a final answer; the last emit wins.
    router = Router(ScriptedModel([first, second, "Done."]))
    outcome = router.route("changed my mind, approved shots")
    assert outcome.ok is True
    assert outcome.query is not None
    assert outcome.query.filters == {"status": "approved"}


def test_outcome_as_dict_is_json_serializable(scripted_router) -> None:
    import json

    router = scripted_router(endpoint="/api/v1/shots", status="approved")
    outcome = router.route("approved shots")
    payload = outcome.as_dict()
    # Round-trips through JSON without error.
    json.dumps(payload)
    assert payload["ok"] is True
    assert payload["query"]["endpoint"] == "/api/v1/shots"


def test_route_prompt_includes_preamble_and_request() -> None:
    model = ScriptedModel(["no emit here"])
    router = Router(model)
    router.route("find the hero asset")
    # The model recorded the prompt it received.
    assert ROUTING_PREAMBLE.split("\n")[0] in model.calls[0]
    assert "find the hero asset" in model.calls[0]


def test_router_accepts_injected_registry() -> None:
    registry = build_routing_registry()
    router = Router(ScriptedModel(["x"]), registry=registry)
    assert router.registry is registry
