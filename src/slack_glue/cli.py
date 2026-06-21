"""The ``slack-glue`` command-line interface (Typer + Rich).

A thin, automation-friendly shell over the package. It is **not** imported by
``slack_glue/__init__.py`` and does **not** load at package import time, so
``import slack_glue`` stays free of Typer/Rich. Those deps live under the ``cli``
extra::

    pip install 'slack-glue[cli]'

Commands:

- ``slack-glue ask "<request>"`` — route a free-text request into a validated
  query, execute it against the mock ShotGrid, and print the matching records.
  Hermetic by default (replykit ``scripted``/``mock`` models, no network);
  ``--model openai``/``anthropic`` activate when the SDK + key are present.
- ``slack-glue serve`` — offline-safe. Prints exactly how to wire a real Slack
  app (env vars, event subscription, the ``app_mention`` handler) without
  opening any socket. With ``--check`` it runs a built-in sample ``app_mention``
  through the hermetic pipeline for a smoke check.

Every command supports ``--json`` for machine consumption: a single JSON object
on stdout and nothing else, so the CLI composes into agent pipelines.

The pure-logic helpers (``_route_and_execute``, ``_build_model``,
``_serve_instructions``) live at module scope below the Typer block so they are
importable and unit-testable even without the ``cli`` extra installed.
"""

from __future__ import annotations

import json
import sys
from typing import Any

from replykit import MockModel, ScriptedModel

from .database import Database, execute_query, load_fixture
from .formatting import (
    format_clarification,
    format_records_json,
    format_records_slack,
)
from .router import Router
from .schema import ENDPOINTS, FIELD_TYPES
from .slack import (
    REPLY_RESULTS,
    AppMentionEvent,
    handle_app_mention,
)

# The hermetic default ``emit_query`` script: a model that maps the *built-in*
# serve --check sample request onto a valid query. It is only the fallback used
# when ``ask`` is run with the default ``scripted`` backend and no -s script is
# supplied, so the CLI still does something useful with zero configuration.
_DEFAULT_EMIT = (
    "@reply name=emit_query\n"
    "endpoint = /api/v1/shots\n"
    "status = approved\n"
    "reel = 3\n"
    "dept = vfx\n"
    "tags = greenscreen\n"
    "@end"
)

# A representative Slack app_mention used by ``serve --check`` to smoke-test the
# whole deterministic pipeline offline.
_SAMPLE_MENTION_TEXT = "<@U0BOTID> get me all approved VFX shots from Reel 3 with green screen"
_SAMPLE_MENTION = AppMentionEvent(
    text=_SAMPLE_MENTION_TEXT,
    user="U0PRODUCER",
    channel="C0VFXCHAN",
    ts="1718900000.000100",
)


try:  # pragma: no cover - import wiring, exercised indirectly
    import typer
    from rich.console import Console
    from rich.table import Table
except ImportError as exc:  # pragma: no cover - only hit without the cli extra
    _MISSING = exc

    def main() -> None:  # noqa: D401 - thin shim
        """Entry point shim when the ``cli`` extra is not installed."""
        sys.stderr.write(
            "The slack-glue CLI requires the 'cli' extra. Install it with:\n"
            "    pip install 'slack-glue[cli]'\n"
        )
        raise SystemExit(1)

else:
    app = typer.Typer(
        name="slack-glue",
        help="Cross-department intent router: messy Slack request -> validated query -> results.",
        add_completion=False,
        no_args_is_help=True,
    )
    console = Console()
    err_console = Console(stderr=True)

    def _emit_json(payload: dict[str, Any]) -> None:
        """Print exactly one JSON object to stdout (automation contract)."""
        sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")

    @app.command()
    def ask(
        request: str = typer.Argument(..., help="The free-text production request to route."),
        model: str = typer.Option(
            "scripted",
            "--model",
            "-m",
            help="Routing backend: scripted | mock | openai | anthropic.",
        ),
        script: list[str] = typer.Option(
            None,
            "--script",
            "-s",
            help="For --model scripted: emit_query @reply block(s) to replay.",
        ),
        as_json: bool = typer.Option(False, "--json", help="Emit a single JSON object."),
    ) -> None:
        """Route + execute a request and print matching records (or clarify)."""
        try:
            backend = _build_model(model, script=script)
        except _CliError as exc:
            _fail(str(exc), as_json=as_json)
            return

        payload = _route_and_execute(request, backend)

        if as_json:
            _emit_json(payload)
            return

        _render_outcome(request, payload)

    @app.command()
    def serve(
        check: bool = typer.Option(
            False, "--check", help="Run a sample app_mention through the pipeline offline."
        ),
        as_json: bool = typer.Option(False, "--json", help="Emit a single JSON object."),
    ) -> None:
        """Offline-safe: print how to wire a real Slack app (no socket opened)."""
        payload = _serve_instructions(check=check)

        if as_json:
            _emit_json(payload)
            return

        _render_serve(payload)

    # -- Rich renderers (human mode only) ------------------------------------

    def _render_outcome(request: str, payload: dict[str, Any]) -> None:
        """Render an ``ask`` outcome as Rich tables / panels (human mode)."""
        if payload.get("ok"):
            result = payload["result"]
            console.print(payload["text"])
            records = result.get("records", [])
            if records:
                table = Table(title=f"{result['endpoint']} — {result['count']} match(es)")
                columns = _record_columns(records)
                for col in columns:
                    table.add_column(col)
                for rec in records:
                    table.add_row(*[_cell(rec.get(col)) for col in columns])
                console.print(table)
        else:
            console.print("[yellow]Could not route that request.[/yellow]")
            console.print(payload["text"])
        _render_telemetry(payload.get("telemetry", {}))

    def _render_serve(payload: dict[str, Any]) -> None:
        """Render the offline serve instructions (human mode)."""
        console.print("[bold]Wiring a real Slack app[/bold]")
        console.print("[dim]No socket is opened by this command.[/dim]\n")

        env_table = Table(title="Required environment", title_justify="left")
        env_table.add_column("variable")
        env_table.add_column("purpose")
        for var in payload["env"]:
            env_table.add_row(var["name"], var["purpose"])
        console.print(env_table)

        console.print("\n[bold]Events API wiring[/bold]")
        for step in payload["wiring"]:
            console.print(f"  • {step}")

        console.print("\n[bold]Handler[/bold]")
        console.print(f"  {payload['handler']}")

        if "check" in payload:
            chk = payload["check"]
            console.print("\n[bold]Offline smoke check[/bold]")
            console.print(f"  request:  {chk['request']}")
            console.print(f"  outcome:  [cyan]{chk['reply']['kind']}[/cyan]")
            console.print(chk["reply"]["text"])

    def _render_telemetry(telemetry: dict[str, Any]) -> None:
        """Render replykit token/cost telemetry as a small Rich table."""
        if not telemetry:
            return
        table = Table(title="Telemetry", title_justify="left")
        table.add_column("metric")
        table.add_column("value", justify="right")
        table.add_row("model calls", str(telemetry.get("calls", 0)))
        table.add_row("input tokens", str(telemetry.get("total_input_tokens", 0)))
        table.add_row("output tokens", str(telemetry.get("total_output_tokens", 0)))
        cost = telemetry.get("total_cost_usd", 0.0)
        table.add_row("estimated cost (USD)", f"${cost:.6f}")
        console.print(table)

    def main() -> None:  # noqa: D401 - Typer entry point
        """Console-script entry point."""
        app()


# ---------------------------------------------------------------------------
# Pure logic helpers (no Typer/Rich) — importable and unit-testable directly.
# ---------------------------------------------------------------------------


class _CliError(Exception):
    """A user-facing CLI configuration error (bad --model, etc.)."""


def _build_model(backend: str, *, script: list[str] | None = None) -> Any:
    """Resolve a ``--model`` choice into a concrete replykit model.

    ``scripted`` / ``mock`` are hermetic; ``openai`` / ``anthropic`` import their
    replykit adapter lazily and raise a clear :class:`_CliError` when the SDK is
    absent — preserving the no-LLM default path.
    """
    name = (backend or "").lower()
    if name == "scripted":
        # A scripted model replays emit_query blocks. The default (no -s) replays
        # the built-in sample then a plain-text turn so the agent loop terminates.
        if script:
            responses: list[str] = list(script)
            # Ensure the agent loop terminates: append a final plain-text turn.
            responses.append("Done.")
        else:
            responses = [_DEFAULT_EMIT, "Done."]
        return ScriptedModel(responses)
    if name in ("mock", "offline", "default"):
        # A MockModel that always emits the default query block on its first turn
        # and a final answer once tool results are fed back.
        def _respond(prompt: str) -> str:
            if "Tool results:" in prompt:
                return "Done."
            return _DEFAULT_EMIT

        return MockModel(_respond)
    if name == "anthropic":
        from replykit import AnthropicModel, MissingDependencyError

        try:
            return AnthropicModel()
        except MissingDependencyError as exc:  # pragma: no cover - needs SDK absence
            raise _CliError(str(exc)) from exc
    if name == "openai":
        from replykit import MissingDependencyError, OpenAIModel

        try:
            return OpenAIModel()
        except MissingDependencyError as exc:  # pragma: no cover - needs SDK absence
            raise _CliError(str(exc)) from exc
    raise _CliError(f"unknown --model {backend!r}; choose scripted|mock|openai|anthropic")


def _route_and_execute(
    request: str,
    model: Any,
    db: Database | None = None,
) -> dict[str, Any]:
    """Route a request and (if valid) execute it; return a ``--json`` payload.

    Pure orchestration over :class:`Router` + the deterministic executor +
    formatters. Returns the same structured dict the CLI prints, so it is the
    single unit-test seam for the ``ask`` command's behavior.

    On a valid query: ``{"ok": True, "query", "result", "text", "telemetry"}``
    where ``result`` is :func:`format_records_json` output and ``text`` is the
    Slack-style plain-text render.

    On validation issues: ``{"ok": False, "issues", "raw_intent", "text",
    "telemetry"}`` where ``text`` is the deterministic ask-to-clarify message.
    """
    if db is None:
        db = load_fixture()

    router = Router(model)
    outcome = router.route(request)
    telemetry = outcome.telemetry.as_dict()

    if outcome.ok and outcome.query is not None:
        result = execute_query(outcome.query, db)
        return {
            "ok": True,
            "request": request,
            "query": outcome.query.as_dict(),
            "result": format_records_json(result),
            "text": format_records_slack(result),
            "telemetry": telemetry,
        }

    return {
        "ok": False,
        "request": request,
        "raw_intent": outcome.raw_intent,
        "issues": [
            {"code": i.code, "field": i.field, "message": i.message} for i in outcome.issues
        ],
        "text": format_clarification(outcome.issues, request),
        "telemetry": telemetry,
    }


def _serve_instructions(*, check: bool = False) -> dict[str, Any]:
    """Build the offline ``serve`` payload: wiring instructions (+ optional check).

    Deterministic. Describes the env vars and Slack Events-API wiring a real
    deployment needs; with ``check=True`` also runs a built-in sample
    ``app_mention`` through the hermetic pipeline and includes the reply.

    Opens no socket and makes no network call: the model used by the smoke check
    is a hermetic :class:`replykit.ScriptedModel`.
    """
    payload: dict[str, Any] = {
        "transport": "offline",
        "note": "This command opens no socket. It prints how to wire a real Slack app.",
        "env": [
            {
                "name": "SLACK_BOT_TOKEN",
                "purpose": "Bot token (xoxb-...) used to post replies via chat.postMessage.",
            },
            {
                "name": "SLACK_SIGNING_SECRET",
                "purpose": "Verifies inbound Events API request signatures.",
            },
            {
                "name": "SLACK_APP_TOKEN",
                "purpose": "App-level token (xapp-...) if you use Socket Mode instead of HTTP.",
            },
        ],
        "wiring": [
            "Create a Slack app and add the 'app_mentions:read' and 'chat:write' bot scopes.",
            "Subscribe to the 'app_mention' bot event in Event Subscriptions.",
            "Point the Request URL at your handler (HTTP) or enable Socket Mode.",
            "On each app_mention, call slack_glue.parse_event(payload) then "
            "handle_app_mention(event, router, db).",
            "Post SlackReply.text back with chat.postMessage, threading on SlackReply.thread_ts.",
        ],
        "handler": (
            "from slack_glue import Router, load_fixture, parse_event, handle_app_mention; "
            "reply = handle_app_mention(parse_event(payload), Router(model), load_fixture())"
        ),
        "endpoints": sorted(ENDPOINTS),
        "filters": {ep: sorted(fields) for ep, fields in FIELD_TYPES.items()},
    }

    if check:
        model = ScriptedModel([_DEFAULT_EMIT, "Done."])
        router = Router(model)
        db = load_fixture()
        reply = handle_app_mention(_SAMPLE_MENTION, router, db)
        payload["check"] = {
            "request": _SAMPLE_MENTION_TEXT,
            "reply": reply.as_dict(),
            "ok": reply.kind == REPLY_RESULTS,
        }

    return payload


def _record_columns(records: list[dict[str, Any]]) -> list[str]:
    """Stable, union-of-keys column order for the human-mode record table."""
    preferred = ["id", "status", "reel", "dept", "sequence", "asset_type", "tags"]
    seen = {k for r in records for k in r}
    cols = [c for c in preferred if c in seen]
    cols.extend(sorted(k for k in seen if k not in preferred))
    return cols


def _cell(value: Any) -> str:
    """Render one record cell value for the Rich table."""
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    if value is None:
        return ""
    return str(value)


def _fail(message: str, *, as_json: bool) -> None:
    """Report a CLI error and exit non-zero."""
    if as_json:
        # Keep the contract: exactly one JSON object on stdout.
        sys.stdout.write(json.dumps({"error": message}) + "\n")
    else:
        err_console.print("[red]error:[/red]", end=" ")
        err_console.print(message, markup=False, highlight=False)
    raise typer.Exit(code=1)


__all__ = ["main"]
