"""slack-glue — a cross-department intent router for production studios.

A producer's messy Slack request ("get me all approved VFX shots from Reel 3
that have green screen") is translated by a :mod:`replykit` agent into a
**strict, validated** API query schema, e.g.::

    {"endpoint": "/api/v1/shots",
     "filters": {"status": "approved", "reel": 3, "tags": ["greenscreen"]}}

A **deterministic** executor runs that query against a mock ShotGrid database
(an in-repo fixture of shots/assets) and returns matching records. A Slack
app-mention event entry point ties it together and formats a reply.

Everything is deterministic except the single natural-language -> schema step:
schema validation, query execution, and Slack/JSON formatting are all plain
code. The tool ships a **no-LLM path** (replykit's ``ScriptedModel`` /
``MockModel``) so it works and CI runs hermetically with no provider
configured.

Importing :mod:`slack_glue` pulls in **zero** third-party packages beyond
``replykit`` (whose own import surface is dependency-free). The CLI's Typer/Rich
deps live under the ``cli`` extra and are imported lazily.
"""

from __future__ import annotations

from .database import (
    Database,
    QueryResult,
    Record,
    execute_query,
    load_fixture,
)
from .formatting import (
    format_clarification,
    format_records_json,
    format_records_slack,
    format_validation_error,
)
from .router import (
    RouteOutcome,
    Router,
    build_routing_registry,
    parse_intent_payload,
)
from .schema import (
    ENDPOINTS,
    FIELD_TYPES,
    IntentQuery,
    ValidationIssue,
    validate_intent,
)
from .slack import (
    AppMentionEvent,
    SlackReply,
    handle_app_mention,
    parse_event,
)

__version__ = "0.1.0"

__all__ = [
    "__version__",
    # schema (deterministic)
    "IntentQuery",
    "ValidationIssue",
    "validate_intent",
    "ENDPOINTS",
    "FIELD_TYPES",
    # database (deterministic)
    "Database",
    "Record",
    "QueryResult",
    "load_fixture",
    "execute_query",
    # router (the one LLM boundary, plus deterministic parse)
    "Router",
    "RouteOutcome",
    "build_routing_registry",
    "parse_intent_payload",
    # formatting (deterministic)
    "format_records_slack",
    "format_records_json",
    "format_validation_error",
    "format_clarification",
    # slack (deterministic)
    "AppMentionEvent",
    "SlackReply",
    "parse_event",
    "handle_app_mention",
]
