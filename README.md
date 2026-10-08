# skillwire

A Claude Code plugin that intercepts and reshapes how Claude uses skills. It
routes prompts to skills, chains skills together, redirects or blocks them,
renders skills just in time, and measures all of it.

| Module | Hook | Default | What it does |
|---|---|---|---|
| **router** | UserPromptSubmit | on | Matches the prompt against keyword/regex rules (with an optional Haiku classifier) and tells Claude which skills are *required* and which are *suggested* |
| **telemetry** | UserPromptSubmit, PreToolUse, PostToolUse | on | Logs every routed, loaded, denied and redirected skill to SQLite. Powers `report`, `suggest-chains` and `ab-report` |
| **chaining** | PostToolUse | on | After skill X loads, points Claude at its configured follow-ups |
| **hijacker** | PreToolUse | off | Denies skill X and tells Claude to load Y instead, with loop guards |
| **allowlist** | PreToolUse | off | Allows or blocks skills per working directory (glob rules) |
| **chaos** | PreToolUse, SessionStart | off | Randomly denies a share of skill loads to test resilience. Needs the config flag **and** `SKILLWIRE_CHAOS=1` |
| **jit** | SessionStart | off | Regenerates `SKILL.md` from a template and a generator command |
| **ab** | CLI only | off | Rotates a skill's description between variants and compares trigger rates |

It uses only the Python 3 standard library (3.9+), with no pip installs. The hook
schema it is built against, including what was verified live, is in
[`docs/HOOK_SCHEMA.md`](docs/HOOK_SCHEMA.md).

## Install

The repo is both the plugin and a one-plugin marketplace.

Inside Claude Code:

```
/plugin marketplace add ajwann/skillwire          # or a local checkout: /path/to/skillwire
/plugin install skillwire@skillwire
```

The same from a shell, optionally scoped to one project:

```bash
claude plugin marketplace add ajwann/skillwire              # --scope project to keep it per-repo
claude plugin install skillwire@skillwire                   # -s project
```

Start a new session (or run `/reload-plugins`), then check the install:

```bash
skillwire doctor        # inside Claude: ask it to run `skillwire doctor`
```

Hooks run `python3` from your PATH.

### Running the CLI

The plugin's `bin/` directory is on the PATH of **Claude's Bash tool** while the plugin is enabled, so
you can ask Claude to "run `skillwire report 30d`". From your own terminal, call the script
directly or add an alias:

```bash
alias skillwire="python3 /path/to/skillwire/bin/skillwire"
```

| Command | Purpose |
|---|---|
| `skillwire init [--print] [--global]` | Generate starter router rules from installed skills' `description` frontmatter. It only *adds* rules for skills that have none and backs up the file first |
| `skillwire report [7d\|30d\|24h\|2w] [--unused]` | Markdown tables: top skills, average load time, redirects, denials, never-triggered skills |
| `skillwire suggest-chains [--min 3] [--window 30d]` | Propose `chaining.chains` entries for skills that load together in ≥ N sessions. Prints only and never edits config |
| `skillwire rotate [--skill NAME] [--dry-run]` | Switch A/B skills to their next description variant |
| `skillwire ab-report` | Trigger rate per variant, with sample sizes and a significance verdict |
| `skillwire doctor [--no-claude]` | Validate config and hook registration, run `claude plugin validate`, and run every dispatcher on fake events in a sandbox |

All commands accept `--project DIR` (default: `$CLAUDE_PROJECT_DIR` or the cwd).

## Configuration

skillwire reads JSON, not YAML, so it needs no third-party parser:

1. `~/.claude/skillwire.json` (global)
2. `<project>/.claude/skillwire.json` (project, which **wins**)

Objects merge key by key, and lists and scalars from the project file replace the
global ones. If a file is unreadable or not valid JSON, it is skipped and the error
goes to `~/.claude/skillwire/errors.log`. The hooks keep running on the other layer
and the defaults. `skillwire doctor` reports the problem.

### Example using every module

[`skillwire.example.json`](skillwire.example.json) (the test suite checks that it validates):

```json
{
  "router": {
    "enabled": true,
    "llm_classify": false,
    "llm_model": "claude-haiku-5-5",
    "llm_timeout": 2.0,
    "rules": [
      {
        "skill": "security-review",
        "keywords": ["security", "vulnerability", "CVE", "auth bypass"],
        "regex": ["\\b(xss|sqli|csrf)\\b"],
        "intent_examples": ["is this endpoint safe?", "audit this PR for injection bugs"],
        "priority": "required"
      },
      {
        "skill": "flaky-test-triage",
        "keywords": ["flaky", "intermittent"],
        "regex": ["passes (locally|on retry)"],
        "intent_examples": ["this test fails in CI but not on my machine"],
        "priority": "suggested"
      }
    ]
  },
  "telemetry": { "enabled": true, "store_prompts": false },
  "chaining": {
    "enabled": true,
    "skip_if_loaded": true,
    "chains": {
      "security-review": ["secret-leak-response"],
      "api-breaking-change-check": ["license-compliance"]
    }
  },
  "hijacker": { "enabled": true, "map": { "old-code-review": "code-review" } },
  "allowlist": {
    "enabled": true,
    "rules": [
      { "paths": ["~/work/*"], "block": ["personal-*", "pirate-voice"] },
      { "paths": ["~/work/payments"], "allow": ["code-review", "security-*", "python-engineering-standards"] }
    ]
  },
  "chaos": { "enabled": true, "rate": 0.2, "seed": null, "exempt": ["security-review"] },
  "jit": { "enabled": true, "timeout": 30, "skill_dirs": [] },
  "ab": { "enabled": true, "min_sessions": 30 },
  "skill_dirs": ["~/shared-skills"]
}
```

### Reference

Every module takes `enabled: true|false`.

**router**

| Key | Default | |
|---|---|---|
| `rules[]` | `[]` | `{skill, keywords[], regex[], intent_examples[], priority}`. `priority` is `required` or `suggested` (default) |
| `llm_classify` | `false` | Also ask Haiku which rules apply. Only used when `ANTHROPIC_API_KEY` is set |
| `llm_model` | `claude-haiku-5-5` | |
| `llm_timeout` | `2.0` | Seconds. On timeout, refusal or a bad response, only the keyword/regex matches are used |

Keywords match case-insensitively on word boundaries ("test" does not match "attest"). Regexes use
Python `re.search` with IGNORECASE. Claude gets context such as *"Required skills (project
policy: load these with the Skill tool before responding): security-review. Suggested skills
(optional, likely relevant): flaky-test-triage."* Skills the allowlist would block are left out.

**telemetry**: `store_prompts` (default `false`). Prompts are stored as a 16-character SHA-256
prefix unless this is `true`.

**chaining**: `chains: {after_skill: [then_skills]}`. With `skip_if_loaded` (default `true`),
skills already loaded in the session are left out, so `a → b → a` chains stop on their own.

**hijacker**: `map: {from_skill: to_skill}`. Chains resolve to their end (`a→b→c` sends `a`
straight to `c`). A self-redirect, a cycle, or a redirect into a skill the allowlist blocks is
**ignored**: the original call goes through, and the reason is logged and reported by `doctor`.

**allowlist**: `rules[]` of `{paths[], allow[]?, block[]?}`. Path globs (`~` expands) match the
cwd *or any ancestor*, with symlinks resolved. Skill patterns are globs that match either
`plugin:skill` or the bare `skill`. In each applicable rule, `block` beats `allow`. If any
applicable rule has an `allow` list, the skill must be on one of those lists.

**chaos**: `rate` (default `0.2`, clamped to 0–1), `seed` (or the env var `SKILLWIRE_CHAOS_SEED`;
with a seed, each decision is a fixed function of seed and `tool_use_id`), and `exempt[]` globs.
Active only when `enabled: true` **and** `SKILLWIRE_CHAOS=1`. While it is active, every session
starts with a visible banner. The deny reason is exactly `skillwire chaos: proceed without this skill.`

**jit**: `timeout` (default 30s per generator) and `skill_dirs[]` (extra skill folders to scan).
A skill opts in with a sidecar `skillwire.json` next to its `SKILL.md`:

```json
{ "template": "SKILL.template.md", "generator": "{python} generate.py --url https://example.com/catalog.json" }
```

`{python}` expands to the interpreter running skillwire. The generator runs in the skill folder,
and its stdout should be a JSON object (anything else becomes `{{ output }}`). Template
placeholders look like `{{ key }}` or `{{ key.sub }}`: lists render as bullets, dicts as JSON.
If anything fails (non-zero exit, timeout, an unknown placeholder, or output without
frontmatter), **SKILL.md is left as it was** and a one-line notice appears at session start.
Renders are skipped after `/compact`.
[`examples/jit-datasets/`](examples/jit-datasets/) fetches a JSON endpoint and lists its datasets.

**ab**: `min_sessions` (default 30 per variant before any winner is called). A skill opts in with:

```json
{ "variants": ["Use when reviewing code for bugs.", "Use for code review requests: PRs, diffs, patches."] }
```

`skillwire rotate` backs up `SKILL.md` to `~/.claude/skillwire/backups/`, rewrites **only** the
`description:` line (and refuses if the description spans several lines), and logs the switch. To
run it on a schedule, use cron, e.g. weekly:

```cron
0 9 * * 1  python3 /path/to/skillwire/bin/skillwire --project /path/to/repo rotate
```

`ab-report` defines trigger rate as *sessions where the skill loaded ÷ sessions with a prompt while
that variant was active*. It shows both counts, refuses to name a winner while any variant has fewer
than `min_sessions`, and otherwise runs a two-proportion z-test (p < 0.05).

**skill_dirs** (top level): extra directories scanned by `init`, `report --unused`, `jit` and `rotate`.
Skills are found in `<project>/.claude/skills`, `~/.claude/skills`, and these directories. Skills
that come from other plugins aren't scanned, so add their folders here if you want them in reports.

### Order on the Skill tool

PreToolUse runs **allowlist → hijacker → chaos → telemetry**. The first module that denies wins,
and later deny-capable modules are skipped. Telemetry always runs last and records what was
decided (`denied` by allowlist or chaos, or `redirected` by hijacker). PostToolUse runs
**chaining → telemetry** (`loaded` with `duration_ms`, or `failed`).

The `duration_ms` Claude Code reports for a Skill call is how long *loading the skill* took, not
how long Claude then spends on the work. The reports label it that way.

### Failure semantics

Every dispatcher catches everything (bad stdin, bad config, a module that crashes or won't
import), logs it to `~/.claude/skillwire/errors.log`, and **exits 0**. skillwire never uses exit
code 2. Denials are made only through the documented `permissionDecision: "deny"` JSON.

## Data

Everything is stored in `~/.claude/skillwire/`:

- `skillwire.db`: SQLite tables `events` and `ab_rotations`
- `errors.log`: rotated at 1 MB
- `backups/`: copies of SKILL.md made before `rotate`, and of config before `init`

## Development

```bash
python3 -m pytest                                  # unit + dispatcher tests (pytest is dev-only)
SKILLWIRE_E2E=1 python3 -m pytest tests/test_e2e.py -s   # real `claude` CLI, one Haiku call
claude plugin validate .
```

The e2e test installs the plugin from this marketplace at **project scope** in a temp project,
runs a headless session, checks the telemetry DB to confirm the router, hijacker and telemetry
hooks fired, and then uninstalls.

## Uninstall cleanly

```
/plugin uninstall skillwire@skillwire          # shell: claude plugin uninstall skillwire@skillwire [-s project]
/plugin marketplace remove skillwire           # shell: claude plugin marketplace remove skillwire
```

Then remove what skillwire wrote outside the plugin:

```bash
rm -rf ~/.claude/skillwire                     # telemetry DB, error log, backups
rm -f ~/.claude/skillwire.json                 # global config
rm -f <project>/.claude/skillwire.json         # per-project config, in each repo where you made one
crontab -e                                     # delete any `skillwire rotate` entry
```

Skills changed by skillwire are ordinary files and stay as they are:

- **JIT skills** keep their last rendered `SKILL.md`. Delete `skillwire.json` and
  `SKILL.template.md` from the skill folder if you no longer want them.
- **A/B skills** keep whichever description was active last. To restore the original, copy the
  oldest `~/.claude/skillwire/backups/<skill>.*.SKILL.md` back **before** you delete that folder.
