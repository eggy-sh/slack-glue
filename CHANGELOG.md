# Changelog

All notable changes to `slack-glue` are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project adheres
to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Initial package scaffold: PEP 621 `pyproject.toml`, `src/` layout package
  `slack_glue`, MIT license, contributor docs, and a packaged mock-ShotGrid
  JSON fixture.
- Public API surface (stubs pending implementation): strict intent `schema` +
  validator, mock-ShotGrid `database` + deterministic executor, `router`
  (the single NL → schema model boundary, built on `replykit`), deterministic
  Slack/JSON `formatting`, and a deterministic Slack `app_mention` entry point.
- `slack-glue` CLI skeleton with `ask` and `serve` commands and `--json`
  output on every command.

[Unreleased]: https://github.com/eggy-sh/slack-glue/commits/main
