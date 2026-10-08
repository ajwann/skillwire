# Hook & plugin schema (verified)

Verified on 2026-10-08 against Claude Code **2.1.295** and the docs at
code.claude.com/docs (`/en/hooks`, `/en/tools-reference`, `/en/plugins-reference`,
`/en/plugin-marketplaces`). Where the docs were silent, the payload was captured
from a real `claude -p` session with a logging hook (marked **captured**).

skillwire is built against this file. If Claude Code changes, update this file
first, then `lib/skillwire/hookio.py`.

## Common stdin fields (every event)

| Field | Notes |
|---|---|
| `session_id` | always present |
| `transcript_path` | path to the session JSONL |
| `cwd` | working directory |
| `hook_event_name` | `SessionStart`, `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, … |
| `prompt_id` | present on prompt and tool events (**captured**; absent on SessionStart) |
| `permission_mode` | `default`, `plan`, `acceptEdits`, `auto`, `dontAsk`, `bypassPermissions` |
| `effort` | `{"level": ...}` on tool events (**captured**) |
| `agent_id`, `agent_type` | only inside subagents / `--agent` |

## Event-specific stdin fields

**SessionStart**: `source` (`startup` / `resume` / `clear` / `compact` / `fork`), optional `model`, `session_title`.

**UserPromptSubmit**: `prompt` (the submitted text), optional `session_title`.

**PreToolUse**: `tool_name`, `tool_input`, `tool_use_id`.

**PostToolUse**: `tool_name`, `tool_input`, `tool_response`, `tool_use_id`, optional `duration_ms`
("Tool execution time in milliseconds. Excludes time spent in permission prompts and PreToolUse hooks").

### The skill tool (captured)

The docs give the tool name, `Skill` ("Executes a skill within the main
conversation"), but not its input schema. Captured from a real call:

```json
// PreToolUse
{"tool_name": "Skill",
 "tool_input": {"skill": "pirate-voice", "args": "hello"},
 "tool_use_id": "toolu_01YEn44KcDUXvByiPF6kYRwY"}

// PostToolUse adds
{"tool_response": {"success": true, "commandName": "pirate-voice"},
 "duration_ms": 5}
```

- Input field: **`skill`**, the skill name. Plugin skills are namespaced `plugin-name:skill-name`.
- **`args`**: an optional free-text string.
- The `duration_ms` for a skill load is how long it takes to *load* the skill
  (milliseconds). It is not the duration of the work Claude then does.

## Output formats

Exit 0 + JSON on stdout (parsed when stdout starts with `{` and ends with `}`).
Plain stdout on SessionStart / UserPromptSubmit is also added to context, but
skillwire always emits JSON.

**Add context** (SessionStart, UserPromptSubmit, PostToolUse; PreToolUse also accepts it):

```json
{"hookSpecificOutput": {"hookEventName": "UserPromptSubmit",
                        "additionalContext": "..."}}
```

The docs advise writing context "as factual statements, not imperative system
instructions, to avoid triggering prompt-injection defenses". skillwire phrases
its context that way.

**Deny a tool call** (PreToolUse):

```json
{"hookSpecificOutput": {"hookEventName": "PreToolUse",
                        "permissionDecision": "deny",
                        "permissionDecisionReason": "..."}}
```

`permissionDecision` ∈ `allow | deny | ask | defer`. Across multiple hooks the
precedence is `deny > defer > ask > allow`. The reason is shown to Claude.

**User-visible banner**: the top-level `systemMessage` field (string).

**Limits**: `additionalContext`, `systemMessage`, and plain stdout are each capped
at 10,000 characters.

### Exit codes
- `0`: success, and stdout is parsed.
- `2`: blocking error (on PreToolUse it denies the call). **skillwire never uses this.**
- Anything else: a non-blocking error notice. skillwire avoids this too, because
  every dispatcher catches all exceptions and exits 0.

### Timeouts
`timeout` is set per hook in seconds. The default is 600, lowered to 30 on
UserPromptSubmit. A timed-out PreToolUse hook does **not** block the tool.

## Matchers

For tool events the matcher filters on `tool_name`. A value made only of letters,
digits, `_`, `-`, spaces, `,`, and `|` is an exact match, so `"Skill"` matches
only the skill tool.

## Plugin registration

- Manifest: `.claude-plugin/plugin.json`. Only `name` is required (kebab-case).
- Hooks: `hooks/hooks.json` is loaded automatically and must wrap the event
  map in a top-level `"hooks"` key.
- Command hooks support **exec form**: `{"type": "command", "command": "python3", "args": ["${CLAUDE_PLUGIN_ROOT}/scripts/x.py"]}`.
  The docs recommend it when a path placeholder is used, because no shell
  quoting is needed.
- Hook processes receive the env vars `CLAUDE_PLUGIN_ROOT`, `CLAUDE_PLUGIN_DATA`,
  and `CLAUDE_PROJECT_DIR`.
- `bin/` under the plugin root is put on the **Bash tool's** PATH while the plugin
  is enabled. It is not added to the user's own shell PATH.

## Marketplace

- `.claude-plugin/marketplace.json` requires `name`, `owner` (`{name}`), and `plugins[]`.
  Each entry requires `name` and `source`.
- A relative `source` is resolved from the marketplace root (the directory that
  contains `.claude-plugin/`). `"./"` makes the plugin the marketplace root itself.
- The entry name should equal the manifest `name`.
- Commands: `/plugin marketplace add <path|owner/repo>`, `/plugin install skillwire@skillwire`.
  The shell equivalents are `claude plugin marketplace add … [--scope user|project|local]`,
  `claude plugin install … [-s scope]`, `claude plugin uninstall … [-s scope] [--keep-data]`,
  `claude plugin marketplace remove <name>`, and `claude plugin validate <dir>`.

## Deviations from the original brief

| Brief said | Docs / reality | What skillwire does |
|---|---|---|
| `skillwire.yaml` | No YAML lib in the stdlib | `skillwire.json` (the brief allowed this) |
| "duration" of a skill | PostToolUse `duration_ms` = load time only | Records `duration_ms` and labels it *load* time in reports |
| Router "Add context … required skills (load before responding)" | Docs warn against imperative injected instructions | States it as policy ("project policy: load …") rather than as a system command |
| Chaos banner "print at session start" | `systemMessage` shows to the user; SessionStart also takes `additionalContext` | Emits both |
| Dispatcher exit 0 | Correct. Exit 2 would block | Always exits 0. Denials go through JSON `permissionDecision` |
