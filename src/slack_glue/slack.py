"""DETERMINISTIC Slack app-mention entry point that ties routing + exec together.

This module parses a Slack ``app_mention`` event payload, strips the leading bot
mention to recover the producer's actual request, runs it through a
:class:`~slack_glue.router.Router` + the deterministic executor, and produces a
:class:`SlackReply`. Everything here is plain code: event parsing, mention
stripping, the route -> execute -> format pipeline, and the reply object. The
single model call lives behind the injected :class:`~slack_glue.router.Router`,
so a test can pass a Router backed by a :class:`replykit.ScriptedModel` and
exercise the **entire** Slack path with no live Slack and no live ShotGrid.

There is no network code here. Posting the reply back to Slack is the caller's
job (the CLI's ``serve`` command prints how to wire that); this module only
computes *what* to say.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .database import Database, execute_query
from .formatting import (
    format_clarification,
    format_records_json,
    format_records_slack,
)
from .router import Router

#: Reply "kind" tags so the caller can branch on outcome without re-parsing.
REPLY_RESULTS = "results"
REPLY_CLARIFY = "clarify"
REPLY_ERROR = "error"

#: A leading Slack mention token: ``<@U0BOTID>`` (optionally ``<@U0BOTID|name>``).
_MENTION_RE = re.compile(r"^\s*<@[A-Z0-9]+(?:\|[^>]+)?>\s*")


@dataclass(frozen=True)
class AppMentionEvent:
    """The fields of a Slack ``app_mention`` event we actually use."""

    text: str  # raw text, includes the leading "<@BOTID>" mention
    user: str
    channel: str
    ts: str


@dataclass(frozen=True)
class SlackReply:
    """What to post back: a kind tag, rendered text, and a JSON payload."""

    kind: str  # one of REPLY_RESULTS | REPLY_CLARIFY | REPLY_ERROR
    text: str
    payload: dict[str, Any]
    channel: str
    thread_ts: str

    def as_dict(self) -> dict[str, Any]:
        """A JSON-serializable form of the reply."""
        return {
            "kind": self.kind,
            "text": self.text,
            "payload": dict(self.payload),
            "channel": self.channel,
            "thread_ts": self.thread_ts,
        }


def parse_event(payload: dict[str, Any]) -> AppMentionEvent:
    """Extract an :class:`AppMentionEvent` from a raw Slack event envelope.

    Accepts the standard ``{"event": {...}}`` Events-API shape or a bare event
    dict. Pure dict access with defaults; raises ``ValueError`` only when the
    payload has no usable ``text`` field. No network.
    """
    if not isinstance(payload, dict):
        raise ValueError(f"event payload must be a dict, got {type(payload).__name__}")

    event = payload.get("event")
    if not isinstance(event, dict):
        event = payload

    text = event.get("text")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("event payload has no usable 'text' field")

    return AppMentionEvent(
        text=text,
        user=str(event.get("user", "")),
        channel=str(event.get("channel", "")),
        ts=str(event.get("ts", "")),
    )


def strip_mention(text: str) -> str:
    """Remove a leading ``<@USERID>`` bot mention and surrounding whitespace.

    Deterministic regex strip so the recovered request is exactly what the
    producer typed after the @mention. Idempotent on text with no mention.
    """
    return _MENTION_RE.sub("", text, count=1).strip()


def handle_app_mention(
    event: AppMentionEvent,
    router: Router,
    db: Database,
) -> SlackReply:
    """Run the full deterministic pipeline for one mention and build a reply.

    Strips the mention, routes the request (the one model call, behind
    ``router``), and then: on a valid query, executes it against ``db`` and
    formats the records; on validation issues, formats an ask-to-clarify reply;
    threads the reply onto the triggering message ``ts``. Returns a
    :class:`SlackReply` — it does not post anything.
    """
    request = strip_mention(event.text)
    outcome = router.route(request)

    if outcome.ok and outcome.query is not None:
        result = execute_query(outcome.query, db)
        return SlackReply(
            kind=REPLY_RESULTS,
            text=format_records_slack(result),
            payload=format_records_json(result),
            channel=event.channel,
            thread_ts=event.ts,
        )

    return SlackReply(
        kind=REPLY_CLARIFY,
        text=format_clarification(outcome.issues, request),
        payload={
            "issues": [
                {"code": i.code, "field": i.field, "message": i.message} for i in outcome.issues
            ],
            "raw_intent": dict(outcome.raw_intent),
        },
        channel=event.channel,
        thread_ts=event.ts,
    )
