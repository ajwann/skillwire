#!/usr/bin/env python3
"""Example skillwire JIT generator: fetch a JSON endpoint and list its datasets.

Prints a JSON object on stdout for SKILL.template.md:
  {"datasets": ["**id**: description", ...], "count": N, "source": URL}

Works with any endpoint that returns a list of objects, or an object holding
that list under datasets/results/data/items. A file:// URL is fine for testing.
Exits non-zero on any failure, and skillwire then keeps the last good SKILL.md.
"""
import argparse
import json
import re
import sys
import urllib.request

LIST_KEYS = ("datasets", "results", "data", "items")
NAME_KEYS = ("id", "name", "title", "slug")
DESC_KEYS = ("description", "summary", "cardData", "notes")


def first(obj, keys):
    for k in keys:
        v = obj.get(k)
        if isinstance(v, str) and v.strip():
            return v
    return ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--limit", type=int, default=15)
    ap.add_argument("--timeout", type=float, default=20)
    args = ap.parse_args()

    req = urllib.request.Request(args.url, headers={"User-Agent": "skillwire-jit-example/0.1"})
    with urllib.request.urlopen(req, timeout=args.timeout) as resp:
        payload = json.loads(resp.read().decode("utf-8"))

    items = payload
    if isinstance(payload, dict):
        items = next((payload[k] for k in LIST_KEYS if isinstance(payload.get(k), list)), None)
    if not isinstance(items, list):
        print("endpoint did not return a list of datasets", file=sys.stderr)
        return 1

    lines = []
    for item in items[: args.limit]:
        if not isinstance(item, dict):
            continue
        name = first(item, NAME_KEYS)
        if not name:
            continue
        desc = re.sub(r"\s+", " ", first(item, DESC_KEYS)).strip()
        desc = (desc[:140] + "…") if len(desc) > 140 else desc
        lines.append(f"**{name}**" + (f": {desc}" if desc else ""))
    if not lines:
        print("no datasets with a name/id field found", file=sys.stderr)
        return 1
    json.dump({"datasets": lines, "count": len(lines), "source": args.url}, sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
