"""Telemetry: record prompts, routing, and skill-tool outcomes in SQLite.

Runs last in every pipeline so it records what the other modules decided.
"""
from __future__ import annotations

import hashlib

from .. import db


def prompt_hash(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8", "replace")).hexdigest()[:16]


def handle(ctx) -> None:
    conn = db.connect()
    try:
        base = {"session_id": ctx.session_id, "event": ctx.name, "cwd": ctx.cwd}
        if ctx.name == "UserPromptSubmit":
            prompt = ctx.event.get("prompt") or ""
            phash = prompt_hash(prompt)
            store = ctx.mod("telemetry").get("store_prompts") is True
            db.insert_event(conn, **base, outcome="prompt", prompt_hash=phash, prompt=prompt if store else None)
            for skill, priority in ctx.notes.get("routed", []):
                db.insert_event(conn, **base, skill=skill, outcome="routed", module="router",
                                detail=priority, prompt_hash=phash)
            return

        skill = ctx.skill
        if not skill:
            return
        base.update(skill=skill, prompt_hash=db.last_prompt_hash(conn, ctx.session_id),
                    variant=db.active_variant(conn, skill))
        if ctx.name == "PreToolUse":
            d = ctx.decision
            if d is not None:
                db.insert_event(conn, **base, outcome=d.outcome, module=d.module,
                                redirect_to=d.redirect_to, detail=d.reason[:500])
        elif ctx.name == "PostToolUse":
            resp = ctx.event.get("tool_response")
            ok = not (isinstance(resp, dict) and resp.get("success") is False)
            dur = ctx.event.get("duration_ms")
            db.insert_event(conn, **base, outcome="loaded" if ok else "failed",
                            duration_ms=int(dur) if isinstance(dur, (int, float)) else None)
    finally:
        conn.close()
