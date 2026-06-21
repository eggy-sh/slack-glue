#!/usr/bin/env python3
"""End-to-end ``ask`` walkthrough — fully hermetic (no network, no API key).

This mirrors what ``slack-glue ask`` does, but in plain Python so you can see the
moving parts:

1. **Route** a free-text request into a structured query. This is the *one* model
   call in slack-glue. Here the model is a :class:`replykit.ScriptedModel` that
   replays a canned ``emit_query`` block, so the example needs no API key. Swap in
   ``replykit.AnthropicModel()`` (with ``ANTHROPIC_API_KEY`` set) for real,
   semantic routing — nothing else changes.
2. **Validate** the emitted intent against the strict schema. This is plain,
   deterministic code: it accepts a well-formed query (normalizing ints and tags)
   or returns structured issues to clarify. The *model* never decides validity.
3. **Execute** the validated query against the packaged mock-ShotGrid fixture.
4. **Format** the matches into a Slack-style reply and a JSON payload — again,
   deterministic, byte-for-byte reproducible.

Run it::

    python examples/ask_hermetic.py

It prints the routed query, the matching records (Slack text + JSON), the
clarify path for an out-of-vocabulary request, and replykit's token/cost
telemetry. It writes no files and opens no socket.
"""

from __future__ import annotations

import json

from replykit import ScriptedModel

from slack_glue import (
    Router,
    execute_query,
    format_clarification,
    format_records_json,
    format_records_slack,
    load_fixture,
)


def _emit_block(**fields: str) -> str:
    """Build the exact ``@reply`` protocol text a routing model would emit."""
    lines = ["@reply name=emit_query"]
    lines += [f"{key} = {value}" for key, value in fields.items()]
    lines.append("@end")
    return "\n".join(lines)


def route_and_run(request: str, *responses: str) -> None:
    """Route one request through a scripted model, then execute + format."""
    print(f"\n=== {request!r} ===")
    # The model replays the emit_query block(s), then a plain-text final turn so
    # the agent loop terminates. This is the whole no-LLM path.
    model = ScriptedModel([*responses, "Done."])
    router = Router(model)
    outcome = router.route(request)

    if outcome.ok and outcome.query is not None:
        print("routed ->", json.dumps(outcome.query.as_dict()))
        result = execute_query(outcome.query, load_fixture())
        print(format_records_slack(result))
        print("json   ->", json.dumps(format_records_json(result)))
    else:
        # Deterministic ask-to-clarify, built from the schema's structured issues.
        print(format_clarification(outcome.issues, request))

    print("telemetry ->", json.dumps(outcome.telemetry.as_dict()))


def main() -> None:
    # 1. A request that maps cleanly onto the schema: 2 fixture shots match.
    route_and_run(
        "approved VFX shots from Reel 3 with green screen",
        _emit_block(
            endpoint="/api/v1/shots",
            status="approved",
            reel="3",
            dept="vfx",
            tags="greenscreen",
        ),
    )

    # 2. An assets request: one approved character asset matches.
    route_and_run(
        "any approved character assets",
        _emit_block(
            endpoint="/api/v1/assets",
            status="approved",
            asset_type="character",
        ),
    )

    # 3. An out-of-vocabulary status -> the validator rejects it and we clarify.
    #    The model emitted *something*; the deterministic schema is the authority.
    route_and_run(
        "all greenlit shots",
        _emit_block(endpoint="/api/v1/shots", status="greenlit"),
    )


if __name__ == "__main__":
    main()
