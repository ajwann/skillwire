"""`skillwire report`: markdown tables over the telemetry database."""
from __future__ import annotations

import re
import time
from pathlib import Path

from . import db, skills


def md_table(headers: list[str], rows: list[list]) -> str:
    if not rows:
        return "_none_\n"
    def cell(v):
        return "–" if v is None else str(v).replace("|", "\\|")
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    lines += ["| " + " | ".join(cell(v) for v in r) + " |" for r in rows]
    return "\n".join(lines) + "\n"


def parse_window(text: str) -> tuple[float, str]:
    m = re.fullmatch(r"(\d+)([hdw])", text.strip().lower())
    if not m:
        raise ValueError(f"window must look like 7d, 30d, 24h or 2w (got {text!r})")
    n, unit = int(m.group(1)), m.group(2)
    seconds = n * {"h": 3600, "d": 86400, "w": 7 * 86400}[unit]
    return seconds, f"last {n}{unit}"


def unused_skills(conn, since: float, project: Path | None, cfg: dict) -> list[skills.SkillInfo]:
    loaded = {r["skill"] for r in conn.execute(
        "SELECT DISTINCT skill FROM events WHERE outcome='loaded' AND ts>=?", (since,))}
    return [s for s in skills.discover(project, cfg) if s.name not in loaded]


def build(window: str, project: Path | None, cfg: dict, unused_only: bool = False, now: float | None = None) -> str:
    seconds, label = parse_window(window)
    since = (now or time.time()) - seconds
    conn = db.connect()
    try:
        out = []
        unused = unused_skills(conn, since, project, cfg)
        unused_rows = [[s.name, s.scope, (s.description[:80] + "…") if len(s.description) > 80 else s.description]
                       for s in sorted(unused, key=lambda s: s.name)]
        if unused_only:
            out.append(f"# skillwire: never-triggered skills ({label})\n")
            out.append(md_table(["skill", "scope", "description"], unused_rows))
            return "\n".join(out)

        q = lambda sql, *a: conn.execute(sql, (since, *a)).fetchall()  # noqa: E731
        totals = q("SELECT COUNT(*) AS prompts, COUNT(DISTINCT session_id) AS sessions "
                   "FROM events WHERE outcome='prompt' AND ts>=?")[0]
        out.append(f"# skillwire report ({label})\n")
        out.append(f"{totals['prompts']} prompts across {totals['sessions']} sessions.\n")

        out.append("## Top skills\n")
        rows = q("""
            SELECT skill,
                   SUM(outcome='loaded')     AS loads,
                   COUNT(DISTINCT CASE WHEN outcome='loaded' THEN session_id END) AS sessions,
                   ROUND(AVG(CASE WHEN outcome='loaded' THEN duration_ms END), 1) AS avg_ms,
                   SUM(outcome='routed')     AS routed,
                   SUM(outcome='denied')     AS denied,
                   SUM(outcome='redirected') AS redirected,
                   SUM(outcome='failed')     AS failed
            FROM events WHERE skill IS NOT NULL AND ts>=?
            GROUP BY skill ORDER BY loads DESC, routed DESC, skill""")
        out.append(md_table(["skill", "loads", "sessions", "avg load ms", "routed", "denied", "redirected away", "failed"],
                            [list(r) for r in rows]))
        out.append("_avg load ms is the Skill tool's `duration_ms`: the time to load the skill, "
                   "not the time Claude spends on the work afterwards._\n")

        out.append("## Redirects\n")
        rows = q("""SELECT skill, redirect_to, COUNT(*) AS n FROM events
                    WHERE outcome='redirected' AND ts>=? GROUP BY skill, redirect_to ORDER BY n DESC""")
        out.append(md_table(["from", "to", "count"], [list(r) for r in rows]))

        out.append("## Denials\n")
        rows = q("""SELECT skill, module, COUNT(*) AS n FROM events
                    WHERE outcome='denied' AND ts>=? GROUP BY skill, module ORDER BY n DESC""")
        out.append(md_table(["skill", "module", "count"], [list(r) for r in rows]))

        out.append("## Never-triggered skills\n")
        out.append(md_table(["skill", "scope", "description"], unused_rows))
        return "\n".join(out)
    finally:
        conn.close()
