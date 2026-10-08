import copy
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

FIXTURES = ROOT / "tests" / "fixtures"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text())


class Env:
    """An isolated HOME + project, with helpers to write config and fire events."""

    def __init__(self, home: Path, project: Path):
        self.home = home
        self.project = project

    @property
    def data(self) -> Path:
        return self.home / ".claude" / "skillwire"

    def write_global(self, cfg) -> Path:
        p = self.home / ".claude" / "skillwire.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(cfg if isinstance(cfg, str) else json.dumps(cfg))
        return p

    def write_project(self, cfg) -> Path:
        p = self.project / ".claude" / "skillwire.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(cfg if isinstance(cfg, str) else json.dumps(cfg))
        return p

    def event(self, fixture: str, **over) -> dict:
        ev = copy.deepcopy(load_fixture(fixture))
        ev["cwd"] = str(self.project)
        ev.update(over)
        return ev

    def fire(self, fixture: str, **over):
        from skillwire.dispatch import run_event
        return run_event(self.event(fixture, **over))

    def skill(self, name: str, **over):
        """Fire PreToolUse for a skill, then PostToolUse if it wasn't denied."""
        ti = {"skill": name, "args": ""}
        pre = self.fire("pre_tool_use_skill", tool_input=ti, **over)
        denied = bool(pre and pre.get("hookSpecificOutput", {}).get("permissionDecision") == "deny")
        post = None if denied else self.fire("post_tool_use_skill", tool_input=ti, **over)
        return pre, post

    def make_skill(self, name: str, description: str, where: str = "project", body: str = "Body.\n") -> Path:
        base = (self.project / ".claude" / "skills") if where == "project" else (self.home / ".claude" / "skills")
        d = base / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "SKILL.md").write_text(f"---\nname: {name}\ndescription: {description}\n---\n{body}")
        return d

    def errors(self) -> str:
        p = self.data / "errors.log"
        return p.read_text() if p.exists() else ""


@pytest.fixture
def env(tmp_path, monkeypatch):
    home = tmp_path / "home"
    project = tmp_path / "project"
    home.mkdir()
    project.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))
    for var in ("SKILLWIRE_HOME", "SKILLWIRE_CHAOS", "SKILLWIRE_CHAOS_SEED", "ANTHROPIC_API_KEY", "SKILLWIRE_DRY_RUN"):
        monkeypatch.delenv(var, raising=False)
    return Env(home, project)


def ctx_of(out) -> str:
    return (out or {}).get("hookSpecificOutput", {}).get("additionalContext", "")


def deny_of(out):
    hso = (out or {}).get("hookSpecificOutput", {})
    return hso.get("permissionDecisionReason") if hso.get("permissionDecision") == "deny" else None
