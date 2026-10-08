"""Finding installed skills and reading/writing SKILL.md frontmatter (no YAML lib)."""
from __future__ import annotations

import glob
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from . import paths

SIDECAR = "skillwire.json"


@dataclass
class SkillInfo:
    name: str
    dir: Path
    scope: str  # project | user | extra
    description: str = ""
    sidecar: dict = field(default_factory=dict)

    @property
    def skill_md(self) -> Path:
        return self.dir / "SKILL.md"


def _unquote(val: str) -> str:
    val = val.strip()
    if len(val) >= 2 and val[0] == val[-1] == '"':
        try:
            return json.loads(val)
        except json.JSONDecodeError:
            return val[1:-1]
    if len(val) >= 2 and val[0] == val[-1] == "'":
        return val[1:-1].replace("''", "'")
    return val


def split_frontmatter(text: str) -> tuple[list[str], list[str]] | None:
    """Return (frontmatter_lines, body_lines) or None if there is no frontmatter."""
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return lines[1:i], lines[i + 1:]
    return None


def parse_frontmatter(text: str) -> dict[str, str]:
    """Parse the flat `key: value` subset of YAML that SKILL.md frontmatter uses.

    Handles quoted scalars, `>`/`|` block scalars and indented continuation lines.
    Nested mappings are kept as raw text.
    """
    split = split_frontmatter(text)
    if split is None:
        return {}
    fm, _ = split
    out: dict[str, str] = {}
    key, buf, block = None, [], None

    def flush():
        if key is None:
            return
        if block:
            joiner = "\n" if block.startswith("|") else " "
            out[key] = joiner.join(b.strip() for b in buf if b.strip())
        else:
            out[key] = _unquote(" ".join(b.strip() for b in buf))

    for line in fm:
        raw = line.rstrip("\n")
        if raw and not raw[0].isspace() and ":" in raw and not raw.lstrip().startswith("#"):
            flush()
            key, _, rest = raw.partition(":")
            key, rest = key.strip(), rest.strip()
            block = rest if rest[:1] in (">", "|") else None
            buf = [] if block else [rest]
        elif key is not None:
            buf.append(raw)
    flush()
    return out


def description_line_index(text: str) -> tuple[int, bool] | None:
    """(line index in the whole file, is_single_line) of the `description:` key."""
    split = split_frontmatter(text)
    if split is None:
        return None
    fm, _ = split
    for i, line in enumerate(fm):
        if line.startswith("description:"):
            rest = line.partition(":")[2].strip()
            nxt = fm[i + 1] if i + 1 < len(fm) else ""
            single = bool(rest) and rest[:1] not in (">", "|") and not (nxt[:1].isspace() and nxt.strip())
            return i + 1, single
    return None


def read_sidecar(skill_dir: Path) -> dict:
    p = skill_dir / SIDECAR
    if not p.exists():
        return {}
    data = json.loads(p.read_text(encoding="utf-8"))
    if isinstance(data, dict) and isinstance(data.get("skillwire"), dict):
        data = data["skillwire"]
    return data if isinstance(data, dict) else {}


def skill_roots(project: Path | None, cfg: dict | None) -> list[tuple[Path, str]]:
    roots = []
    if project is not None:
        roots.append((project / ".claude" / "skills", "project"))
    roots.append((paths.claude_home() / "skills", "user"))
    extra = list((cfg or {}).get("skill_dirs", []) or [])
    extra += list((cfg or {}).get("jit", {}).get("skill_dirs", []) or [])
    for pattern in extra:
        for match in sorted(glob.glob(os.path.expanduser(str(pattern)))):
            roots.append((Path(match), "extra"))
    return roots


def discover(project: Path | None, cfg: dict | None = None) -> list[SkillInfo]:
    """Skills in <project>/.claude/skills, ~/.claude/skills and configured skill_dirs.

    A skill_dirs entry may be a directory of skills or one skill directory.
    The first skill found for a name wins, so project skills shadow user skills.
    """
    found: dict[str, SkillInfo] = {}
    seen_dirs = set()
    for root, scope in skill_roots(project, cfg):
        if not root.is_dir():
            continue
        candidates = [root] if (root / "SKILL.md").exists() or (root / "SKILL.template.md").exists() \
            else sorted(p for p in root.iterdir() if p.is_dir())
        for d in candidates:
            real = d.resolve()
            md = d / "SKILL.md"
            if real in seen_dirs or not (md.exists() or (d / SIDECAR).exists()):
                continue
            seen_dirs.add(real)
            try:
                fm = parse_frontmatter(md.read_text(encoding="utf-8")) if md.exists() else {}
            except (OSError, UnicodeDecodeError):
                fm = {}
            try:
                sidecar = read_sidecar(d)
            except (OSError, ValueError):
                sidecar = {}
            name = fm.get("name") or d.name
            found.setdefault(name, SkillInfo(name, d, scope, fm.get("description", ""), sidecar))
    return list(found.values())
