"""Config loading: defaults <- ~/.claude/skillwire.json <- <project>/.claude/skillwire.json.

Dicts merge recursively, and the project layer wins. Lists and scalars are
replaced rather than merged. A file that is unreadable or not a JSON object is
skipped with a logged error, so a corrupted config falls back to the other
layers and never breaks a hook.
"""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

from . import paths
from .errors import log_error

MODULES = ("router", "telemetry", "chaining", "hijacker", "allowlist", "chaos", "jit", "ab")

DEFAULTS: dict[str, Any] = {
    "router": {
        "enabled": True,
        "rules": [],
        "llm_classify": False,
        "llm_model": "claude-haiku-5-5",
        "llm_timeout": 2.0,
    },
    "telemetry": {"enabled": True, "store_prompts": False},
    "chaining": {"enabled": True, "chains": {}, "skip_if_loaded": True},
    "hijacker": {"enabled": False, "map": {}},
    "allowlist": {"enabled": False, "rules": []},
    "chaos": {"enabled": False, "rate": 0.2, "seed": None, "exempt": []},
    "jit": {"enabled": False, "timeout": 30, "skill_dirs": []},
    "ab": {"enabled": False, "min_sessions": 30},
    "skill_dirs": [],
}


def deep_merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for key, val in over.items():
        if isinstance(val, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], val)
        else:
            out[key] = copy.deepcopy(val)
    return out


def read_layer(path: Path) -> tuple[dict | None, str | None]:
    """Return (data, problem). A missing file is (None, None)."""
    if not path.exists():
        return None, None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, f"{path}: unreadable or invalid JSON ({exc})"
    if not isinstance(data, dict):
        return None, f"{path}: top level must be a JSON object"
    return data, None


def sanitize(data: dict, source: str) -> tuple[dict, list[str]]:
    """Drop module sections with the wrong shape so they can't crash a module."""
    problems = []
    clean = {}
    for key, val in data.items():
        if key in MODULES and not isinstance(val, dict):
            problems.append(f"{source}: '{key}' must be an object; ignored")
            continue
        if key in MODULES and "enabled" in val and not isinstance(val["enabled"], bool):
            problems.append(f"{source}: '{key}.enabled' must be true/false; ignored")
            val = {k: v for k, v in val.items() if k != "enabled"}
        clean[key] = val
    return clean, problems


def load(project: Path | None = None) -> tuple[dict, list[str]]:
    """Return (merged_config, problems). Never raises."""
    cfg = copy.deepcopy(DEFAULTS)
    problems: list[str] = []
    layers = [paths.global_config_path()]
    if project is not None:
        layers.append(paths.project_config_path(project))
    for layer in layers:
        try:
            data, problem = read_layer(layer)
            if problem:
                problems.append(problem)
                log_error("config", message=problem)
            if data:
                data, more = sanitize(data, str(layer))
                problems.extend(more)
                cfg = deep_merge(cfg, data)
        except Exception as exc:  # pragma: no cover - belt and braces
            problems.append(f"{layer}: {exc}")
            log_error("config", exc)
    return cfg, problems


def config_sources(project: Path | None) -> list[Path]:
    out = [paths.global_config_path()]
    if project is not None:
        out.append(paths.project_config_path(project))
    return [p for p in out if p.exists()]


# ---------------------------------------------------------------- validation

def find_cycles(mapping: dict) -> list[list[str]]:
    """Cycles in a {from: to} redirect map, each as a list of nodes."""
    cycles, seen_cycles = [], set()
    for start in mapping:
        path, node = [], start
        while node in mapping and node not in path:
            path.append(node)
            node = mapping[node]
        if node in path:
            cyc = path[path.index(node):]
            key = frozenset(cyc)
            if key not in seen_cycles:
                seen_cycles.add(key)
                cycles.append(cyc + [node])
    return cycles


def validate(cfg: dict) -> list[str]:
    """Semantic checks used by `skillwire doctor`. Returns a list of problems."""
    problems = []
    for key in cfg:
        if key not in MODULES and key not in DEFAULTS and not key.startswith("$"):
            problems.append(f"unknown top-level key '{key}'")

    rules = cfg["router"].get("rules", [])
    if not isinstance(rules, list):
        problems.append("router.rules must be a list")
        rules = []
    for i, rule in enumerate(rules):
        if not isinstance(rule, dict) or not rule.get("skill"):
            problems.append(f"router.rules[{i}] needs a 'skill'")
            continue
        if rule.get("priority", "suggested") not in ("required", "suggested"):
            problems.append(f"router.rules[{i}].priority must be 'required' or 'suggested'")
        for rx in rule.get("regex", []) or []:
            try:
                re.compile(rx)
            except re.error as exc:
                problems.append(f"router.rules[{i}] bad regex {rx!r}: {exc}")

    hmap = cfg["hijacker"].get("map", {})
    if not isinstance(hmap, dict):
        problems.append("hijacker.map must be an object")
    else:
        for src, dst in hmap.items():
            if src == dst:
                problems.append(f"hijacker.map redirects '{src}' to itself (ignored at runtime)")
        for cyc in find_cycles({k: v for k, v in hmap.items() if k != v}):
            problems.append("hijacker.map cycle (ignored at runtime): " + " -> ".join(cyc))

    chains = cfg["chaining"].get("chains", {})
    if not isinstance(chains, dict) or not all(isinstance(v, list) for v in chains.values()):
        problems.append("chaining.chains must map skill -> [skills]")

    rate = cfg["chaos"].get("rate", 0.2)
    if not isinstance(rate, (int, float)) or not 0 <= rate <= 1:
        problems.append("chaos.rate must be a number in [0, 1]")

    arules = cfg["allowlist"].get("rules", [])
    if not isinstance(arules, list):
        problems.append("allowlist.rules must be a list")
    else:
        for i, rule in enumerate(arules):
            if not isinstance(rule, dict) or not rule.get("paths"):
                problems.append(f"allowlist.rules[{i}] needs 'paths'")
            elif "allow" not in rule and "block" not in rule:
                problems.append(f"allowlist.rules[{i}] needs 'allow' or 'block'")

    timeout = cfg["jit"].get("timeout", 30)
    if not isinstance(timeout, (int, float)) or timeout <= 0:
        problems.append("jit.timeout must be a positive number")
    return problems
