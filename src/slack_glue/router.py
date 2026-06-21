"""The intent router: the ONE place a model is used, plus deterministic glue.

A producer's free-text request is open-ended natural language — "approved VFX
shots from Reel 3 with green screen", "any final character assets tagged hero".
Mapping that fuzzy phrasing onto the closed schema vocabulary (which endpoint?
which status enum? is "green screen" the tag "greenscreen"?) is genuine
language understanding that a rule set cannot robustly encode across the open
space of how people actually type in Slack. **That single natural-language ->
schema step is the only model call in slack-glue.**

Everything around it is deterministic and lives here too:

- :func:`build_routing_registry` exposes ONE replykit tool, ``emit_query``, whose
  arguments are the schema fields. The model "calls" it to emit a structured
  query; the tool body is a pure pass-through that records the args.
- :func:`parse_intent_payload` turns the tool's recorded ``@reply`` args (flat
  strings) into a raw intent dict (parsing ``reel`` digits, splitting ``tags``
  on commas) — pure string/JSON work, **no model**.
- :class:`Router` orchestrates: run the replykit :class:`~replykit.Agent`, take
  the emitted query args, parse them deterministically, then hand off to
  :func:`~slack_glue.schema.validate_intent`. Validation (not the model) decides
  accept-vs-clarify.

The router is constructed with any :class:`replykit.Model`. Tests inject a
:class:`replykit.ScriptedModel` that returns a canned ``emit_query`` block, so
routing is exercised with **no provider and no network**. A real provider is an
optional swap (``replykit[openai]`` / ``replykit[anthropic]``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from replykit import Agent, Model, Telemetry, ToolRegistry

from .schema import ENDPOINTS, IntentQuery, ValidationIssue, validate_intent

#: The name of the single tool the model is asked to emit.
EMIT_TOOL = "emit_query"

#: The system framing injected ahead of the producer's request. Lists the closed
#: endpoint/field vocabulary so the model maps onto it rather than inventing.
ROUTING_PREAMBLE: str = (
    "You translate a production team member's request into exactly one "
    "structured query by emitting a single emit_query tool call.\n"
    f"Choose an endpoint from {sorted(ENDPOINTS)}.\n"
    "Map natural-language phrasing onto the closed schema vocabulary: pick the "
    "correct status/dept/asset_type enum member, the reel number, and any tags "
    "(comma-separated, lowercase, no spaces — e.g. 'green screen' -> "
    "'greenscreen'). Emit only the fields the request actually constrains."
)


@dataclass(frozen=True)
class RouteOutcome:
    """The result of routing one request.

    Exactly one of ``query`` (accepted) or ``issues`` (clarify/reject) is the
    meaningful payload; ``raw_intent`` is always the pre-validation dict the
    deterministic parser produced (useful for debugging and ``--json``).
    """

    ok: bool
    query: IntentQuery | None
    issues: list[ValidationIssue]
    raw_intent: dict[str, Any]
    telemetry: Telemetry
    answer: str

    def as_dict(self) -> dict[str, Any]:
        """A JSON-serializable summary of the routing outcome."""
        return {
            "ok": self.ok,
            "query": self.query.as_dict() if self.query is not None else None,
            "issues": [
                {"code": i.code, "field": i.field, "message": i.message} for i in self.issues
            ],
            "raw_intent": dict(self.raw_intent),
            "telemetry": self.telemetry.as_dict(),
            "answer": self.answer,
        }


def _emit_query(
    endpoint: str = "",
    status: str = "",
    reel: str = "",
    dept: str = "",
    tags: str = "",
    asset_type: str = "",
    sequence: str = "",
) -> dict[str, str]:
    """Pure pass-through: record the emitted query fields verbatim.

    The model "calls" this tool to emit one structured query. There is no
    judgment here — replykit's tolerant @reply parser extracts the args and the
    agent trace captures exactly what was emitted. Validation happens later in
    :func:`~slack_glue.schema.validate_intent`, never in the tool body.
    """
    return {
        "endpoint": endpoint,
        "status": status,
        "reel": reel,
        "dept": dept,
        "tags": tags,
        "asset_type": asset_type,
        "sequence": sequence,
    }


def build_routing_registry() -> ToolRegistry:
    """Build the one-tool registry the routing agent uses.

    Registers a single ``emit_query`` tool whose signature mirrors the schema
    (``endpoint``, ``status``, ``reel``, ``dept``, ``tags``, ``asset_type``,
    ``sequence`` — all optional strings). The body is a pure pass-through: it
    returns its arguments unchanged so the agent trace captures exactly what the
    model emitted. No validation here — that is :mod:`slack_glue.schema`'s job.
    """
    registry = ToolRegistry()
    registry.register(
        _emit_query,
        name=EMIT_TOOL,
        description=(
            "Emit exactly one structured query. endpoint is required; include "
            "only the filter fields the request constrains. tags is "
            "comma-separated."
        ),
    )
    return registry


def parse_intent_payload(args: dict[str, str]) -> dict[str, Any]:
    """Deterministically turn flat ``emit_query`` args into a raw intent dict.

    Pure string work, no model: pulls ``endpoint`` out, folds the remaining
    recognized keys into a ``filters`` dict, splits ``tags`` on commas (trimming
    blanks), and leaves type coercion/validation to
    :func:`~slack_glue.schema.validate_intent`. Unknown keys are passed through
    into ``filters`` so the validator can report them rather than silently
    dropping them.
    """
    endpoint = ""
    filters: dict[str, Any] = {}

    for key, value in args.items():
        if value is None:
            continue
        text = value.strip() if isinstance(value, str) else value
        if isinstance(text, str) and text == "":
            # An empty/unset emit_query arg is not a constraint; skip it.
            continue
        if key == "endpoint":
            endpoint = text
            continue
        if key == "tags":
            if isinstance(text, str):
                parts = [p.strip() for p in text.split(",")]
                tags = [p for p in parts if p]
            else:
                tags = text
            if tags:
                filters["tags"] = tags
            continue
        # Every other key (recognized or not) folds into filters; the validator
        # decides what is legal for the chosen endpoint.
        filters[key] = text

    return {"endpoint": endpoint, "filters": filters}


class Router:
    """Orchestrates NL -> schema -> validated query.

    Holds a :class:`replykit.Model` (the only model in the system) and a routing
    registry. :meth:`route` runs the agent, extracts the emitted query from the
    agent trace, parses it deterministically, validates it, and returns a
    :class:`RouteOutcome`. With a :class:`replykit.ScriptedModel` the whole path
    is hermetic.
    """

    def __init__(
        self,
        model: Model,
        *,
        registry: ToolRegistry | None = None,
        max_steps: int = 3,
    ) -> None:
        self.model = model
        self.registry = registry if registry is not None else build_routing_registry()
        self.max_steps = max_steps

    def route(self, request: str) -> RouteOutcome:
        """Route one free-text request into a validated query or clarify issues.

        Builds the routing prompt from :data:`ROUTING_PREAMBLE` + the request,
        runs the agent (one model call in the happy path), reads the last
        ``emit_query`` call from the trace, parses + validates it. If the model
        emits no ``emit_query`` call at all, returns a ``not ok`` outcome with a
        single ``no_query`` issue (deterministic, no second model call).
        """
        telemetry = Telemetry()
        agent = Agent(
            self.model,
            self.registry,
            telemetry=telemetry,
            max_steps=self.max_steps,
        )
        result = agent.run(self._build_prompt(request))

        emitted = [t for t in result.trace if t.tool == EMIT_TOOL]
        if not emitted:
            return RouteOutcome(
                ok=False,
                query=None,
                issues=[
                    ValidationIssue(
                        code="no_query",
                        field="",
                        message="the router did not emit a structured query for this request",
                    )
                ],
                raw_intent={},
                telemetry=telemetry,
                answer=result.answer,
            )

        # Use the last emit_query call — if the model emitted several, the final
        # one is its considered answer. The trace args are the raw emitted strings.
        raw_args = dict(emitted[-1].args)
        raw_intent = parse_intent_payload(raw_args)
        query, issues = validate_intent(raw_intent)
        return RouteOutcome(
            ok=query is not None,
            query=query,
            issues=issues,
            raw_intent=raw_intent,
            telemetry=telemetry,
            answer=result.answer,
        )

    def _build_prompt(self, request: str) -> str:
        """Compose the routing prompt (preamble + request). Deterministic."""
        return f"{ROUTING_PREAMBLE}\n\nRequest: {request}"
