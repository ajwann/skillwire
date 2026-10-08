"""`skillwire suggest-chains`: mine telemetry for skills that load together.

For every session, each ordered pair (A loaded before B) counts once. A pair
seen in at least --min sessions is proposed as chaining.chains[A] += [B]. When
both orders reach the threshold, only the more frequent direction is proposed.
Proposals are printed and config is never edited.
"""
from __future__ import annotations

import time
from collections import Counter, defaultdict

from . import db
from .report import parse_window


def pair_counts(conn, since: float) -> Counter:
    seqs: dict[str, list[str]] = defaultdict(list)
    for r in conn.execute("SELECT session_id, skill FROM events WHERE outcome='loaded' AND ts>=? "
                          "ORDER BY session_id, ts, id", (since,)):
        seq = seqs[r["session_id"]]
        if r["skill"] not in seq:
            seq.append(r["skill"])
    counts: Counter = Counter()
    for seq in seqs.values():
        for i, a in enumerate(seq):
            for b in seq[i + 1:]:
                counts[(a, b)] += 1
    return counts


def suggest(cfg: dict, min_count: int = 3, window: str = "30d") -> tuple[dict[str, list[str]], list[tuple]]:
    seconds, _ = parse_window(window)
    conn = db.connect()
    try:
        counts = pair_counts(conn, time.time() - seconds)
    finally:
        conn.close()
    existing = cfg.get("chaining", {}).get("chains", {}) or {}
    proposals: dict[str, list[str]] = defaultdict(list)
    evidence = []
    for (a, b), n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
        if n < min_count:
            continue
        if counts.get((b, a), 0) > n or (counts.get((b, a), 0) == n and b < a):
            continue  # the other direction wins
        if b in (existing.get(a) or []):
            continue
        proposals[a].append(b)
        evidence.append((a, b, n, counts.get((b, a), 0)))
    return dict(proposals), evidence
