"""Shared hermetic fixtures for the slack-glue test suite.

Nothing here touches the network, a live Slack workspace, or a live ShotGrid.
Routing is exercised with :class:`replykit.ScriptedModel`; the database is the
packaged JSON fixture. These fixtures are the seams every test layer reuses so
the suite stays fully offline and reproducible.
"""

from __future__ import annotations

import os

import pytest
from replykit import ScriptedModel

from slack_glue import Database, Router, load_fixture

# Pin a wide terminal width so Rich-rendered CLI "--help" output is never
# wrapped/truncated under CI's narrow non-TTY width (which hides option flags
# from the help tests). Set at import time, before any CLI is imported/invoked.
os.environ["COLUMNS"] = "200"
# Disable ANSI color so Rich does not split option names (e.g. "--fps")
# across styled spans, which CI's forced color would otherwise do.
os.environ["TERM"] = "dumb"
os.environ["NO_COLOR"] = "1"
os.environ.pop("FORCE_COLOR", None)


@pytest.fixture
def db() -> Database:
    """The packaged mock-ShotGrid fixture loaded into a :class:`Database`."""
    return load_fixture()


@pytest.fixture
def emit_block():
    """Factory: build a well-formed ``emit_query`` @reply block string.

    Pass schema fields as kwargs (``endpoint="/api/v1/shots"``, ``status=...``,
    ``reel=...``, ``tags="greenscreen"`` etc.); returns the exact protocol text a
    real model would emit, suitable for seeding a :class:`ScriptedModel`.
    """

    def _build(**fields: str) -> str:
        lines = ["@reply name=emit_query"]
        for key, value in fields.items():
            lines.append(f"{key} = {value}")
        lines.append("@end")
        return "\n".join(lines)

    return _build


@pytest.fixture
def scripted_router(emit_block):
    """Factory: a :class:`Router` whose model replays one ``emit_query`` block.

    Usage::

        router = scripted_router(endpoint="/api/v1/shots", status="approved",
                                 reel="3", tags="greenscreen")

    The router then runs fully offline. Pass ``_responses=[...]`` to supply raw
    response strings directly (e.g. to test a non-emit_query / no-query turn).
    """

    def _build(_responses: list[str] | None = None, **fields: str) -> Router:
        if _responses is None:
            # emit_query block, then a plain-text final answer so the agent stops.
            _responses = [emit_block(**fields), "Done."]
        return Router(ScriptedModel(_responses))

    return _build


@pytest.fixture
def sample_event() -> dict:
    """A representative Slack ``app_mention`` event envelope (Events API shape)."""
    return {
        "event": {
            "type": "app_mention",
            "text": "<@U0BOTID> get me all approved VFX shots from Reel 3 with green screen",
            "user": "U0PRODUCER",
            "channel": "C0VFXCHAN",
            "ts": "1718900000.000100",
        }
    }
