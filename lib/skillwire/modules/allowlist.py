"""Repo allowlist / denylist (PreToolUse on Skill).

Config:
  allowlist.rules = [
    {"paths": ["~/work/*"], "block": ["personal-*"]},
    {"paths": ["~/work/payments"], "allow": ["code-review", "security-*"]}
  ]

A rule applies when one of its path globs matches the working directory or
any of its ancestors, so "~/work/payments" also covers subdirectories. Skill
patterns are globs, matched against the full name ("plugin:skill") and the
bare name. In each applicable rule, block beats allow. When any applicable
rule has an allow list, the skill must appear in one of those lists.
"""
from __future__ import annotations

import os
from fnmatch import fnmatchcase

from ..hookio import Decision

GLOB_CHARS = set("*?[")


def _dir_candidates(cwd: str) -> list[str]:
    out = []
    for base in {os.path.abspath(cwd), os.path.realpath(cwd)}:
        p = base
        while True:
            out.append(p)
            parent = os.path.dirname(p)
            if parent == p:
                break
            p = parent
    return out


def _norm_pattern(pat: str) -> list[str]:
    pat = os.path.expanduser(str(pat)).rstrip("/") or "/"
    pats = [pat]
    if not GLOB_CHARS & set(pat):
        pats.append(os.path.realpath(pat))
    else:  # resolve the literal prefix so /tmp/* also matches /private/tmp/*
        cut = min(pat.index(ch) for ch in GLOB_CHARS if ch in pat)
        head = pat[:cut]
        root = head.rstrip("/") if head.endswith("/") else os.path.dirname(head)
        if root and os.path.exists(root):
            pats.append(os.path.realpath(root) + pat[len(root):])
    return pats


def _path_matches(rule_paths, cwd: str) -> str | None:
    cands = _dir_candidates(cwd)
    for raw in rule_paths if isinstance(rule_paths, list) else [rule_paths]:
        for pat in _norm_pattern(raw):
            if any(fnmatchcase(c, pat) for c in cands):
                return str(raw)
    return None


def _skill_matches(skill: str, patterns) -> bool:
    if not isinstance(patterns, list):
        return False
    names = {skill, skill.split(":")[-1]}
    return any(isinstance(p, str) and fnmatchcase(n, p) for p in patterns for n in names)


def check(skill: str, cwd: str, cfg: dict) -> str | None:
    """Return a denial reason, or None if the skill is allowed in cwd."""
    rules = cfg.get("allowlist", {}).get("rules", [])
    if not isinstance(rules, list):
        return None
    allow_scopes = []
    allowed = False
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        where = _path_matches(rule.get("paths", []), cwd)
        if where is None:
            continue
        if _skill_matches(skill, rule.get("block")):
            return (f"skillwire allowlist: skill '{skill}' is blocked in {cwd} (rule paths '{where}'). "
                    "Proceed without it.")
        if "allow" in rule:
            allow_scopes.append(where)
            allowed = allowed or _skill_matches(skill, rule.get("allow"))
    if allow_scopes and not allowed:
        return (f"skillwire allowlist: skill '{skill}' is not on the allowlist for {cwd} "
                f"(rule paths {', '.join(repr(s) for s in allow_scopes)}). Proceed without it.")
    return None


def handle(ctx) -> None:
    skill = ctx.skill
    if not skill:
        return
    reason = check(skill, ctx.cwd, ctx.cfg)
    if reason:
        ctx.decision = Decision(module="allowlist", outcome="denied", reason=reason)
