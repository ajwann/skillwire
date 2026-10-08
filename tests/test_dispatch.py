import json
import subprocess
import sys

import pytest

from conftest import ROOT, load_fixture
from skillwire import paths

SCRIPTS = {
    "SessionStart": "on_session_start.py",
    "UserPromptSubmit": "on_user_prompt_submit.py",
    "PreToolUse": "on_pre_tool_use.py",
    "PostToolUse": "on_post_tool_use.py",
}
FIXTURE_FOR = {
    "SessionStart": "session_start",
    "UserPromptSubmit": "user_prompt_submit",
    "PreToolUse": "pre_tool_use_skill",
    "PostToolUse": "post_tool_use_skill",
}


def run_script(event_name, stdin, env):
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / SCRIPTS[event_name])],
        input=stdin, capture_output=True, text=True, timeout=30,
        env=paths.child_env(HOME=str(env.home), CLAUDE_PROJECT_DIR=str(env.project)),
    )
    return proc


@pytest.mark.parametrize("event_name", list(SCRIPTS))
def test_every_dispatcher_exits_zero_on_fixture(env, event_name):
    ev = env.event(FIXTURE_FOR[event_name])
    proc = run_script(event_name, json.dumps(ev), env)
    assert proc.returncode == 0, proc.stderr
    if proc.stdout:
        out = json.loads(proc.stdout)
        if "hookSpecificOutput" in out:
            assert out["hookSpecificOutput"]["hookEventName"] == event_name


@pytest.mark.parametrize("stdin", ["", "not json", "[1,2]", '{"hook_event_name": 5}'])
@pytest.mark.parametrize("event_name", list(SCRIPTS))
def test_garbage_stdin_never_blocks(env, event_name, stdin):
    proc = run_script(event_name, stdin, env)
    assert proc.returncode == 0
    assert proc.stdout == "" or json.loads(proc.stdout)


def test_fixtures_have_documented_fields():
    for name in FIXTURE_FOR.values():
        ev = load_fixture(name)
        for key in ("session_id", "transcript_path", "cwd", "hook_event_name"):
            assert key in ev, (name, key)
    assert load_fixture("user_prompt_submit")["prompt"]
    pre = load_fixture("pre_tool_use_skill")
    assert pre["tool_name"] == "Skill" and "skill" in pre["tool_input"] and pre["tool_use_id"]
    post = load_fixture("post_tool_use_skill")
    assert "tool_response" in post and "duration_ms" in post


def test_non_skill_tools_are_ignored(env):
    env.write_project({"chaos": {"enabled": True, "rate": 1.0}})
    assert env.fire("pre_tool_use_bash") is None


def test_module_crash_is_logged_and_swallowed(env, monkeypatch):
    from skillwire import dispatch
    from skillwire.modules import telemetry

    def boom(ctx):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(telemetry, "handle", boom)
    out = dispatch.run_event(env.event("pre_tool_use_skill"))
    assert out is None
    assert "kaboom" in env.errors() and "PreToolUse/telemetry" in env.errors()


def test_unknown_event_is_noop(env):
    assert env.fire("session_start", hook_event_name="Notification") is None
