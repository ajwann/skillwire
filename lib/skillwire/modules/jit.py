"""JIT skills (SessionStart): regenerate SKILL.md from a template and a generator.

A skill opts in with a sidecar `skillwire.json` next to its SKILL.md:

    {"template": "SKILL.template.md", "generator": "{python} generate.py --url <catalog-url>"}

On session start the generator runs in the skill directory (jit.timeout,
default 30s). Its stdout should be a JSON object, and non-JSON output is
exposed as {{ output }}. The template's {{ key }} / {{ key.sub }} placeholders
are filled in: lists render as markdown bullets, dicts as JSON. Any failure
leaves SKILL.md exactly as it was, so the last good render stays in place:
generator exit != 0, a timeout, an unknown placeholder, or output without
frontmatter. The skipped render is logged and noted in a systemMessage.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .. import db, paths, skills
from ..errors import log_error

PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z_][\w.]*)\s*\}\}")


class RenderError(Exception):
    pass


def _lookup(data, dotted: str):
    cur = data
    for part in dotted.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
            cur = cur[int(part)]
        else:
            raise RenderError(f"template placeholder '{{{{ {dotted} }}}}' has no value in generator output")
    return cur


def _format(value) -> str:
    if isinstance(value, list):
        return "\n".join(f"- {v if isinstance(v, str) else json.dumps(v)}" for v in value) or "_(none)_"
    if isinstance(value, dict):
        return json.dumps(value, indent=2)
    return "" if value is None else str(value)


def render(template: str, data: dict) -> str:
    out = PLACEHOLDER.sub(lambda m: _format(_lookup(data, m.group(1))), template)
    if skills.split_frontmatter(out) is None:
        raise RenderError("rendered SKILL.md has no frontmatter (--- … ---)")
    return out


def _command(generator) -> list[str]:
    argv = shlex.split(generator) if isinstance(generator, str) else [str(a) for a in generator]
    if not argv:
        raise RenderError("empty generator command")
    return [sys.executable if a == "{python}" else a for a in argv]


def run_generator(skill_dir: Path, generator, timeout: float) -> dict:
    env = paths.child_env(SKILLWIRE_SKILL_DIR=str(skill_dir))
    try:
        proc = subprocess.run(_command(generator), cwd=str(skill_dir), capture_output=True, text=True,
                              timeout=timeout, env=env, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        raise RenderError(f"generator timed out after {timeout:g}s")
    except OSError as exc:
        raise RenderError(f"generator could not start: {exc}")
    if proc.returncode != 0:
        raise RenderError(f"generator exited {proc.returncode}: {proc.stderr.strip()[-500:]}")
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        data = {"output": proc.stdout.strip()}
    if not isinstance(data, dict):
        data = {"output": data}
    data.setdefault("generated_at", time.strftime("%Y-%m-%dT%H:%M:%S%z"))
    return data


def apply_active_variant(text: str, skill_name: str) -> str:
    """Keep an A/B-rotated description in force across re-renders."""
    try:
        conn = db.connect()
        try:
            row = conn.execute("SELECT description FROM ab_rotations WHERE skill=? "
                               "ORDER BY started_at DESC, id DESC LIMIT 1", (skill_name,)).fetchone()
        finally:
            conn.close()
        return skills.replace_description(text, row["description"]) if row else text
    except Exception as exc:
        log_error("jit/ab", exc)
        return text


def refresh(skill: skills.SkillInfo, timeout: float, dry_run: bool = False) -> tuple[bool, str]:
    """Render one skill. Returns (ok, message). Never raises."""
    side = skill.sidecar
    try:
        tpl_path = skill.dir / side.get("template", "SKILL.template.md")
        if not tpl_path.is_file():
            raise RenderError(f"template {tpl_path.name} not found")
        if not side.get("generator"):
            raise RenderError("no generator in skillwire.json")
        data = run_generator(skill.dir, side["generator"], float(side.get("timeout", timeout)))
        text = render(tpl_path.read_text(encoding="utf-8"), data)
        text = apply_active_variant(text, skill.name)
        if not dry_run:
            tmp = skill.skill_md.with_suffix(".md.skillwire-tmp")
            tmp.write_text(text, encoding="utf-8")
            tmp.replace(skill.skill_md)
        return True, f"rendered {skill.name}"
    except Exception as exc:
        log_error(f"jit/{skill.name}", None if isinstance(exc, RenderError) else exc, str(exc))
        kept = "kept the last good SKILL.md" if skill.skill_md.exists() else "no SKILL.md exists yet"
        return False, f"{skill.name}: {exc} ({kept})"


def jit_skills(project: Path, cfg: dict) -> list[skills.SkillInfo]:
    return [s for s in skills.discover(project, cfg) if s.sidecar.get("generator")]


def handle(ctx) -> None:
    if ctx.event.get("source") == "compact":
        return  # mid-session; the skill text Claude has already seen should stay stable
    targets = jit_skills(ctx.project, ctx.cfg)
    if not targets:
        return
    timeout = float(ctx.mod("jit").get("timeout", 30))
    dry = os.environ.get("SKILLWIRE_DRY_RUN") == "1"
    with ThreadPoolExecutor(max_workers=min(8, len(targets))) as pool:
        results = list(pool.map(lambda s: refresh(s, timeout, dry), targets))
    failures = [msg for ok, msg in results if not ok]
    if failures:
        ctx.system_messages.append("skillwire JIT: " + "; ".join(failures))
