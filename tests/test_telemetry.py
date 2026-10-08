import sqlite3
import subprocess
import sys
import time

from conftest import ROOT


def rows(env, sql="SELECT * FROM events ORDER BY id"):
    conn = sqlite3.connect(env.data / "skillwire.db")
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(sql)]
    finally:
        conn.close()


def test_prompt_is_hashed_not_stored_by_default(env):
    env.fire("user_prompt_submit", prompt="secret plans")
    (r,) = rows(env)
    assert r["outcome"] == "prompt" and r["prompt"] is None
    assert len(r["prompt_hash"]) == 16 and "secret" not in r["prompt_hash"]


def test_store_prompts_opt_in(env):
    env.write_project({"telemetry": {"store_prompts": True}})
    env.fire("user_prompt_submit", prompt="keep me")
    assert rows(env)[0]["prompt"] == "keep me"


def test_loaded_with_duration_session_and_prompt_hash(env):
    env.fire("user_prompt_submit", prompt="hi")
    env.fire("pre_tool_use_skill")  # allowed: nothing recorded at Pre
    env.fire("post_tool_use_skill")
    r = rows(env)
    assert [x["outcome"] for x in r] == ["prompt", "loaded"]
    loaded = r[1]
    assert loaded["skill"] == "code-review" and loaded["duration_ms"] == 12
    assert loaded["session_id"] == "sess-fixture-1"
    assert loaded["prompt_hash"] == r[0]["prompt_hash"]


def test_failed_load(env):
    env.fire("post_tool_use_skill", tool_response={"success": False})
    assert rows(env)[0]["outcome"] == "failed"


def test_disabled_telemetry_writes_nothing(env):
    env.write_project({"telemetry": {"enabled": False}})
    env.fire("user_prompt_submit")
    env.fire("post_tool_use_skill")
    assert not (env.data / "skillwire.db").exists()


def seed(env):
    from skillwire import db
    conn = db.connect()
    now = time.time()
    for sid in ("s1", "s2", "s3"):
        db.insert_event(conn, ts=now - 3600, session_id=sid, event="UserPromptSubmit", outcome="prompt")
    for sid, ms in (("s1", 10), ("s2", 30), ("s3", 20)):
        db.insert_event(conn, ts=now - 3000, session_id=sid, event="PostToolUse", skill="tdd", outcome="loaded", duration_ms=ms)
    db.insert_event(conn, ts=now - 3000, session_id="s1", event="PreToolUse", skill="old-review",
                    outcome="redirected", module="hijacker", redirect_to="code-review")
    db.insert_event(conn, ts=now - 3000, session_id="s2", event="PreToolUse", skill="deploy",
                    outcome="denied", module="allowlist")
    # outside a 7d window
    db.insert_event(conn, ts=now - 20 * 86400, session_id="old", event="PostToolUse", skill="ancient", outcome="loaded")
    conn.close()


def test_report_tables(env):
    from skillwire import config, report
    seed(env)
    env.make_skill("tdd", "Test driven development")
    env.make_skill("lonely", "Never used", where="user")
    cfg, _ = config.load(env.project)
    text = report.build("7d", env.project, cfg)
    assert "3 prompts across 3 sessions" in text
    assert "| tdd | 3 | 3 | 20.0 |" in text
    assert "| old-review | code-review | 1 |" in text
    assert "| deploy | allowlist | 1 |" in text
    never = text.split("## Never-triggered skills")[1]
    assert "lonely" in never and "tdd" not in never
    assert "ancient" not in text
    assert "ancient" in report.build("30d", env.project, cfg)


def test_report_unused_via_cli(env):
    seed(env)
    env.make_skill("tdd", "x")
    env.make_skill("lonely", "y")
    proc = subprocess.run([sys.executable, str(ROOT / "bin" / "skillwire"), "report", "7d", "--unused"],
                          capture_output=True, text=True, env={"HOME": str(env.home), "PATH": "/usr/bin:/bin",
                                                               "CLAUDE_PROJECT_DIR": str(env.project)})
    assert proc.returncode == 0, proc.stderr
    assert "lonely" in proc.stdout and "| tdd |" not in proc.stdout


def test_bad_window(env):
    from skillwire.cli import main
    assert main(["report", "forever"]) == 2
