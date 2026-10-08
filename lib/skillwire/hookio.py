"""Hook input/output shapes. See docs/HOOK_SCHEMA.md."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import SKILL_TOOL

EVENTS = ("SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse")
MAX_FIELD = 10_000  # documented cap for additionalContext / systemMessage


@dataclass
class Decision:
    """A PreToolUse verdict made by one module."""
    module: str
    outcome: str  # "denied" | "redirected"
    reason: str
    redirect_to: str | None = None


@dataclass
class Context:
    event: dict
    cfg: dict
    project: Path
    contexts: list[str] = field(default_factory=list)
    system_messages: list[str] = field(default_factory=list)
    decision: Decision | None = None
    notes: dict[str, Any] = field(default_factory=dict)

    @property
    def name(self) -> str:
        return self.event.get("hook_event_name", "")

    @property
    def session_id(self) -> str:
        return self.event.get("session_id", "") or ""

    @property
    def cwd(self) -> str:
        return self.event.get("cwd") or str(self.project)

    @property
    def is_skill_call(self) -> bool:
        return self.event.get("tool_name") == SKILL_TOOL

    @property
    def skill(self) -> str | None:
        ti = self.event.get("tool_input")
        if isinstance(ti, dict) and isinstance(ti.get("skill"), str):
            return ti["skill"].lstrip("/")
        return None

    @property
    def skill_args(self) -> str:
        ti = self.event.get("tool_input") or {}
        args = ti.get("args") if isinstance(ti, dict) else None
        return args if isinstance(args, str) else ""

    def mod(self, name: str) -> dict:
        return self.cfg.get(name, {})


def _clip(text: str) -> str:
    return text if len(text) <= MAX_FIELD else text[: MAX_FIELD - 20] + "\n…[truncated]"


def build_output(ctx: Context) -> dict | None:
    """Turn what the modules collected into the documented JSON shape."""
    out: dict[str, Any] = {}
    hso: dict[str, Any] = {}
    if ctx.name == "PreToolUse" and ctx.decision is not None:
        hso["permissionDecision"] = "deny"
        hso["permissionDecisionReason"] = _clip(ctx.decision.reason)
    if ctx.contexts:
        hso["additionalContext"] = _clip("\n\n".join(ctx.contexts))
    if hso:
        hso["hookEventName"] = ctx.name
        out["hookSpecificOutput"] = hso
    if ctx.system_messages:
        out["systemMessage"] = _clip("\n".join(ctx.system_messages))
    return out or None
