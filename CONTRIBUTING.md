# Contributing to slack-glue

`slack-glue` is a small, dependency-light intent router built on `replykit`. The
bar for contributions is correctness, **hermetic** tests, and a disciplined line
between deterministic code and the single model call.

## Development setup

```bash
uv venv
uv pip install -e '.[dev]'
```

The `dev` extra includes the Typer/Rich CLI dependencies, so the CLI and its
tests run out of the box. `replykit` is pulled in as a normal dependency.

## The one rule: AI only at the genuine judgment boundary

The **only** model call in this codebase is the natural-language → schema step
in `router.py`. Everything else — schema validation, query execution, Slack
event parsing, every reply string, all JSON — **must** be plain deterministic
code. If "a script could do this," it is a script. Adding a model call anywhere
else (to "summarize results", "guess a field", etc.) is a defect, not a feature.

## Quality gates (must pass before a PR)

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest --cov=slack_glue --cov-report=term-missing
```

- The whole suite is **hermetic**: no live LLM, no live Slack, no live
  ShotGrid, no network. Use `replykit.ScriptedModel`/`MockModel` for routing and
  the packaged JSON fixture for the database.
- Line coverage must stay **≥ 90%** on the deterministic core.
- The public API in `src/slack_glue/__init__.py` is the contract. Do not rename
  or remove a symbol without a version bump.

## Style

- Python 3.11+, `src/` layout, PEP 621 packaging.
- `ruff` is the linter and formatter; keep both green.
