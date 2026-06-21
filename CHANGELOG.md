# Changelog

All notable changes to `slack-glue` are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project adheres
to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] — 2026-06-20

First release. A cross-department intent router that turns a messy Slack
production request into a strict, validated query and runs it deterministically
against a mock ShotGrid. The single natural-language → schema step is the only
model call; everything else — validation, execution, formatting — is plain
deterministic code, so the package works and CI runs hermetically with no
provider configured (via `replykit`'s `ScriptedModel` / `MockModel`).

### Added

- **Strict intent schema + validator** (`schema`): a closed contract over two
  endpoints (`/api/v1/shots`, `/api/v1/assets`) with per-endpoint field
  vocabularies and typed values. `validate_intent` returns field-scoped
  `ValidationIssue`s — `unknown_endpoint`, `unknown_field`, `bad_enum` — and
  deterministically coerces values (e.g. `reel` to an `int`). Exposes
  `IntentQuery`, `ValidationIssue`, `validate_intent`, `ENDPOINTS`,
  `FIELD_TYPES`.
- **Mock-ShotGrid database + deterministic executor** (`database`): loads the
  packaged `fixtures/shotgrid.json` (10 shots + 6 assets) via `load_fixture`,
  and `execute_query` runs scalar-equality plus tag-superset (AND) matching,
  returning a `QueryResult` with the matched records and a scan count. Exposes
  `Database`, `Record`, `QueryResult`, `load_fixture`, `execute_query`.
- **Intent router** (`router`): the single NL → schema model boundary, built on
  a `replykit` agent with an `emit_query` tool. `Router` routes a request to a
  `RouteOutcome` (validated query or clarification) and carries replykit's
  per-call token / cost / repair telemetry. Exposes `Router`, `RouteOutcome`,
  `build_routing_registry`, `parse_intent_payload`. With no provider, routing is
  driven hermetically by a scripted/mock model.
- **Deterministic Slack + JSON formatting** (`formatting`): `format_records_slack`
  (bullet list with sorted filters and correct singular/plural noun),
  `format_records_json`, plus `format_validation_error` / `format_clarification`
  for the clarify path.
- **Slack `app_mention` entry point** (`slack`): `parse_event` builds an
  `AppMentionEvent` from an Events-API envelope (stripping the leading mention);
  `handle_app_mention` runs the full route → validate → execute → format pipeline
  and returns a `SlackReply` that threads on the triggering message `ts`. No
  socket is opened. Exposes `AppMentionEvent`, `SlackReply`, `parse_event`,
  `handle_app_mention`.
- **`slack-glue` CLI** with `ask` and `serve` commands. `ask` routes and executes
  a request (`--model scripted|mock|openai|anthropic`, `--script` to replay an
  `emit_query` block for `scripted`); `serve` prints offline wiring instructions
  and, with `--check`, smoke-tests the whole pipeline against a built-in sample
  mention. Every command supports `--json`, which emits exactly one JSON object
  to stdout; configuration errors (e.g. an unknown `--model`) exit non-zero with
  a single `{"error": ...}` object.
- **Hermetic test + acceptance suite**: a 149-test deterministic-core suite and
  an 11-scenario end-to-end acceptance set (`acceptance/`), both offline by
  construction (`total_cost_usd == 0.0` asserted throughout). Runnable examples
  (`examples/ask_hermetic.py`, `examples/slack_event.py`), PEP 621 `pyproject.toml`,
  `src/` layout, MIT license, `py.typed` marker, and contributor docs.

### Notes

- Requires Python ≥ 3.11. The CLI's Typer/Rich dependencies live under the `cli`
  extra and are imported lazily; the core API imports nothing beyond `replykit`.
- `replykit` is not yet published to PyPI. Local development installs it editable
  from the sibling checkout; CI installs it from
  `git+https://github.com/edgarh92/replykit@main` (see `CONTRIBUTING.md`).

[0.1.0]: https://github.com/eggy-sh/slack-glue/releases/tag/v0.1.0
