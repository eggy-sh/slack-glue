#!/usr/bin/env python3
"""Drive the Slack ``app_mention`` path end-to-end — hermetic (no network).

This is what a real Slack app would do *inside* its event handler, minus the HTTP
plumbing: take a raw Events-API payload, recover the request, run the one model
call + deterministic executor, and build the reply to post back. Here the model
is a :class:`replykit.ScriptedModel`, so the entire path runs offline with no
Slack workspace and no API key.

The pipeline:

1. :func:`slack_glue.parse_event` pulls the ``app_mention`` fields out of the
   Events-API envelope (``{"event": {...}}``).
2. :func:`slack_glue.handle_app_mention` strips the leading ``<@BOTID>`` mention,
   routes the recovered request (the one model call, behind the injected
   :class:`~slack_glue.Router`), executes the validated query against the mock
   ShotGrid, and returns a :class:`~slack_glue.SlackReply`.
3. The reply carries a ``kind`` tag (``results`` / ``clarify`` / ``error``),
   plain-text for the channel, a structured JSON ``payload``, and the
   ``thread_ts`` to thread onto — *posting* it is the caller's job (this module
   computes only *what* to say).

Run it::

    python examples/slack_event.py

It prints the reply for a request that resolves to records and for one that needs
clarification. It posts nothing and opens no socket.
"""

from __future__ import annotations

import json

from replykit import ScriptedModel

from slack_glue import Router, handle_app_mention, load_fixture, parse_event
from slack_glue.slack import strip_mention


def _emit_block(**fields: str) -> str:
    """The exact ``@reply`` text a routing model would emit for these fields."""
    lines = ["@reply name=emit_query"]
    lines += [f"{key} = {value}" for key, value in fields.items()]
    lines.append("@end")
    return "\n".join(lines)


def _envelope(text: str) -> dict:
    """A representative Slack Events-API ``app_mention`` envelope."""
    return {
        "event": {
            "type": "app_mention",
            "text": text,
            "user": "U0PRODUCER",
            "channel": "C0VFXCHAN",
            "ts": "1718900000.000100",
        }
    }


def run(label: str, envelope: dict, *responses: str) -> None:
    """Parse an event envelope and run the full Slack pipeline for it."""
    print(f"\n=== {label} ===")
    event = parse_event(envelope)
    # handle_app_mention strips the leading mention internally; show the same
    # recovered request here for clarity.
    print("recovered request:", repr(strip_mention(event.text)))

    # The injected Router holds the only model in the system. A ScriptedModel
    # keeps the whole Slack path hermetic; a real provider is a drop-in swap.
    router = Router(ScriptedModel([*responses, "Done."]))
    reply = handle_app_mention(event, router, load_fixture())

    print(f"reply.kind = {reply.kind}  (thread_ts={reply.thread_ts})")
    print(reply.text)
    print("payload ->", json.dumps(reply.payload))


def main() -> None:
    # 1. A request that resolves to records -> a "results" reply.
    run(
        "results",
        _envelope("<@U0BOTID> get me all approved VFX shots from Reel 3 with green screen"),
        _emit_block(
            endpoint="/api/v1/shots",
            status="approved",
            reel="3",
            dept="vfx",
            tags="greenscreen",
        ),
    )

    # 2. A request with an out-of-vocabulary status -> a "clarify" reply that
    #    tells the producer exactly what could not be mapped.
    run(
        "clarify",
        _envelope("<@U0BOTID> show me the greenlit shots"),
        _emit_block(endpoint="/api/v1/shots", status="greenlit"),
    )


if __name__ == "__main__":
    main()
