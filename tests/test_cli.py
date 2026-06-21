"""Integration tests for the ``slack-glue`` Typer CLI.

These exercise the CLI the way a user / automation pipeline would: through
Typer's :class:`CliRunner`, asserting exit codes, the human-mode Rich output,
and the ``--json`` automation contract (exactly one JSON object on stdout and
nothing else). The pure helpers (``_route_and_execute`` / ``_build_model`` /
``_serve_instructions``) are also tested directly, since they are importable
without the Typer/Rich extra.

Everything is **hermetic**: no network, no live Slack, no live ShotGrid, no live
LLM. Routing runs against replykit's :class:`~replykit.ScriptedModel` (a canned
``emit_query`` block) or :class:`~replykit.MockModel`; the database is the
packaged JSON fixture.
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from slack_glue import load_fixture
from slack_glue.cli import (
    _build_model,
    _CliError,
    _route_and_execute,
    _serve_instructions,
    app,
)

runner = CliRunner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _one_json_object(stdout: str) -> dict:
    """Assert stdout is exactly one JSON object (the automation contract)."""
    nonblank = [line for line in stdout.splitlines() if line.strip()]
    assert len(nonblank) == 1, f"expected exactly one stdout line, got {nonblank!r}"
    obj = json.loads(stdout)
    assert isinstance(obj, dict)
    return obj


def _emit(**fields: str) -> str:
    """Build a well-formed ``emit_query`` @reply block for --script."""
    lines = ["@reply name=emit_query"]
    for key, value in fields.items():
        lines.append(f"{key} = {value}")
    lines.append("@end")
    return "\n".join(lines)


# A canonical valid block: approved VFX shots, reel 3, greenscreen (2 fixture hits).
GREENSCREEN_BLOCK = _emit(
    endpoint="/api/v1/shots",
    status="approved",
    reel="3",
    dept="vfx",
    tags="greenscreen",
)


# ---------------------------------------------------------------------------
# Top-level wiring / help
# ---------------------------------------------------------------------------


def test_no_args_shows_help() -> None:
    result = runner.invoke(app, [])
    assert "ask" in result.stdout
    assert "serve" in result.stdout


def test_ask_help_documents_flags() -> None:
    result = runner.invoke(app, ["ask", "--help"])
    assert result.exit_code == 0
    for flag in ("--model", "--script", "--json"):
        assert flag in result.stdout


def test_serve_help_documents_flags() -> None:
    result = runner.invoke(app, ["serve", "--help"])
    assert result.exit_code == 0
    for flag in ("--check", "--json"):
        assert flag in result.stdout


# ---------------------------------------------------------------------------
# _build_model — backend resolution (pure helper)
# ---------------------------------------------------------------------------


def test_build_model_scripted_is_a_replykit_model() -> None:
    from replykit import Model

    assert isinstance(_build_model("scripted", script=[GREENSCREEN_BLOCK]), Model)


def test_build_model_mock_is_a_replykit_model() -> None:
    from replykit import Model

    assert isinstance(_build_model("mock"), Model)


def test_build_model_unknown_backend_raises_cli_error() -> None:
    with pytest.raises(_CliError) as exc:
        _build_model("telepathy")
    assert "unknown --model" in str(exc.value)


def test_build_model_default_scripted_still_routes() -> None:
    # With no -s script, the scripted backend replays a built-in sample query, so
    # the CLI still does something useful with zero configuration.
    model = _build_model("scripted")
    payload = _route_and_execute("anything", model)
    assert payload["ok"] is True


def test_build_model_mock_routes_end_to_end() -> None:
    # The mock backend's response callable emits the sample query on the first
    # turn and a final answer once tool results are fed back — a full agent loop.
    model = _build_model("mock")
    payload = _route_and_execute("anything", model)
    assert payload["ok"] is True
    assert payload["result"]["count"] == 2


def test_build_model_provider_without_sdk_raises_cli_error() -> None:
    # The provider extras are not installed in the hermetic dev env, so selecting
    # one must surface a clean _CliError (a pip hint), never a bare traceback —
    # this is what preserves the no-LLM default path.
    for backend in ("anthropic", "openai"):
        with pytest.raises(_CliError) as exc:
            _build_model(backend)
        assert "package" in str(exc.value).lower() or "install" in str(exc.value).lower()


# ---------------------------------------------------------------------------
# _route_and_execute — the ask unit seam (pure helper)
# ---------------------------------------------------------------------------


def test_route_and_execute_valid_query_returns_records() -> None:
    model = _build_model("scripted", script=[GREENSCREEN_BLOCK])
    payload = _route_and_execute("approved vfx shots reel 3 greenscreen", model)
    assert payload["ok"] is True
    assert payload["query"]["endpoint"] == "/api/v1/shots"
    assert payload["result"]["count"] == 2
    ids = {r["id"] for r in payload["result"]["records"]}
    assert ids == {"SHOT-0101", "SHOT-0102"}
    # Telemetry from the (hermetic) model call is surfaced.
    assert payload["telemetry"]["calls"] >= 1


def test_route_and_execute_human_text_is_slack_formatted() -> None:
    model = _build_model("scripted", script=[GREENSCREEN_BLOCK])
    payload = _route_and_execute("q", model)
    assert payload["text"].startswith("Found 2 records on /api/v1/shots")
    assert "• SHOT-0101" in payload["text"]


def test_route_and_execute_zero_match_says_no_records() -> None:
    # A valid query that matches nothing: omit-status assets (none in the fixture).
    block = _emit(endpoint="/api/v1/assets", status="omit")
    model = _build_model("scripted", script=[block])
    payload = _route_and_execute("omitted assets", model)
    assert payload["ok"] is True
    assert payload["result"]["count"] == 0
    assert payload["text"].startswith("No records matched on /api/v1/assets")


def test_route_and_execute_bad_enum_clarifies() -> None:
    block = _emit(endpoint="/api/v1/shots", status="greenlit")
    model = _build_model("scripted", script=[block])
    payload = _route_and_execute("greenlit shots", model)
    assert payload["ok"] is False
    codes = {i["code"] for i in payload["issues"]}
    assert "bad_enum" in codes
    assert "greenlit shots" in payload["text"]  # the request is echoed back
    assert "rephrase" in payload["text"].lower()


def test_route_and_execute_unknown_field_clarifies() -> None:
    # ``sequence`` is a valid emit_query tool arg, but it is NOT a filterable
    # field on the assets endpoint (only shots have a sequence). The model can
    # emit it; the deterministic schema validator is what rejects it.
    block = _emit(endpoint="/api/v1/assets", sequence="RDR")
    model = _build_model("scripted", script=[block])
    payload = _route_and_execute("assets in sequence RDR", model)
    assert payload["ok"] is False
    assert {i["code"] for i in payload["issues"]} == {"unknown_field"}
    # raw_intent is always present for debugging, even on rejection.
    assert payload["raw_intent"]["filters"]["sequence"] == "RDR"


def test_route_and_execute_no_query_when_model_emits_none() -> None:
    # A plain-text turn (no emit_query block) -> deterministic no_query outcome.
    model = _build_model("scripted", script=["Just chatting, no tool call."])
    payload = _route_and_execute("hello", model)
    assert payload["ok"] is False
    assert {i["code"] for i in payload["issues"]} == {"no_query"}


def test_route_and_execute_accepts_injected_db() -> None:
    # The db is injectable so the seam can be exercised against a custom fixture.
    db = load_fixture()
    model = _build_model("scripted", script=[GREENSCREEN_BLOCK])
    payload = _route_and_execute("q", model, db=db)
    assert payload["ok"] is True


# ---------------------------------------------------------------------------
# ask — JSON mode (automation contract)
# ---------------------------------------------------------------------------


def test_ask_json_is_single_object_valid_query() -> None:
    result = runner.invoke(app, ["ask", "q", "-s", GREENSCREEN_BLOCK, "--json"])
    assert result.exit_code == 0
    obj = _one_json_object(result.stdout)
    assert obj["ok"] is True
    assert obj["result"]["count"] == 2
    assert obj["query"]["filters"]["reel"] == 3  # int-coerced by the validator


def test_ask_json_clarify_on_bad_enum() -> None:
    block = _emit(endpoint="/api/v1/shots", status="greenlit")
    result = runner.invoke(app, ["ask", "greenlit shots", "-s", block, "--json"])
    assert result.exit_code == 0  # a clarify is a *successful* run, not an error
    obj = _one_json_object(result.stdout)
    assert obj["ok"] is False
    assert any(i["field"] == "status" for i in obj["issues"])


def test_ask_json_no_query_outcome() -> None:
    result = runner.invoke(app, ["ask", "hi", "-s", "plain text answer", "--json"])
    assert result.exit_code == 0
    obj = _one_json_object(result.stdout)
    assert obj["ok"] is False
    assert obj["issues"][0]["code"] == "no_query"


def test_ask_json_assets_endpoint() -> None:
    block = _emit(endpoint="/api/v1/assets", asset_type="character", status="approved")
    result = runner.invoke(app, ["ask", "approved characters", "-s", block, "--json"])
    obj = _one_json_object(result.stdout)
    assert obj["ok"] is True
    assert obj["result"]["endpoint"] == "/api/v1/assets"
    assert obj["result"]["count"] == 1
    assert obj["result"]["records"][0]["id"] == "AST-HERO-01"


def test_ask_json_tags_are_anded() -> None:
    # Two tags -> only records carrying BOTH match (tag-superset AND semantics).
    block = _emit(endpoint="/api/v1/shots", tags="greenscreen,hero")
    result = runner.invoke(app, ["ask", "hero greenscreen shots", "-s", block, "--json"])
    obj = _one_json_object(result.stdout)
    assert obj["ok"] is True
    assert obj["result"]["count"] == 1
    assert obj["result"]["records"][0]["id"] == "SHOT-0101"


# ---------------------------------------------------------------------------
# ask — human mode
# ---------------------------------------------------------------------------


def test_ask_human_renders_records_and_telemetry() -> None:
    result = runner.invoke(app, ["ask", "q", "-s", GREENSCREEN_BLOCK])
    assert result.exit_code == 0
    assert "Found 2 records" in result.stdout
    assert "SHOT-0101" in result.stdout
    assert "Telemetry" in result.stdout


def test_ask_human_clarify_path() -> None:
    block = _emit(endpoint="/api/v1/shots", status="greenlit")
    result = runner.invoke(app, ["ask", "greenlit", "-s", block])
    assert result.exit_code == 0
    assert "Could not route" in result.stdout
    assert "status" in result.stdout


def test_ask_human_zero_match_renders_no_records_line() -> None:
    # A valid query that matches nothing: the human render shows the "no records"
    # text and no record table (the records branch is skipped).
    block = _emit(endpoint="/api/v1/assets", status="omit")
    result = runner.invoke(app, ["ask", "omitted assets", "-s", block])
    assert result.exit_code == 0
    assert "No records matched on /api/v1/assets" in result.stdout


def test_cell_renderer_handles_lists_none_and_scalars() -> None:
    from slack_glue.cli import _cell, _record_columns

    assert _cell(["a", "b"]) == "a, b"
    assert _cell(None) == ""
    assert _cell(3) == "3"
    # Column order is stable: preferred fields first, extras sorted after.
    cols = _record_columns([{"id": "X", "status": "approved", "zeta": 1}])
    assert cols[0] == "id"
    assert cols.index("status") < cols.index("zeta")


# ---------------------------------------------------------------------------
# ask — error paths
# ---------------------------------------------------------------------------


def test_ask_unknown_model_json_errors_cleanly() -> None:
    result = runner.invoke(app, ["ask", "q", "--model", "telepathy", "--json"])
    assert result.exit_code == 1
    obj = _one_json_object(result.stdout)
    assert "unknown --model" in obj["error"]


def test_ask_unknown_model_human_errors_to_stderr() -> None:
    result = runner.invoke(app, ["ask", "q", "--model", "telepathy"])
    assert result.exit_code == 1
    # The error must not pollute stdout (the automation channel).
    assert result.stdout.strip() == ""


# ---------------------------------------------------------------------------
# serve — offline wiring instructions
# ---------------------------------------------------------------------------


def test_serve_instructions_is_offline_and_complete() -> None:
    payload = _serve_instructions()
    assert payload["transport"] == "offline"
    env_names = {e["name"] for e in payload["env"]}
    assert "SLACK_BOT_TOKEN" in env_names
    assert "SLACK_SIGNING_SECRET" in env_names
    assert payload["wiring"]  # non-empty list of steps
    assert "/api/v1/shots" in payload["endpoints"]
    # "check" is only present when explicitly requested.
    assert "check" not in payload


def test_serve_instructions_check_runs_pipeline_offline() -> None:
    payload = _serve_instructions(check=True)
    assert "check" in payload
    check = payload["check"]
    assert check["ok"] is True
    assert check["reply"]["kind"] == "results"
    assert check["reply"]["payload"]["count"] >= 1


def test_serve_json_is_single_object() -> None:
    result = runner.invoke(app, ["serve", "--json"])
    assert result.exit_code == 0
    obj = _one_json_object(result.stdout)
    assert obj["transport"] == "offline"


def test_serve_check_json_includes_smoke_reply() -> None:
    result = runner.invoke(app, ["serve", "--check", "--json"])
    assert result.exit_code == 0
    obj = _one_json_object(result.stdout)
    assert obj["check"]["reply"]["kind"] == "results"


def test_serve_human_mode_prints_wiring() -> None:
    result = runner.invoke(app, ["serve"])
    assert result.exit_code == 0
    assert "SLACK_BOT_TOKEN" in result.stdout
    assert "Events API" in result.stdout
    # serve opens no socket: it returns promptly (no hang) with exit 0.


def test_serve_human_check_prints_outcome() -> None:
    result = runner.invoke(app, ["serve", "--check"])
    assert result.exit_code == 0
    assert "smoke check" in result.stdout.lower()
    assert "results" in result.stdout


# ---------------------------------------------------------------------------
# conftest fixtures stay wired (router/db seams used by the wider suite)
# ---------------------------------------------------------------------------


def test_scripted_router_fixture_routes(scripted_router) -> None:
    router = scripted_router(
        endpoint="/api/v1/shots", status="approved", reel="3", dept="vfx", tags="greenscreen"
    )
    outcome = router.route("approved vfx reel 3 greenscreen shots")
    assert outcome.ok is True
    assert outcome.query.endpoint == "/api/v1/shots"


def test_sample_event_fixture_shape(sample_event) -> None:
    assert sample_event["event"]["type"] == "app_mention"
    assert "<@U0BOTID>" in sample_event["event"]["text"]
