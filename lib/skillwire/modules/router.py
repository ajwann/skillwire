"""Router (UserPromptSubmit): match the prompt against rules and suggest skills.

Rule shape: {skill, keywords[], regex[], intent_examples[], priority: required|suggested}

Keywords match case-insensitively on word boundaries, and regexes use
re.search with IGNORECASE. Routing is local: nothing leaves the machine.
intent_examples aren't matched; `skillwire init` fills them in as notes for
the people who tune the rules.
"""
from __future__ import annotations

import re

from ..errors import log_error



def _keyword_hit(keyword: str, text: str) -> bool:
    kw = keyword.strip()
    if not kw:
        return False
    # \b only works next to word chars; fall back to substring for things like "c++".
    left = r"\b" if re.match(r"\w", kw) else ""
    right = r"\b" if re.search(r"\w$", kw) else ""
    return re.search(left + re.escape(kw) + right, text, re.IGNORECASE) is not None


def match_rules(prompt: str, rules: list) -> list[dict]:
    hits = []
    for rule in rules:
        if not isinstance(rule, dict) or not rule.get("skill"):
            continue
        hit = any(_keyword_hit(k, prompt) for k in rule.get("keywords", []) or [] if isinstance(k, str))
        if not hit:
            for rx in rule.get("regex", []) or []:
                try:
                    if re.search(rx, prompt, re.IGNORECASE):
                        hit = True
                        break
                except re.error as exc:
                    log_error("router", message=f"bad regex {rx!r} for {rule['skill']}: {exc}")
        if hit:
            hits.append(rule)
    return hits


def route(prompt: str, cfg: dict) -> tuple[list[str], list[str]]:
    rules = cfg.get("router", {}).get("rules") or []
    hits = {r["skill"]: r for r in match_rules(prompt, rules)}
    required = [s for s, r in hits.items() if r.get("priority") == "required"]
    suggested = [s for s, r in hits.items() if r.get("priority") != "required"]
    return required, suggested


def handle(ctx) -> None:
    prompt = ctx.event.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        return
    required, suggested = route(prompt, ctx.cfg)

    # Don't point Claude at skills the allowlist would deny here anyway.
    if ctx.mod("allowlist").get("enabled"):
        from . import allowlist
        required = [s for s in required if allowlist.check(s, ctx.cwd, ctx.cfg) is None]
        suggested = [s for s in suggested if allowlist.check(s, ctx.cwd, ctx.cfg) is None]
    if not required and not suggested:
        return
    ctx.notes["routed"] = [(s, "required") for s in required] + [(s, "suggested") for s in suggested]
    lines = ["skillwire router matched this prompt to skills."]
    if required:
        lines.append("Required skills (project policy: load these with the Skill tool before responding): "
                     + ", ".join(required) + ".")
    if suggested:
        lines.append("Suggested skills (optional, likely relevant): " + ", ".join(suggested) + ".")
    ctx.contexts.append("\n".join(lines))
