#!/usr/bin/env python3
"""E007 — exact policy evaluation through E006's stage-2 machinery.

A policy here is nothing but a held-hour mask on E006's hour grid. Its maximal
runs become streaks; each streak is simulated exactly through
`e006/exact.py::simulate_streak` (E003's `run_arm`, lag1h_rh1h inside, fresh
mint at entry, burn+flatten at exit); cash outside. Priced at all three
envelope points after the fact; the verdict reads CENTRAL.

The disk cache (out/cache_w<W>.json, git-ignored, rederivable) memoises
per-streak Bucket totals keyed by (start, end): thresholds within and across
candidates share most of their streaks, which is what makes the pre-registered
grids affordable. The cache stores the engine's per-streak accounting gap and
`evaluate_mask` asserts it <= 1e-6 (contract 3) on every use, cached or not.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

E007 = Path(__file__).resolve().parent
BMS = E007.parent
for p in (BMS / "gate1", BMS / "e003", BMS / "e006"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
import envelope as ENV   # noqa: E402
import oracle            # noqa: E402
import exact             # noqa: E402

BUCKET_FIELDS = exact.BUCKET_FIELDS
GAP_BAR = 1e-6


class StreakCache:
    def __init__(self, w: int):
        self.w = w
        self.path = E007 / "out" / f"cache_w{w}.json"
        self.data: dict[str, dict] = {}
        self.dirty = 0
        if self.path.exists():
            self.data = json.loads(self.path.read_text())

    def save(self) -> None:
        if self.dirty:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.data))
            self.dirty = 0

    def get(self, t_from: int, t_to: int, swaps: pd.DataFrame, funding: dict) -> dict | None:
        key = f"{t_from}:{t_to}"
        hit = self.data.get(key)
        if hit is None:
            r = exact.simulate_streak(self.w, swaps, funding, t_from, t_to)
            if r is None:
                hit = {"empty": True}
            else:
                hit = {
                    "total": {f: getattr(r.total, f) for f in BUCKET_FIELDS},
                    "months": {lab: {f: getattr(b, f) for f in BUCKET_FIELDS}
                               for lab, b in r.months.items()},
                    "gap": r.checks["lp_value_abs_gap_usd"],
                }
            self.data[key] = hit
            self.dirty += 1
            if self.dirty >= 200:
                self.save()
        if hit.get("empty"):
            return None
        assert hit["gap"] <= GAP_BAR, f"accounting gap {hit['gap']} > {GAP_BAR}"
        return hit


def evaluate_mask(mask: np.ndarray, hs: np.ndarray, swaps: pd.DataFrame,
                  funding: dict, cache: StreakCache) -> dict:
    """Exact result of the policy `mask` over the hours it is defined on."""
    total: dict = {}
    months: dict[str, dict] = {}
    runs = oracle.streaks_of(np.asarray(mask, dtype=bool))
    n_sim = 0
    for (i, j) in runs:
        hit = cache.get(int(hs[i]), int(hs[j]) + 3600, swaps, funding)
        if hit is None:
            continue
        n_sim += 1
        for f, v in hit["total"].items():
            total[f] = total.get(f, 0.0) + v
        for lab, b in hit["months"].items():
            dst = months.setdefault(lab, {})
            for f, v in b.items():
                dst[f] = dst.get(f, 0.0) + v
    return {"total": total, "months": months,
            "n_streaks": len(runs), "n_simulated": n_sim,
            "held_hours": total.get("hours", 0.0)}


def net_usd(bucket: dict, point_name: str) -> float:
    if not bucket:
        return 0.0
    return exact.net_usd(bucket, ENV.ENVELOPE_BY_NAME[point_name])
