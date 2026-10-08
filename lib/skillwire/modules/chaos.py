"""Chaos mode (PreToolUse on Skill; SessionStart banner).

Denies a fraction (chaos.rate, default 0.2) of skill loads so you can see how
Claude copes without them. Active only when BOTH chaos.enabled is true AND the
environment has SKILLWIRE_CHAOS=1.

Determinism: with chaos.seed (or SKILLWIRE_CHAOS_SEED) set, each decision is a
pure function of (seed, tool_use_id), so a replayed session denies the same
calls even though every hook runs in a fresh process.
"""
from __future__ import annotations

import os
import random
from fnmatch import fnmatchcase

from ..hookio import Decision

REASON = "skillwire chaos: proceed without this skill."


def active(cfg: dict) -> bool:
    return cfg.get("chaos", {}).get("enabled") is True and os.environ.get("SKILLWIRE_CHAOS") == "1"


def rate(cfg: dict) -> float:
    r = cfg.get("chaos", {}).get("rate", 0.2)
    try:
        return min(1.0, max(0.0, float(r)))
    except (TypeError, ValueError):
        return 0.2


def seed(cfg: dict):
    env = os.environ.get("SKILLWIRE_CHAOS_SEED")
    return env if env not in (None, "") else cfg.get("chaos", {}).get("seed")


def should_deny(cfg: dict, tool_use_id: str, skill: str) -> bool:
    exempt = cfg.get("chaos", {}).get("exempt", []) or []
    if any(isinstance(p, str) and fnmatchcase(skill, p) for p in exempt):
        return False
    s = seed(cfg)
    rng = random.Random(f"{s}:{tool_use_id}") if s is not None else random.SystemRandom()
    return rng.random() < rate(cfg)


def handle(ctx) -> None:
    if not active(ctx.cfg):
        return
    if ctx.name == "SessionStart":
        banner = (f"⚠ skillwire chaos mode is ACTIVE: about {rate(ctx.cfg):.0%} of skill loads will be denied. "
                  "Unset SKILLWIRE_CHAOS or set chaos.enabled=false to stop.")
        ctx.system_messages.append(banner)
        ctx.contexts.append("skillwire chaos mode is active in this session: some Skill tool calls will be "
                            "denied on purpose to test resilience. When that happens, continue the task without the skill.")
        return
    skill = ctx.skill
    if skill and should_deny(ctx.cfg, ctx.event.get("tool_use_id", ""), skill):
        ctx.decision = Decision(module="chaos", outcome="denied", reason=REASON)
