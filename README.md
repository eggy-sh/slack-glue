# slack-glue

A cross-department **intent router** for production studios. A producer types a
messy request in Slack; `slack-glue` turns it into a **strict, validated** API
query and runs it against a (mock) ShotGrid — returning the actual matching
shots/assets instead of a thread of "can someone pull this for me?".

```
"get me all approved VFX shots from Reel 3 that have green screen"
            │
            ▼  (the ONE model call: natural language -> schema)
{"endpoint": "/api/v1/shots",
 "filters": {"status": "approved", "dept": "vfx", "reel": 3, "tags": ["greenscreen"]}}
            │
            ▼  (deterministic: validate -> execute -> format)
SHOT-0101, SHOT-0102   ← real records, posted back in-thread
```

## Why this is built for studios

Production tracking lives in ShotGrid/Flow, but the *questions* live in Slack —
asked by producers, coordinators, and supervisors who do not write filter syntax
and should not have to. The usual answers are bad: a brittle slash-command DSL
nobody remembers, or a free-form LLM bot that hallucinates shot IDs and statuses
that were never in the database. Neither is safe to point at a pipeline of
record.

`slack-glue` splits the problem at the one seam that actually needs judgment:

- **The model only translates.** Mapping fuzzy phrasing onto the closed schema
  vocabulary — which endpoint, which `status` enum, is "green screen" the
  `greenscreen` tag — is genuine language understanding. That single
  natural-language → schema step is the **only** model call in the system.
- **A deterministic core owns the truth.** Schema validation, the query
  executor, Slack event parsing, and every byte of reply formatting are plain
  code. The model can *propose* a query; it can never decide what is valid, count
  records, or write the summary. An out-of-vocabulary ask (`status=greenlit`)
  isn't guessed at — it's deterministically rejected with a precise,
  field-scoped clarify message.
- **It runs with no LLM at all.** The default CLI path and the entire test suite
  drive routing with replykit's `ScriptedModel`, so CI is hermetic — no live
  Slack, no live ShotGrid, no network, no API key. A real provider
  (`anthropic` / `openai`) is a one-flag swap; nothing downstream changes.

The result is a bot a studio can trust: it answers from real records or asks a
specific clarifying question, and it is impossible for it to invent a status,
a tag, or a shot that isn't there.

Built on [`replykit`](https://github.com/eggy-sh/replykit) for the agent I/O, the
tolerant `@reply` protocol, the provider-agnostic model abstraction, and
first-class token/cost telemetry.

## Install

```bash
uv venv
uv pip install -e '.[dev]'        # core + CLI + test tooling
# optional real providers (the no-LLM path works without these):
uv pip install -e '.[anthropic]'  # or .[openai]
```

## Quickstart

```bash
# Route + execute + print results. Hermetic by default (scripted model).
slack-glue ask "approved vfx shots in reel 3 with greenscreen" \
  --model scripted \
  --script $'@reply name=emit_query\nendpoint = /api/v1/shots\nstatus = approved\ndept = vfx\nreel = 3\ntags = greenscreen\n@end'

# Same, machine-readable — exactly one JSON object on stdout:
slack-glue ask "..." --json | jq '.result.count'

# Offline-safe: print how to wire a real Slack app (opens no socket).
slack-glue serve
slack-glue serve --check          # also runs a sample app_mention through the pipeline
```

Prefer to see the moving parts in plain Python? Two runnable, hermetic examples:

```bash
python examples/ask_hermetic.py   # route -> validate -> execute -> format
python examples/slack_event.py    # full Slack app_mention -> SlackReply pipeline
```

## Using a real model

Swap the backend for a provider-backed router; the schema, executor, and Slack
layers are unchanged. The model still only emits an `emit_query` block — the
deterministic core still decides accept-vs-clarify.

```bash
export ANTHROPIC_API_KEY=...
slack-glue ask "approved vfx shots in reel 3 with greenscreen" --model anthropic
```

## Interop notes

`slack-glue` is designed to drop into other systems, not to be a closed app.

- **`--json` on every command** prints **exactly one JSON object** to stdout and
  nothing else, so the CLI composes into pipelines (`| jq`, agent tool calls,
  CI asserts). `ask` returns
  `{"ok", "request", "query", "result": {"endpoint","filters","count","records"},
  "text", "telemetry"}` on a hit, or `{"ok": false, "issues", "raw_intent",
  "text", "telemetry"}` on a clarify. Configuration errors return
  `{"error": "..."}` with a non-zero exit, still as a single object.
- **Slack Events API.** Inside your handler, call
  `parse_event(payload)` → `handle_app_mention(event, router, db)`. The returned
  `SlackReply` carries a `kind` tag (`results` / `clarify` / `error`), the
  channel text, a structured JSON `payload`, and a `thread_ts` to thread on —
  post it with `chat.postMessage`. `slack-glue serve` prints the exact scopes,
  events, and env vars; the library itself opens no socket and makes no network
  call, so *how* you host (HTTP endpoint vs. Socket Mode) is your choice.
- **Swapping in real ShotGrid.** The schema (`ENDPOINTS`, `FIELD_TYPES`) is the
  closed contract; the executor is the only piece that touches data. Point
  `load_fixture` at your own JSON, or replace `execute_query` with a real
  ShotGrid/Flow API call that honors the same validated `IntentQuery` — the
  router, validator, and formatters are untouched.
- **Telemetry.** Every routed request carries replykit's per-call token / cost /
  repair accounting in `telemetry`, so a deployment can budget and monitor the
  one model call. Hermetic models report `$0.00`.

## Architecture

| Module | Responsibility | Deterministic? |
|--------|----------------|----------------|
| `schema.py` | Strict intent schema + validator (accept / clarify) | yes |
| `database.py` | Mock ShotGrid loader + query executor | yes |
| `router.py` | NL → schema (replykit agent) + deterministic parse | **model boundary** |
| `formatting.py` | Slack-text + JSON rendering | yes |
| `slack.py` | `app_mention` parse → route → execute → reply | yes |
| `cli.py` | `ask` / `serve` commands (both `--json`) | yes |

The mock ShotGrid fixture lives at `src/slack_glue/fixtures/shotgrid.json`
(10 shots + 6 assets across statuses, departments, reels, and tags).

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md). Quality gates: `ruff check`,
`ruff format --check`, and `pytest --cov` (≥ 90% on the deterministic core). The
whole suite is hermetic — no network, no live LLM.

## License

MIT © 2026 Edgar Hernandez
