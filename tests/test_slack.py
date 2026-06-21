"""Unit tests for the deterministic Slack app-mention entry point.

Event-envelope parsing, mention stripping, and the route -> execute -> format
pipeline are plain code. The only model touch is the injected Router (backed by
a :class:`replykit.ScriptedModel`), so the entire Slack path runs with no live
Slack, no live ShotGrid, and no network.
"""

from __future__ import annotations

import pytest

from slack_glue.slack import (
    REPLY_CLARIFY,
    REPLY_RESULTS,
    AppMentionEvent,
    SlackReply,
    handle_app_mention,
    parse_event,
    strip_mention,
)

# --- parse_event -----------------------------------------------------------


def test_parse_event_events_api_shape(sample_event) -> None:
    event = parse_event(sample_event)
    assert isinstance(event, AppMentionEvent)
    assert event.user == "U0PRODUCER"
    assert event.channel == "C0VFXCHAN"
    assert event.ts == "1718900000.000100"
    assert event.text.startswith("<@U0BOTID>")


def test_parse_event_bare_event_shape() -> None:
    bare = {
        "type": "app_mention",
        "text": "<@U0BOTID> hello",
        "user": "U1",
        "channel": "C1",
        "ts": "123.456",
    }
    event = parse_event(bare)
    assert event.text == "<@U0BOTID> hello"
    assert event.channel == "C1"


def test_parse_event_missing_text_raises() -> None:
    with pytest.raises(ValueError):
        parse_event({"event": {"user": "U1", "channel": "C1", "ts": "1"}})


def test_parse_event_blank_text_raises() -> None:
    with pytest.raises(ValueError):
        parse_event({"event": {"text": "   "}})


def test_parse_event_non_dict_raises() -> None:
    with pytest.raises(ValueError):
        parse_event("not a dict")  # type: ignore[arg-type]


def test_parse_event_defaults_missing_metadata() -> None:
    event = parse_event({"event": {"text": "<@U0BOTID> hi"}})
    assert event.user == ""
    assert event.channel == ""
    assert event.ts == ""


# --- strip_mention ---------------------------------------------------------


def test_strip_mention_removes_leading_mention() -> None:
    assert strip_mention("<@U0BOTID> approved vfx shots") == "approved vfx shots"


def test_strip_mention_handles_named_mention() -> None:
    assert strip_mention("<@U0BOTID|slackbot> hello") == "hello"


def test_strip_mention_idempotent_without_mention() -> None:
    text = "just plain text"
    assert strip_mention(text) == text
    assert strip_mention(strip_mention(text)) == text


def test_strip_mention_only_strips_leading() -> None:
    # A mention in the middle is left intact.
    assert strip_mention("<@U0BOTID> ping <@U1OTHER>") == "ping <@U1OTHER>"


# --- handle_app_mention (end-to-end, hermetic) -----------------------------


def test_handle_app_mention_results_path(scripted_router, db) -> None:
    router = scripted_router(
        endpoint="/api/v1/shots", status="approved", dept="vfx", reel="3", tags="greenscreen"
    )
    event = AppMentionEvent(
        text="<@U0BOTID> approved vfx shots from reel 3 with green screen",
        user="U0PRODUCER",
        channel="C0VFXCHAN",
        ts="1718900000.000100",
    )
    reply = handle_app_mention(event, router, db)
    assert isinstance(reply, SlackReply)
    assert reply.kind == REPLY_RESULTS
    assert reply.channel == "C0VFXCHAN"
    assert reply.thread_ts == "1718900000.000100"  # threaded onto trigger ts
    ids = [r["id"] for r in reply.payload["records"]]
    assert ids == ["SHOT-0101", "SHOT-0102"]
    assert "SHOT-0101" in reply.text


def test_handle_app_mention_clarify_path(scripted_router, db) -> None:
    # Invalid emitted intent -> clarify, never executed.
    router = scripted_router(endpoint="/api/v1/shots", status="greenlit")
    event = AppMentionEvent(
        text="<@U0BOTID> greenlit shots",
        user="U0PRODUCER",
        channel="C0VFXCHAN",
        ts="999.000",
    )
    reply = handle_app_mention(event, router, db)
    assert reply.kind == REPLY_CLARIFY
    assert reply.thread_ts == "999.000"
    assert reply.payload["issues"][0]["code"] == "bad_enum"
    assert "greenlit shots" in reply.text


def test_handle_app_mention_no_query_path(db) -> None:
    from replykit import ScriptedModel

    from slack_glue.router import Router

    router = Router(ScriptedModel(["I don't understand."]))
    event = AppMentionEvent(text="<@U0BOTID> ???", user="U", channel="C", ts="1.0")
    reply = handle_app_mention(event, router, db)
    assert reply.kind == REPLY_CLARIFY
    assert reply.payload["issues"][0]["code"] == "no_query"


def test_slack_reply_as_dict(scripted_router, db) -> None:
    import json

    router = scripted_router(endpoint="/api/v1/assets", asset_type="character")
    event = AppMentionEvent(text="<@U0BOTID> character assets", user="U", channel="C", ts="2.0")
    reply = handle_app_mention(event, router, db)
    payload = reply.as_dict()
    json.dumps(payload)  # serializable
    assert payload["kind"] == REPLY_RESULTS
    assert payload["channel"] == "C"
    assert payload["thread_ts"] == "2.0"


def test_full_path_from_raw_envelope(scripted_router, db, sample_event) -> None:
    # parse_event -> handle_app_mention, end to end from the raw envelope.
    router = scripted_router(
        endpoint="/api/v1/shots", status="approved", dept="vfx", reel="3", tags="greenscreen"
    )
    event = parse_event(sample_event)
    reply = handle_app_mention(event, router, db)
    assert reply.kind == REPLY_RESULTS
    assert [r["id"] for r in reply.payload["records"]] == ["SHOT-0101", "SHOT-0102"]
