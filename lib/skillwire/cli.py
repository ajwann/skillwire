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


def cmd_suggest_chains(args) -> int:
    import json
    from . import report, suggest
    project = _project(args)
    proposals, evidence = suggest.suggest(_cfg(project), args.min, args.window)
    if not proposals:
        print(f"No skill pairs co-occurred in at least {args.min} sessions ({args.window}). Nothing to propose.")
        return 0
    print(f"# Proposed chains (pairs seen in >= {args.min} sessions, {args.window})\n")
    print(report.md_table(["after", "then", "sessions A→B", "sessions B→A"], [list(e) for e in evidence]))
    print("Add to `chaining.chains` in skillwire.json if these look right (not applied automatically):\n")
    print("```json")
    print(json.dumps({"chaining": {"chains": proposals}}, indent=2))
    print("```")
    return 0


def cmd_rotate(args) -> int:
    from . import rotator
    project = _project(args)
    cfg = _cfg(project)
    if not cfg["ab"].get("enabled") and not args.dry_run:
        print("A/B rotation is off. Set \"ab\": {\"enabled\": true} in skillwire.json (or use --dry-run).")
        return 1
    lines = rotator.rotate(project, cfg, args.skill, args.dry_run)
    print("\n".join(lines) if lines else "No skills with A/B variants found.")
    return 0


def cmd_ab_report(args) -> int:
    from . import rotator
    project = _project(args)
    print(rotator.ab_report(project, _cfg(project)))
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

    p = sub.add_parser("suggest-chains", help="propose chain entries from co-occurring skills (prints only)")
    p.add_argument("--min", type=int, default=3, help="minimum sessions a pair must co-occur in (default 3)")
    p.add_argument("--window", default="30d", help="lookback window (default 30d)")
    p.set_defaults(func=cmd_suggest_chains)

    p = sub.add_parser("rotate", help="switch A/B skills to their next description variant")
    p.add_argument("--skill", help="only rotate this skill")
    p.add_argument("--dry-run", action="store_true", help="show what would change")
    p.set_defaults(func=cmd_rotate)

    p = sub.add_parser("ab-report", help="compare trigger rate per description variant")
    p.set_defaults(func=cmd_ab_report)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except ValueError as exc:
        print(f"skillwire: {exc}", file=sys.stderr)
        return 2
