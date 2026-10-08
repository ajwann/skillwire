"""Hijacker (PreToolUse on Skill): redirect one skill to another.

Config: hijacker.map = {from_skill: to_skill}. Chains are followed to their
end (a -> b -> c redirects a straight to c). Loop guards:
  * a skill mapped to itself is ignored
  * any chain that revisits a skill (a cycle) is ignored entirely
  * a redirect to a skill the allowlist blocks here is ignored
In every ignored case the original call goes through and the reason is logged.
"""
from __future__ import annotations

from ..errors import log_error
from ..hookio import Decision


def resolve(skill: str, mapping: dict) -> str | None:
    """Final redirect target for skill, or None if there's no safe redirect."""
    if not isinstance(mapping, dict) or skill not in mapping:
        return None
    seen = [skill]
    node = skill
    while node in mapping:
        nxt = mapping[node]
        if not isinstance(nxt, str) or not nxt:
            log_error("hijacker", message=f"ignoring non-string target for {node!r}")
            return None
        if nxt in seen:
            if nxt != node or len(seen) > 1:
                log_error("hijacker", message="cycle ignored: " + " -> ".join(seen + [nxt]))
            return None
        seen.append(nxt)
        node = nxt
    return node if node != skill else None


def handle(ctx) -> None:
    skill = ctx.skill
    if not skill:
        return
    target = resolve(skill, ctx.mod("hijacker").get("map", {}))
    if target is None:
        return
    if ctx.mod("allowlist").get("enabled"):
        from . import allowlist
        if allowlist.check(target, ctx.cwd, ctx.cfg) is not None:
            log_error("hijacker", message=f"not redirecting {skill!r} to {target!r}: target is blocked in {ctx.cwd}")
            return
    args = ctx.skill_args
    hint = f" with the same args ({args!r})" if args else ""
    ctx.decision = Decision(
        module="hijacker",
        outcome="redirected",
        redirect_to=target,
        reason=(f"skillwire hijacker: '{skill}' is replaced by '{target}' in this setup. "
                f"Load '{target}' with the Skill tool instead{hint}, then continue the task."),
    )
