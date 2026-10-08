"""`skillwire init`: starter router rules from installed skills' descriptions."""
from __future__ import annotations

import json
import re
import shutil
import time
from collections import Counter
from pathlib import Path

from . import paths, skills

STOPWORDS = set("""
a about above after again against all also am an and any are as at be because been before being below between
both but by can could did do does doing down during each even every few for from further had has have having he
her here hers how i if in into is it its itself just like make makes many may me more most much must my need needs
no nor not now of off on once only or other our out over own same she should so some such than that the their them
then there these they this those through to too under until up use used uses using very via was we were what when
whenever where which while who whom why will with within without would you your yours user users claude skill skills
asks asked ask want wants trigger triggers include includes including example examples e.g etc any whether something
what check change code time date test tests build server version file files data work help project projects new
thing things write writes writing tool tools task tasks change changes run runs running even says said
""".split())


def keywords_for(name: str, description: str, limit: int = 6) -> list[str]:
    out: list[str] = []

    def add(k: str):
        k = k.strip().lower()
        if k and k not in out:
            out.append(k)

    base = name.split(":")[-1]
    parts = [p for p in re.split(r"[-_\s]+", base) if p]
    if len(parts) > 1:
        add(" ".join(parts))
    for p in parts:
        if len(p) >= 4 and p.lower() not in STOPWORDS:
            add(p)
    for phrase in re.findall(r"[\"“]([^\"”]{3,40})[\"”]", description):
        add(phrase)
    words = [w.lower() for w in re.findall(r"[A-Za-z][A-Za-z0-9+#.-]{3,}", description)]
    words = [w.strip(".-") for w in words if w.strip(".-") not in STOPWORDS]
    for w, _ in Counter(words).most_common():
        if len(out) >= limit + 2:
            break
        add(w)
    return out[: limit + 2]


def intent_examples_for(description: str, limit: int = 3) -> list[str]:
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", description) if len(s.strip()) > 10]
    return sentences[:limit]


def rule_for(skill: skills.SkillInfo) -> dict:
    return {
        "skill": skill.name,
        "keywords": keywords_for(skill.name, skill.description),
        "regex": [],
        "intent_examples": intent_examples_for(skill.description),
        "priority": "suggested",
    }


def generate(project: Path, cfg: dict) -> list[dict]:
    return [rule_for(s) for s in sorted(skills.discover(project, cfg), key=lambda s: s.name) if s.description]


def write(target: Path, rules: list[dict]) -> tuple[int, Path | None]:
    """Merge rules into target config, adding only skills that have no rule yet.

    Existing rules are never changed or removed. Returns (added, backup_path).
    """
    data: dict = {}
    backup = None
    if target.exists():
        data = json.loads(target.read_text(encoding="utf-8"))  # refuse to clobber a broken file
        if not isinstance(data, dict):
            raise ValueError(f"{target} is not a JSON object; fix it first")
        backup = paths.backups_dir() / f"{target.name}.{time.strftime('%Y%m%d-%H%M%S')}.bak"
        shutil.copy2(target, backup)
    router = data.setdefault("router", {})
    existing = router.setdefault("rules", [])
    have = {r.get("skill") for r in existing if isinstance(r, dict)}
    new = [r for r in rules if r["skill"] not in have]
    existing.extend(new)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    tmp.replace(target)
    return len(new), backup
