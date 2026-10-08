import json
import shutil

from conftest import ROOT
from skillwire import doctor


def plugin_copy(tmp_path):
    dst = tmp_path / "plugin"
    shutil.copytree(ROOT, dst, ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache", "tests"))
    return dst


def test_doctor_passes_on_shipped_plugin(env):
    code, text = doctor.run(env.project, ROOT, run_claude=False)
    assert code == 0, text
    for ev in ("SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse"):
        assert f"✔ {ev}: exit 0" in text
    assert "matcher 'Skill'" in text


def test_doctor_does_not_touch_real_telemetry(env):
    doctor.run(env.project, ROOT, run_claude=False)
    assert not (env.data / "skillwire.db").exists()


def test_doctor_flags_bad_matcher_and_missing_event(env, tmp_path):
    root = plugin_copy(tmp_path)
    hooks = json.loads((root / "hooks" / "hooks.json").read_text())
    hooks["hooks"]["PreToolUse"][0]["matcher"] = "Bash"
    del hooks["hooks"]["PostToolUse"]
    (root / "hooks" / "hooks.json").write_text(json.dumps(hooks))
    code, text = doctor.run(env.project, root, run_claude=False)
    assert code == 1
    assert "matcher is 'Bash', expected 'Skill'" in text
    assert "PostToolUse: not registered" in text


def test_doctor_flags_unwrapped_hooks_file(env, tmp_path):
    root = plugin_copy(tmp_path)
    hooks = json.loads((root / "hooks" / "hooks.json").read_text())
    (root / "hooks" / "hooks.json").write_text(json.dumps(hooks["hooks"]))
    code, text = doctor.run(env.project, root, run_claude=False)
    assert code == 1 and 'top-level "hooks" key' in text


def test_doctor_flags_corrupted_config_and_semantics(env):
    env.write_project('{"router": ')
    code, text = doctor.run(env.project, ROOT, run_claude=False)
    assert code == 1 and "invalid JSON" in text
    env.write_project({"hijacker": {"map": {"a": "b", "b": "a"}}, "chaos": {"rate": 2}})
    code, text = doctor.run(env.project, ROOT, run_claude=False)
    assert code == 1 and "cycle" in text and "chaos.rate" in text


def test_doctor_catches_dispatcher_that_misbehaves(env, tmp_path):
    root = plugin_copy(tmp_path)
    (root / "scripts" / "on_post_tool_use.py").write_text("import sys\nprint('not json')\n")
    code, text = doctor.run(env.project, root, run_claude=False)
    assert code == 1 and "PostToolUse: stdout is not JSON" in text


def test_doctor_reports_module_errors(env, tmp_path):
    root = plugin_copy(tmp_path)
    (root / "lib" / "skillwire" / "modules" / "router.py").write_text("def handle(ctx):\n    raise RuntimeError('router exploded')\n")
    code, text = doctor.run(env.project, root, run_claude=False)
    assert code == 1 and "router exploded" in text
    assert "✔ UserPromptSubmit: exit 0" in text  # crash still didn't block the hook
