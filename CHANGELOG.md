# Changelog

All notable changes to skillwire are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/).

## [0.1.1] - 2026-10-08

Changes for the Anthropic plugin directory checks.

### Changed
- The router's Haiku classifier now takes its API key from a new sensitive
  `classifier_api_key` plugin option (secure storage, exported to hooks as
  `CLAUDE_PLUGIN_OPTION_CLASSIFIER_API_KEY`). skillwire no longer reads API keys from
  the shell environment. **If you used `llm_classify` with a key from your shell, set the
  option instead.**
- `plugin.json` now sets `author`, `homepage`, `repository` and `icon`.

### Added
- Listing icon at `.claude-plugin/icon.png`.
- README section "What skillwire runs, sends and fetches".

## [0.1.0] - 2026-10-08

First release.

### Added
- `docs/HOOK_SCHEMA.md`: the hook, plugin and marketplace schema, checked against the
  Claude Code 2.1.295 docs. It also records the Skill tool's input
  (`{"skill", "args"}`) and PostToolUse `tool_response` / `duration_ms`, which were
  captured from a live session.
- Plugin manifest, a one-plugin marketplace, and `hooks/hooks.json`, with exec-form
  hooks for SessionStart, UserPromptSubmit, and PreToolUse/PostToolUse (matcher `Skill`).
- One dispatcher per hook event that always exits 0 and logs failures to
  `~/.claude/skillwire/errors.log`.
- Layered JSON config: `~/.claude/skillwire.json` with `<project>/.claude/skillwire.json`
  on top. A corrupted layer is skipped.
- Modules: router (keywords, regex, and an optional Haiku classifier with a 2s
  timeout and regex fallback), telemetry (SQLite), chaining, hijacker (with
  self-redirect and cycle guards), repo allowlist/denylist, chaos mode (needs the
  config flag plus `SKILLWIRE_CHAOS=1`, can be seeded, shows a session banner), JIT
  skills (template plus generator, keeps the last good render on failure), and a
  description A/B rotator.
- CLI: `init`, `report`, `suggest-chains`, `rotate`, `ab-report`, `doctor`.
- Example JIT skill `examples/jit-datasets` that lists datasets from a JSON endpoint.
- pytest suite, with fixtures for every hook event, plus an opt-in end-to-end test
  that installs from the local marketplace and drives the real `claude` CLI.

### Notes on deviations from the original spec
- JSON config instead of YAML, so no third-party parser is needed.
- Skill "duration" is the `duration_ms` Claude Code reports, which is the time to
  load the skill. Reports label it that way.
- Router context is worded as project policy rather than as an injected system
  instruction, following the hooks docs' guidance.
