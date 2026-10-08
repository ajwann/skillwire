"""skillwire command-line interface."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__, config, paths


def _project(args) -> Path:
    return Path(args.project).resolve() if getattr(args, "project", None) else paths.project_dir()


def _cfg(project: Path) -> dict:
    cfg, problems = config.load(project)
    for p in problems:
        print(f"warning: {p}", file=sys.stderr)
    return cfg


def cmd_report(args) -> int:
    from . import report
    project = _project(args)
    print(report.build(args.window, project, _cfg(project), unused_only=args.unused))
    return 0


def cmd_init(args) -> int:
    import json
    from . import init
    project = _project(args)
    rules = init.generate(project, _cfg(project))
    if not rules:
        print("No skills with a description found in .claude/skills, ~/.claude/skills or skill_dirs.")
        return 0
    if args.print:
        print(json.dumps({"router": {"rules": rules}}, indent=2))
        return 0
    target = paths.global_config_path() if args.glob else paths.project_config_path(project)
    added, backup = init.write(target, rules)
    print(f"Added {added} router rule(s) to {target} ({len(rules) - added} skill(s) already had rules).")
    if backup:
        print(f"Backup of the previous file: {backup}")
    print("Review the generated keywords: they are a starting point, not tuned rules.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="skillwire", description="Intercept and reshape how Claude uses skills.")
    ap.add_argument("--version", action="version", version=f"skillwire {__version__}")
    ap.add_argument("--project", help="project directory (default: $CLAUDE_PROJECT_DIR or cwd)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init", help="generate starter router rules from installed skills")
    p.add_argument("--print", action="store_true", help="print the rules instead of writing config")
    p.add_argument("--global", dest="glob", action="store_true", help="write ~/.claude/skillwire.json instead of the project")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("report", help="markdown usage report from telemetry")
    p.add_argument("window", nargs="?", default="7d", help="7d (default), 30d, 24h, 2w …")
    p.add_argument("--unused", action="store_true", help="only list skills that never loaded in the window")
    p.set_defaults(func=cmd_report)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except ValueError as exc:
        print(f"skillwire: {exc}", file=sys.stderr)
        return 2
