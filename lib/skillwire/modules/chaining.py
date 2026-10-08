"""Chaining (PostToolUse on Skill): after skill X loads, point Claude at its follow-ups.

Config: chaining.chains = {after_skill: [then_skills]}. When skip_if_loaded is
on (the default), follow-ups that already loaded in this session are left out,
which also stops a chain from ping-ponging between two skills.
"""
from __future__ import annotations

from .. import db
from ..errors import log_error


def follow_ups(skill: str, cfg: dict) -> list[str]:
    chains = cfg.get("chaining", {}).get("chains", {})
    if not isinstance(chains, dict):
        return []
    then = chains.get(skill, [])
    if not isinstance(then, list):
        return []
    out = []
    for s in then:
        if isinstance(s, str) and s and s != skill and s not in out:
            out.append(s)
    return out


def handle(ctx) -> None:
    skill = ctx.skill
    if not skill:
        return
    resp = ctx.event.get("tool_response")
    if isinstance(resp, dict) and resp.get("success") is False:
        return
    then = follow_ups(skill, ctx.cfg)
    if not then:
        return
    if ctx.mod("chaining").get("skip_if_loaded", True) and ctx.session_id:
        try:
            conn = db.connect()
            try:
                loaded = db.loaded_in_session(conn, ctx.session_id)
            finally:
                conn.close()
            then = [s for s in then if s not in loaded]
        except Exception as exc:
            log_error("chaining", exc)
    if ctx.mod("allowlist").get("enabled"):
        from . import allowlist
        then = [s for s in then if allowlist.check(s, ctx.cwd, ctx.cfg) is None]
    if not then:
        return
    ctx.contexts.append(
        f"skillwire chaining: in this setup '{skill}' is followed by: {', '.join(then)}. "
        "Load those with the Skill tool as well unless they are clearly irrelevant to the task."
    )
