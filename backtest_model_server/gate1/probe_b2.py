#!/usr/bin/env python3
"""Abort-criterion probe: is trial-window pool data (2026-05-12..15) in B2?

Lists every key under the pool prefix, groups by top-level data type, and prints
what exists for the T4/T5 window. Downloads nothing.
"""

import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from engine.b2 import B2  # noqa: E402

TRIAL_DAYS = ["2026-05-11", "2026-05-12", "2026-05-13", "2026-05-14", "2026-05-15", "2026-05-16"]


def main() -> int:
    b2 = B2()
    print(f"bucket={b2.bucket_name} pool_prefix={b2.pool_prefix}")

    files = b2.list_files(f"{b2.pool_prefix}/")
    print(f"total keys under {b2.pool_prefix}/: {len(files)}")

    # Group by the path shape after the pool prefix, collapsing date components.
    shapes = defaultdict(lambda: {"n": 0, "bytes": 0, "sample": None})
    for f in files:
        parts = f["name"].split("/")
        shape = "/".join(parts[1:3]) if len(parts) > 2 else "/".join(parts[1:])
        s = shapes[shape]
        s["n"] += 1
        s["bytes"] += f["size"]
        if s["sample"] is None:
            s["sample"] = f["name"]
    print("\n--- key shapes ---")
    for shape, s in sorted(shapes.items()):
        print(f"  {shape:28s} n={s['n']:6d} {s['bytes']/1e6:9.1f} MB  e.g. {s['sample']}")

    print("\n--- trial-window coverage ---")
    for day in TRIAL_DAYS:
        hits = [f for f in files if day in f["name"]]
        by_kind = defaultdict(lambda: [0, 0])
        for f in hits:
            parts = f["name"].split("/")
            kind = "/".join(parts[1:3]) if len(parts) > 2 else "/".join(parts[1:])
            by_kind[kind][0] += 1
            by_kind[kind][1] += f["size"]
        desc = ", ".join(f"{k}:{v[0]}f/{v[1]/1e6:.1f}MB" for k, v in sorted(by_kind.items()))
        print(f"  {day}: {len(hits):5d} keys   {desc if desc else 'NONE'}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
