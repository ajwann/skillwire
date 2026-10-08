"""End-to-end smoke test against the real `claude` CLI.

Installs skillwire from this repo's local marketplace into a temp project
(project scope only, so user settings are untouched), runs one headless
session, and checks that the hooks fired by reading the telemetry DB. It uses
a real model call, so it only runs when SKILLWIRE_E2E=1:

    SKILLWIRE_E2E=1 python3 -m pytest tests/test_e2e.py -v -s
"""
import json
import os
import shutil
import sqlite3
import subprocess

import pytest

from conftest import ROOT

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(os.environ.get("SKILLWIRE_E2E") != "1", reason="set SKILLWIRE_E2E=1 to run"),
    pytest.mark.skipif(shutil.which("claude") is None, reason="claude CLI not on PATH"),
]


def claude(*args, cwd, env, timeout=240):
    proc = subprocess.run(["claude", *args], cwd=str(cwd), env=env, capture_output=True, text=True, timeout=timeout)
    print(f"$ claude {' '.join(args)}\n{proc.stdout[-2000:]}{proc.stderr[-2000:]}")
    return proc


def test_install_from_local_marketplace_and_hooks_fire(tmp_path):
    project = tmp_path / "proj"
    data = tmp_path / "skillwire-data"
    for name, desc in (("e2e-probe", "Old greeting skill. Use when asked for the e2e probe greeting."),
                       ("e2e-replacement", "New greeting skill that replaces e2e-probe.")):
        d = project / ".claude" / "skills" / name
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(f"---\nname: {name}\ndescription: {desc}\n---\nReply with exactly: HELLO FROM {name.upper()}\n")
    (project / ".claude" / "skillwire.json").write_text(json.dumps({
        "router": {"rules": [{"skill": "e2e-probe", "keywords": ["probe greeting"], "priority": "required"}]},
        "hijacker": {"enabled": True, "map": {"e2e-probe": "e2e-replacement"}},
    }))
    env = {**os.environ, "SKILLWIRE_HOME": str(data)}
    env.pop("CLAUDE_PROJECT_DIR", None)

    try:
        assert claude("plugin", "marketplace", "add", str(ROOT), "--scope", "project", cwd=project, env=env).returncode == 0
        assert claude("plugin", "install", "skillwire@skillwire", "--scope", "project", cwd=project, env=env).returncode == 0
        settings = json.loads((project / ".claude" / "settings.json").read_text())
        assert settings.get("enabledPlugins", {}).get("skillwire@skillwire") is True

        run = claude("-p", "--model", "haiku", "--permission-mode", "bypassPermissions",
                     "Give me the probe greeting. Use the Skill tool to load the e2e-probe skill first.",
                     cwd=project, env=env)
        assert run.returncode == 0

        db = data / "skillwire.db"
        assert db.exists(), "telemetry DB missing: hooks did not fire"
        rows = sqlite3.connect(db).execute(
            "SELECT event, skill, outcome, module, redirect_to FROM events ORDER BY id").fetchall()
        print("telemetry rows:", rows)
        assert ("UserPromptSubmit", None, "prompt", None, None) in rows               # UserPromptSubmit fired
        assert ("UserPromptSubmit", "e2e-probe", "routed", "router", None) in rows    # router matched
        assert ("PreToolUse", "e2e-probe", "redirected", "hijacker", "e2e-replacement") in rows  # deny honoured
        assert any(r[1] == "e2e-replacement" and r[2] == "loaded" for r in rows), \
            "Claude did not load the replacement after the redirect"
        errors = data / "errors.log"
        assert not errors.exists() or not errors.read_text().strip(), errors.read_text()
    finally:
        claude("plugin", "uninstall", "skillwire@skillwire", "--scope", "project", cwd=project, env=env)
        claude("plugin", "marketplace", "remove", "skillwire", "--scope", "project", cwd=project, env=env)
