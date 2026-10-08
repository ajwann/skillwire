"""Filesystem locations. Everything skillwire writes lives under data_dir()."""
from __future__ import annotations

import os
from pathlib import Path


def claude_home() -> Path:
    return Path.home() / ".claude"


def data_dir() -> Path:
    """~/.claude/skillwire (override with SKILLWIRE_HOME, used by tests and doctor)."""
    override = os.environ.get("SKILLWIRE_HOME")
    d = Path(override) if override else claude_home() / "skillwire"
    d.mkdir(parents=True, exist_ok=True)
    return d


def db_path() -> Path:
    return data_dir() / "skillwire.db"


def errors_log() -> Path:
    return data_dir() / "errors.log"


def backups_dir() -> Path:
    d = data_dir() / "backups"
    d.mkdir(parents=True, exist_ok=True)
    return d


def global_config_path() -> Path:
    return claude_home() / "skillwire.json"


def project_dir(event: dict | None = None) -> Path:
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env:
        return Path(env)
    if event and event.get("cwd"):
        return Path(event["cwd"])
    return Path.cwd()


def project_config_path(project: Path) -> Path:
    return project / ".claude" / "skillwire.json"


def plugin_root() -> Path:
    env = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[2]


# Variables a child process needs to run normally. Nothing else is passed, so
# generators and sandboxed dispatchers never inherit tokens from the user's shell.
CHILD_ENV_VARS = ("PATH", "HOME", "USER", "LOGNAME", "SHELL", "LANG", "LC_ALL", "LC_CTYPE",
                  "TMPDIR", "TZ", "SYSTEMROOT")


def child_env(**extra: str) -> dict[str, str]:
    env = {}
    for name in CHILD_ENV_VARS:
        val = os.environ.get(name)
        if val is not None:
            env[name] = val
    env.update({k: str(v) for k, v in extra.items()})
    return env
