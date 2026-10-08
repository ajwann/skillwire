"""One entry point per hook event. Runs the enabled modules in a fixed order.

Contract: a dispatcher never blocks Claude. Every failure, whether a module
import, a module crash, bad stdin, or bad config, is logged to errors.log, and
the process still exits 0. Denials are expressed only through documented JSON.
"""
from __future__ import annotations

import importlib
import json
import sys

from . import config, paths
from .errors import log_error
from .hookio import Context, build_output

# Order matters. On PreToolUse, telemetry is last so it records the verdict.
PIPELINES: dict[str, tuple[str, ...]] = {
    "SessionStart": ("jit", "chaos"),
    "UserPromptSubmit": ("router", "telemetry"),
    "PreToolUse": ("allowlist", "hijacker", "chaos", "telemetry"),
    "PostToolUse": ("chaining", "telemetry"),
}
TOOL_EVENTS = ("PreToolUse", "PostToolUse")
# Modules that observe even after a denial. Every other PreToolUse module stops
# at the first deny.
OBSERVERS = ("telemetry",)


def run_event(event: dict) -> dict | None:
    """Run the pipeline for an already-parsed event and return the hook JSON (or None)."""
    name = event.get("hook_event_name", "")
    pipeline = PIPELINES.get(name)
    if not pipeline:
        return None
    project = paths.project_dir(event)
    cfg, _problems = config.load(project)
    ctx = Context(event=event, cfg=cfg, project=project)
    if name in TOOL_EVENTS and not ctx.is_skill_call:
        return None
    for mod_name in pipeline:
        if not cfg.get(mod_name, {}).get("enabled", False):
            continue
        if ctx.decision is not None and mod_name not in OBSERVERS:
            continue
        try:
            module = importlib.import_module(f"skillwire.modules.{mod_name}")
            module.handle(ctx)
        except Exception as exc:
            log_error(f"{name}/{mod_name}", exc)
    return build_output(ctx)


def main(expected_event: str | None = None) -> int:
    try:
        raw = sys.stdin.read()
        event = json.loads(raw) if raw.strip() else {}
        if not isinstance(event, dict):
            raise ValueError("stdin JSON is not an object")
        if expected_event and not event.get("hook_event_name"):
            event["hook_event_name"] = expected_event
        out = run_event(event)
        if out:
            sys.stdout.write(json.dumps(out))
            sys.stdout.flush()
    except BaseException as exc:  # noqa: BLE001 - must never propagate
        log_error(f"dispatch/{expected_event}", exc)
    return 0
