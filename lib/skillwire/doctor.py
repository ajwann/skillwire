"""`skillwire doctor`: validate config, hook registration, and each dispatcher."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from . import SKILL_TOOL, config, paths

# From docs/HOOK_SCHEMA.md
EXPECTED = {
    "SessionStart": {"script": "on_session_start.py", "matcher": None},
    "UserPromptSubmit": {"script": "on_user_prompt_submit.py", "matcher": None},
    "PreToolUse": {"script": "on_pre_tool_use.py", "matcher": SKILL_TOOL},
    "PostToolUse": {"script": "on_post_tool_use.py", "matcher": SKILL_TOOL},
}
KNOWN_EVENTS = {"SessionStart", "SessionEnd", "UserPromptSubmit", "PreToolUse", "PostToolUse", "PostToolUseFailure",
                "Notification", "Stop", "SubagentStart", "SubagentStop", "PreCompact", "PostCompact",
                "PermissionRequest", "CwdChanged", "FileChanged", "UserPromptExpansion"}


class Report:
    def __init__(self):
        self.lines: list[str] = []
        self.failures = 0

    def ok(self, msg):
        self.lines.append(f"  ✔ {msg}")

    def warn(self, msg):
        self.lines.append(f"  ! {msg}")

    def fail(self, msg):
        self.failures += 1
        self.lines.append(f"  ✖ {msg}")

    def section(self, title):
        self.lines.append(f"\n{title}")


def fake_events(project: Path) -> dict[str, dict]:
    base = {"session_id": "skillwire-doctor", "transcript_path": str(project / "doctor.jsonl"),
            "cwd": str(project), "permission_mode": "default"}
    tool = {**base, "prompt_id": "doctor-prompt", "tool_name": SKILL_TOOL,
            "tool_input": {"skill": "skillwire-doctor-probe", "args": ""}, "tool_use_id": "toolu_doctor"}
    return {
        "SessionStart": {**base, "hook_event_name": "SessionStart", "source": "startup"},
        "UserPromptSubmit": {**base, "hook_event_name": "UserPromptSubmit", "prompt_id": "doctor-prompt",
                             "prompt": "skillwire doctor probe prompt"},
        "PreToolUse": {**tool, "hook_event_name": "PreToolUse"},
        "PostToolUse": {**tool, "hook_event_name": "PostToolUse",
                        "tool_response": {"success": True, "commandName": "skillwire-doctor-probe"},
                        "duration_ms": 1},
    }


def check_config(rep: Report, project: Path) -> dict:
    rep.section("Config")
    sources = config.config_sources(project)
    if sources:
        for s in sources:
            rep.ok(f"found {s}")
    else:
        rep.warn("no skillwire.json found; using defaults (router, telemetry, chaining on)")
    cfg, problems = config.load(project)
    for p in problems:
        rep.fail(p)
    for p in config.validate(cfg):
        rep.fail(p)
    if not problems:
        on = [m for m in config.MODULES if cfg[m].get("enabled")]
        rep.ok("enabled modules: " + (", ".join(on) or "none"))
    from .modules import chaos
    if cfg["chaos"].get("enabled") and not chaos.active(cfg):
        rep.warn("chaos.enabled is true but SKILLWIRE_CHAOS!=1 in this shell, so chaos is inactive here")
    if cfg["router"].get("llm_classify"):
        rep.warn("router.llm_classify is on: the classifier only runs inside hooks when the plugin's "
                 "classifier_api_key option is set (/plugin → skillwire → configure); otherwise regex only")
    return cfg


def check_hooks(rep: Report, root: Path) -> dict:
    rep.section("Hook registration (vs docs/HOOK_SCHEMA.md)")
    hooks_file = root / "hooks" / "hooks.json"
    try:
        data = json.loads(hooks_file.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        rep.fail(f"{hooks_file}: {exc}")
        return {}
    events = data.get("hooks")
    if not isinstance(events, dict):
        rep.fail('hooks.json must wrap the event map in a top-level "hooks" key')
        return {}
    for ev in events:
        if ev not in KNOWN_EVENTS:
            rep.fail(f"unknown hook event '{ev}'")
    for ev, want in EXPECTED.items():
        groups = events.get(ev)
        if not isinstance(groups, list) or not groups:
            rep.fail(f"{ev}: not registered")
            continue
        for g in groups:
            matcher = g.get("matcher")
            if want["matcher"] and matcher != want["matcher"]:
                rep.fail(f"{ev}: matcher is {matcher!r}, expected {want['matcher']!r} (the skill tool's name)")
            for h in g.get("hooks", []):
                if h.get("type") != "command":
                    rep.fail(f"{ev}: handler type must be 'command'")
                    continue
                argv = [h.get("command", "")] + list(h.get("args", []))
                resolved = [a.replace("${CLAUDE_PLUGIN_ROOT}", str(root)) for a in argv]
                script = next((Path(a) for a in resolved if a.endswith(".py")), None)
                if script is None or script.name != want["script"]:
                    rep.fail(f"{ev}: expected to run scripts/{want['script']}, got {argv}")
                elif not script.exists():
                    rep.fail(f"{ev}: {script} does not exist")
                elif "args" not in h:
                    rep.warn(f"{ev}: shell-form command; exec form (command + args) is what the docs recommend")
                else:
                    t = h.get("timeout")
                    if t is not None and not isinstance(t, (int, float)):
                        rep.fail(f"{ev}: timeout must be a number of seconds")
                    rep.ok(f"{ev}: {'matcher ' + repr(matcher) + ', ' if matcher else ''}exec form → {script.name}")
    for mf in ("plugin.json", "marketplace.json"):
        p = root / ".claude-plugin" / mf
        try:
            json.loads(p.read_text())
            rep.ok(f".claude-plugin/{mf} parses")
        except (OSError, json.JSONDecodeError) as exc:
            rep.fail(f".claude-plugin/{mf}: {exc}")
    return events


def check_claude_validate(rep: Report, root: Path) -> None:
    claude = shutil.which("claude")
    if not claude:
        rep.warn("`claude` not on PATH; skipped `claude plugin validate`")
        return
    try:
        proc = subprocess.run([claude, "plugin", "validate", str(root)], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        rep.warn(f"`claude plugin validate` could not run: {exc}")
        return
    tail = (proc.stdout + proc.stderr).strip().splitlines()[-1:] or [""]
    (rep.ok if proc.returncode == 0 else rep.fail)(f"claude plugin validate: {tail[0]}")


def check_dispatchers(rep: Report, root: Path, project: Path, hook_events: dict) -> None:
    rep.section("Dispatchers (fake events, sandboxed data dir, JIT dry-run)")
    sandbox = Path(tempfile.mkdtemp(prefix="skillwire-doctor-"))
    try:
        env = {**os.environ, "SKILLWIRE_HOME": str(sandbox), "SKILLWIRE_DRY_RUN": "1",
               "CLAUDE_PROJECT_DIR": str(project), "CLAUDE_PLUGIN_ROOT": str(root)}
        for ev, payload in fake_events(project).items():
            script = root / "scripts" / EXPECTED[ev]["script"]
            limit = 60
            for g in hook_events.get(ev, []):
                for h in g.get("hooks", []):
                    limit = h.get("timeout", limit)
            t0 = time.time()
            try:
                proc = subprocess.run([sys.executable, str(script)], input=json.dumps(payload), capture_output=True,
                                      text=True, timeout=limit, env=env, cwd=str(project))
            except subprocess.TimeoutExpired:
                rep.fail(f"{ev}: exceeded its {limit}s hook timeout")
                continue
            ms = (time.time() - t0) * 1000
            if proc.returncode != 0:
                rep.fail(f"{ev}: exit {proc.returncode} (must always be 0): {proc.stderr.strip()[-300:]}")
                continue
            out = proc.stdout.strip()
            if out:
                try:
                    data = json.loads(out)
                except json.JSONDecodeError:
                    rep.fail(f"{ev}: stdout is not JSON: {out[:120]!r}")
                    continue
                hso = data.get("hookSpecificOutput", {})
                if hso and hso.get("hookEventName") != ev:
                    rep.fail(f"{ev}: hookSpecificOutput.hookEventName is {hso.get('hookEventName')!r}")
                    continue
                if "permissionDecision" in hso and ev != "PreToolUse":
                    rep.fail(f"{ev}: permissionDecision is only valid on PreToolUse")
                    continue
            note = "no output" if not out else "valid JSON"
            rep.ok(f"{ev}: exit 0, {note}, {ms:.0f} ms")
        log = sandbox / "errors.log"
        if log.exists() and log.read_text().strip():
            rep.fail("modules logged errors during the dry run:\n      " +
                     log.read_text().strip()[-1500:].replace("\n", "\n      "))
        else:
            rep.ok("no module errors logged")
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)


def run(project: Path, root: Path | None = None, run_claude: bool = True) -> tuple[int, str]:
    root = root or paths.plugin_root()
    rep = Report()
    rep.lines.append(f"skillwire doctor (python {sys.version.split()[0]}, plugin root {root}, project {project})")
    if sys.version_info < (3, 8):
        rep.fail("Python 3.8+ required")
    try:
        d = paths.data_dir()
        (d / ".doctor").write_text("ok")
        (d / ".doctor").unlink()
        rep.ok(f"data dir writable: {d}")
    except OSError as exc:
        rep.fail(f"data dir not writable: {exc}")
    check_config(rep, project)
    hook_events = check_hooks(rep, root)
    if run_claude:
        check_claude_validate(rep, root)
    check_dispatchers(rep, root, project, hook_events)
    rep.lines.append("\n" + ("All checks passed." if rep.failures == 0 else f"{rep.failures} problem(s) found."))
    return (0 if rep.failures == 0 else 1), "\n".join(rep.lines)
