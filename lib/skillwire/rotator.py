"""Description A/B rotator: `skillwire rotate` and `skillwire ab-report`.

A skill opts in with variants in its sidecar `skillwire.json`:

    {"variants": ["Use when …(A)", "Use when …(B)"]}

`rotate` switches SKILL.md to the next variant. It backs up the file first
and changes only the `description:` line. Every switch is logged to
ab_rotations, and telemetry stamps each skill event with the active variant.

`ab-report` compares the per-variant trigger rate: sessions in which the skill
loaded, divided by sessions with at least one prompt while that variant was
active.
"""
from __future__ import annotations

import math
import shutil
import time
from pathlib import Path

from . import db, paths, skills
from .report import md_table

LABELS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def variants_of(skill: skills.SkillInfo) -> list[str]:
    v = skill.sidecar.get("variants")
    if isinstance(v, list) and len(v) >= 2 and all(isinstance(x, str) and x.strip() for x in v):
        return v[: len(LABELS)]
    return []


def ab_skills(project: Path, cfg: dict) -> list[skills.SkillInfo]:
    return [s for s in skills.discover(project, cfg) if variants_of(s)]


def current_index(conn, skill: skills.SkillInfo, variants: list[str]) -> int:
    label = db.active_variant(conn, skill.name)
    if label and label in LABELS[: len(variants)]:
        return LABELS.index(label)
    if skill.description in variants:
        return variants.index(skill.description)
    return -1


def rotate_one(conn, skill: skills.SkillInfo, dry_run: bool = False) -> str:
    variants = variants_of(skill)
    text = skill.skill_md.read_text(encoding="utf-8")
    nxt = (current_index(conn, skill, variants) + 1) % len(variants)
    label = LABELS[nxt]
    new_text = skills.replace_description(text, variants[nxt])
    old_lines, new_lines = text.splitlines(), new_text.splitlines()
    changed = [i for i, (a, b) in enumerate(zip(old_lines, new_lines)) if a != b]
    if len(old_lines) != len(new_lines) or len(changed) > 1:
        raise ValueError(f"{skill.name}: refusing to write, edit would touch more than the description line")
    if dry_run:
        return f"{skill.name}: would switch to variant {label}"
    backup = paths.backups_dir() / f"{skill.name.replace(':', '_')}.{time.strftime('%Y%m%d-%H%M%S')}.{time.time_ns() % 10**6}.SKILL.md"
    shutil.copy2(skill.skill_md, backup)
    tmp = skill.skill_md.with_suffix(".md.skillwire-tmp")
    tmp.write_text(new_text, encoding="utf-8")
    tmp.replace(skill.skill_md)
    conn.execute("INSERT INTO ab_rotations (skill, variant, description, started_at) VALUES (?,?,?,?)",
                 (skill.name, label, variants[nxt], time.time()))
    conn.commit()
    return f"{skill.name}: switched to variant {label} (backup: {backup})"


def rotate(project: Path, cfg: dict, only: str | None = None, dry_run: bool = False) -> list[str]:
    targets = [s for s in ab_skills(project, cfg) if only is None or s.name == only]
    if only and not targets:
        raise ValueError(f"no skill named {only!r} with skillwire.json variants")
    conn = db.connect()
    try:
        out = []
        for s in targets:
            try:
                out.append(rotate_one(conn, s, dry_run))
            except (OSError, ValueError) as exc:
                out.append(f"{s.name}: skipped ({exc})")
        return out
    finally:
        conn.close()


# ------------------------------------------------------------------ report

def variant_stats(conn, skill: str, now: float | None = None) -> dict[str, dict]:
    rows = conn.execute("SELECT variant, started_at FROM ab_rotations WHERE skill=? ORDER BY started_at, id",
                        (skill,)).fetchall()
    now = now or time.time()
    stats: dict[str, dict] = {}
    for i, r in enumerate(rows):
        end = rows[i + 1]["started_at"] if i + 1 < len(rows) else now
        s = stats.setdefault(r["variant"], {"sessions": set(), "triggered": set(), "days": 0.0})
        s["days"] += (end - r["started_at"]) / 86400
        s["sessions"] |= {x[0] for x in conn.execute(
            "SELECT DISTINCT session_id FROM events WHERE outcome='prompt' AND ts>=? AND ts<?", (r["started_at"], end))}
    for label, s in stats.items():
        s["triggered"] = {x[0] for x in conn.execute(
            "SELECT DISTINCT session_id FROM events WHERE outcome='loaded' AND skill=? AND variant=?", (skill, label))}
        s["n"] = len(s["sessions"])
        s["k"] = len(s["triggered"] & s["sessions"])
        s["rate"] = s["k"] / s["n"] if s["n"] else None
    return stats


def two_proportion_p(k1: int, n1: int, k2: int, n2: int) -> float:
    if not n1 or not n2:
        return 1.0
    p = (k1 + k2) / (n1 + n2)
    se = math.sqrt(p * (1 - p) * (1 / n1 + 1 / n2))
    if se == 0:
        return 1.0
    z = abs(k1 / n1 - k2 / n2) / se
    return math.erfc(z / math.sqrt(2))


def verdict(stats: dict[str, dict], min_sessions: int) -> str:
    if len(stats) < 2:
        only = next(iter(stats), None)
        return ("Not enough data to call a winner: only variant " + only + " has been active so far. "
                "Run `skillwire rotate` to start the next variant.") if only else "No rotations recorded yet."
    small = [f"{lbl} has {s['n']} session(s)" for lbl, s in sorted(stats.items()) if s["n"] < min_sessions]
    if small:
        return (f"Not enough data to call a winner: {'; '.join(small)} (need at least {min_sessions} per variant, "
                "set ab.min_sessions to change).")
    ranked = sorted(stats.items(), key=lambda kv: -(kv[1]["rate"] or 0))
    (best, b), (second, s2) = ranked[0], ranked[1]
    p = two_proportion_p(b["k"], b["n"], s2["k"], s2["n"])
    if p < 0.05:
        return (f"Variant {best} leads: {b['rate']:.0%} vs {s2['rate']:.0%} for {second} "
                f"(two-proportion z-test p={p:.3f}).")
    return (f"No clear winner yet: {best} {b['rate']:.0%} vs {second} {s2['rate']:.0%}, p={p:.2f} "
            "(differences this size are within noise; keep collecting).")


def ab_report(project: Path, cfg: dict) -> str:
    min_sessions = int(cfg.get("ab", {}).get("min_sessions", 30))
    conn = db.connect()
    try:
        names = sorted({s.name for s in ab_skills(project, cfg)} |
                       {r[0] for r in conn.execute("SELECT DISTINCT skill FROM ab_rotations")})
        if not names:
            return "No skills with A/B variants found. Add \"variants\" to a skill's skillwire.json."
        out = ["# skillwire A/B report\n",
               "Trigger rate = sessions where the skill loaded ÷ sessions with a prompt while the variant was active.\n"]
        for name in names:
            stats = variant_stats(conn, name)
            out.append(f"## {name}\n")
            rows = [[lbl, s["n"], s["k"], f"{s['rate']:.1%}" if s["rate"] is not None else None, f"{s['days']:.1f}"]
                    for lbl, s in sorted(stats.items())]
            out.append(md_table(["variant", "sessions", "triggered", "trigger rate", "days active"], rows))
            out.append("**Verdict:** " + verdict(stats, min_sessions) + "\n")
        return "\n".join(out)
    finally:
        conn.close()
