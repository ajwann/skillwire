"""Error logging. Nothing in here may raise."""
from __future__ import annotations

import datetime as _dt
import traceback

from . import paths

MAX_LOG_BYTES = 1_000_000


def log_error(where: str, exc: BaseException | None = None, message: str = "") -> None:
    try:
        log = paths.errors_log()
        if log.exists() and log.stat().st_size > MAX_LOG_BYTES:
            log.replace(log.with_suffix(".log.1"))
        stamp = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
        lines = [f"[{stamp}] {where}: {message}".rstrip()]
        if exc is not None:
            lines.append("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)).rstrip())
        with log.open("a", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
    except BaseException:  # logging must never take Claude down
        pass
