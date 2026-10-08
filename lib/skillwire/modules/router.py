"""Router (UserPromptSubmit): match the prompt against rules and suggest skills.

Rule shape: {skill, keywords[], regex[], intent_examples[], priority: required|suggested}

Keywords match case-insensitively on word boundaries, and regexes use
re.search with IGNORECASE. When router.llm_classify is true and
ANTHROPIC_API_KEY is set, a Haiku call adds matches. It has a hard timeout
(router.llm_timeout, default 2s), and on any failure only the regex/keyword
matches are used.
"""
from __future__ import annotations

import json
import os
import re
import urllib.request

from ..errors import log_error

API_URL = "https://api.anthropic.com/v1/messages"


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


def llm_classify(prompt: str, rules: list, model: str, timeout: float) -> list[str] | None:
    """Ask Haiku which rule skills apply. Returns None on any failure (caller falls back)."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key or not rules:
        return None
    catalog = []
    for r in rules:
        if isinstance(r, dict) and r.get("skill"):
            examples = "; ".join(str(e) for e in (r.get("intent_examples") or [])[:5])
            catalog.append(f"- {r['skill']}: {examples or ', '.join(r.get('keywords') or [])}")
    names = [r["skill"] for r in rules if isinstance(r, dict) and r.get("skill")]
    body = {
        "model": model,
        "max_tokens": 256,
        "thinking": {"type": "disabled"},
        "output_config": {
            "effort": "low",
            "format": {
                "type": "json_schema",
                "schema": {
                    "type": "object",
                    "properties": {"skills": {"type": "array", "items": {"type": "string", "enum": names}}},
                    "required": ["skills"],
                    "additionalProperties": False,
                },
            },
        },
        "messages": [{
            "role": "user",
            "content": (
                "Classify which of these skills are relevant to the user's request. "
                "Return only skills whose intent clearly matches; an empty list is fine.\n\n"
                "Skills:\n" + "\n".join(catalog) + "\n\nUser request:\n<request>\n" + prompt[:4000] + "\n</request>"
            ),
        }],
    }
    req = urllib.request.Request(
        API_URL, data=json.dumps(body).encode(), method="POST",
        headers={"content-type": "application/json", "x-api-key": key, "anthropic-version": "2023-06-01"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
        if data.get("stop_reason") == "refusal":
            return None
        text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
        picked = json.loads(text).get("skills", [])
        return [s for s in picked if s in names]
    except Exception as exc:  # timeout, HTTP error, bad JSON: fall back to regex
        log_error("router/llm", message=f"classifier unavailable, using regex only: {exc!r}")
        return None


def route(prompt: str, cfg: dict) -> tuple[list[str], list[str]]:
    rcfg = cfg.get("router", {})
    rules = [r for r in (rcfg.get("rules") or []) if isinstance(r, dict) and r.get("skill")]
    hits = {r["skill"]: r for r in match_rules(prompt, rules)}
    if rcfg.get("llm_classify") is True:
        picked = llm_classify(prompt, rules, rcfg.get("llm_model", "claude-haiku-5-5"),
                              float(rcfg.get("llm_timeout", 2.0)))
        for name in picked or []:
            hits.setdefault(name, next(r for r in rules if r["skill"] == name))
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
