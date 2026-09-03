#!/usr/bin/env python3
"""E011 funding-persistence look — E009's estimators on LINK-PERP, plus the
pre-registered two-leg bounds F1/F2.

    nix develop .#gate1 -c python backtest_model_server/e011/funding11.py

The hedge is two shorts (M005 §2): LINK-PERP against the LP's LINK leg,
ETH-PERP against its WETH leg; positive funding credits both. This module
answers: is the window's funding tailwind (+$1.7–1.8/day at always-in $10k
leg notionals) representative?

Pre-named estimators only (E009's, reused by import where they exist):
  - trailing-12m mean (central), full-history mean, halves trajectory
  - floor-pin share (|r − 1.25e-5/h| <= 1e-9), negative-hour share
  - daily two-leg package $ series on FIXED notionals = the wide arm's
    stage-1 time-average leg notionals; worst rolling 30d/90d, longest
    negative run, negative-day fraction, AR(1)
  - regime split by Binance LINKUSDT trailing-30d return (E009 test B)
  - HL-vs-Binance 8h sign agreement (E009 test F, cross-venue guard)

Decision inputs (pre-registered):
  F1  trailing-12m central two-leg package on wide-arm always-in notionals
      must be > −$1.00/day.
  F2  funding-substitution: per arm, dfund = sum over held(central) hours of
      (rbar_LINK − r_h)·ntl0 + (rbar_ETH − r_h)·ntl1, /days; stage-2 exact
      central + dfund must stay >= +$2.7397/day on any arm claiming the
      SUPPORTED net clause.

Output: out/funding_results.json.
"""

from __future__ import annotations

import csv
from collections import defaultdict
from datetime import datetime, timezone

import numpy as np
import pandas as pd

import common11 as C

E9A = C._load_by_path("e009_analyze", C.BMS / "e009" / "analyze.py")

PIN_RATE, PIN_TOL = 1.25e-5, 1e-9
END_DAY = "2026-09-02"          # last complete UTC day of the frozen fetch
F1_FLOOR = -1.00                # $/day, pre-registered
TARGET = C.TARGET_10PCT


def load_hourly(path) -> dict[int, float]:
    out = {}
    with open(path) as f:
        for row in csv.DictReader(f):
            out[int(row["time_ms"]) // 3_600_000] = float(
                row["funding_rate_hourly"])
    return out


def day_of(hour_key: int) -> str:
    return datetime.fromtimestamp(hour_key * 3600, tz=timezone.utc
                                  ).strftime("%Y-%m-%d")


def trailing_12m_mean(series: dict[int, float]) -> float:
    end = int(datetime.strptime(END_DAY, "%Y-%m-%d")
              .replace(tzinfo=timezone.utc).timestamp() // 3600) + 24
    start = end - 365 * 24
    vals = [r for k, r in series.items() if start <= k < end]
    return float(np.mean(vals)) if vals else float("nan")


def main() -> int:
    link = load_hourly(C.E011 / "data" / "hl_funding_link_hourly_long.csv")
    eth = load_hourly(C.BMS / "e009" / "data"
                      / "hl_funding_eth_hourly_long.csv")

    # Fixed notionals: the wide arm's stage-1 time-average leg notionals.
    wide = pd.read_csv(C.OUT / "stage1_hours_arm_8.3pct.csv")
    N0 = float(wide["ntl0_usd"].mean())
    N1 = float(wide["ntl1_usd"].mean())

    rbar_link = trailing_12m_mean(link)
    rbar_eth = trailing_12m_mean(eth)

    # Daily two-leg package on the overlap of both series' coverage.
    common_hours = sorted(set(link) & set(eth))
    pkg_daily: dict[str, float] = defaultdict(float)
    for k in common_hours:
        pkg_daily[day_of(k)] += link[k] * N0 + eth[k] * N1
    days_sorted = sorted(pkg_daily)
    # Drop first/last partial days and everything past END_DAY.
    days_sorted = [d for d in days_sorted if d <= END_DAY][1:]
    series = [pkg_daily[d] for d in days_sorted]

    w30, w30d = E9A.rolling_min(days_sorted, series, 30)
    w90, w90d = E9A.rolling_min(days_sorted, series, 90)
    runs = E9A.negative_runs(days_sorted, series)
    longest = max((n for _, n in runs), default=0)
    t12 = [v for d, v in zip(days_sorted, series)
           if d > "2025-09-02" and d <= END_DAY]

    # Regime split: Binance LINKUSDT trailing-30d return (E009 test B).
    closes = {}
    with open(C.E011 / "data" / "binance_linkusdt_1d.csv") as f:
        for row in csv.DictReader(f):
            closes[row["iso_utc"][:10]] = float(row["close"])
    daylist = sorted(closes)
    idx = {d: i for i, d in enumerate(daylist)}
    up, down = [], []
    for d, v in zip(days_sorted, series):
        i = idx.get(d)
        if i is not None and i >= 31:
            r = closes[daylist[i - 1]] / closes[daylist[i - 31]] - 1.0
            (up if r >= 0 else down).append(v)

    # Cross-venue sign agreement on the 8h grid (E009 test F).
    agree = tot = 0
    with open(C.E011 / "data" / "binance_linkusdt_funding_8h.csv") as f:
        for row in csv.DictReader(f):
            t_end = int(row["funding_time_ms"]) // 3_600_000
            hl8 = [link[k] for k in range(t_end - 8, t_end) if k in link]
            if len(hl8) == 8:
                tot += 1
                if (sum(hl8) >= 0) == (float(row["funding_rate_8h"]) >= 0):
                    agree += 1

    def leg_stats(series_map: dict[int, float], upto=END_DAY) -> dict:
        ks = sorted(k for k in series_map if day_of(k) <= upto)
        rs = np.array([series_map[k] for k in ks])
        halves = defaultdict(list)
        for k, r in zip(ks, rs):
            d = day_of(k)
            halves[f"{d[:4]}H{1 if int(d[5:7]) <= 6 else 2}"].append(r)
        return {
            "first_utc": day_of(ks[0]), "last_utc": day_of(ks[-1]),
            "n_hours": len(ks),
            "mean_ann_pct": float(rs.mean() * 24 * 365 * 100),
            "trailing_12m_ann_pct":
                trailing_12m_mean(series_map) * 24 * 365 * 100,
            "pinned_frac_full": float(np.mean(np.abs(rs - PIN_RATE) <= PIN_TOL)),
            "negative_frac_full": float(np.mean(rs < 0)),
            "halves_ann_pct": {h: float(np.mean(v) * 24 * 365 * 100)
                               for h, v in sorted(halves.items())},
        }

    # F2 per arm from stage-1 held hours + stage-2 exact.
    stage2 = C.read_json(C.OUT / "stage2_results.json")
    f2 = {}
    for arm in C.arms():
        label = arm["label"]
        hrs = pd.read_csv(C.OUT / f"stage1_hours_{label}.csv")
        held = hrs["held_central"].to_numpy(bool)
        hkeys = hrs["hour_epoch"].to_numpy(np.int64) // 3600
        ntl0 = hrs["ntl0_usd"].to_numpy()
        ntl1 = hrs["ntl1_usd"].to_numpy()
        days = stage2["window"]["days"]
        dfund = 0.0
        for h in np.nonzero(held)[0]:
            k = int(hkeys[h])
            rl, re_ = link.get(k), eth.get(k)
            if rl is None or re_ is None:
                continue
            dfund += (rbar_link - rl) * ntl0[h] + (rbar_eth - re_) * ntl1[h]
        s2 = stage2["arms"][label]["points"]["central"]["per_day_usd"]
        f2[label] = {
            "stage2_central_per_day": s2,
            "dfund_per_day": dfund / days,
            "stage2_adj_per_day": s2 + dfund / days,
            "passes_f2_floor": bool(s2 + dfund / days >= TARGET),
        }

    pkg_trailing_12m = float(np.mean(t12)) if t12 else float("nan")
    payload = {
        "experiment": "E011", "part": "funding-persistence",
        "end_day_frozen": END_DAY,
        "notionals_usd": {"link_leg_N0": N0, "eth_leg_N1": N1,
                          "source": "stage-1 wide-arm time-average"},
        "link_leg": leg_stats(link),
        "eth_leg": leg_stats(eth),
        "trailing_12m_rate_hourly": {"link": rbar_link, "eth": rbar_eth},
        "package_daily_usd": {
            "coverage": [days_sorted[0], days_sorted[-1]],
            "n_days": len(days_sorted),
            "full_mean_per_day": float(np.mean(series)),
            "trailing_12m_mean_per_day": pkg_trailing_12m,
            "worst_rolling_30d_per_day": w30,
            "worst_rolling_30d_start": w30d,
            "worst_rolling_90d_per_day": w90,
            "worst_rolling_90d_start": w90d,
            "longest_negative_run_days": longest,
            "negative_day_fraction_full":
                float(np.mean(np.array(series) < 0)),
            "negative_day_fraction_trailing_12m":
                float(np.mean(np.array(t12) < 0)) if t12 else None,
            "ar1": E9A.ar1(series),
            "up_regime_mean_per_day":
                float(np.mean(up)) if up else None,
            "down_regime_mean_per_day":
                float(np.mean(down)) if down else None,
            "down_regime_day_share":
                len(down) / (len(up) + len(down)) if (up or down) else None,
        },
        "cross_venue_sign_agreement_8h":
            agree / tot if tot else None,
        "window_vs_long": {
            "window_link_ann_pct": 10.64, "window_eth_ann_pct": 7.21,
            "note": "window figures from committed e005 CSVs (M005 §3)"},
        "F1": {"floor_per_day": F1_FLOOR,
               "trailing_12m_package_per_day": pkg_trailing_12m,
               "passes": bool(pkg_trailing_12m > F1_FLOOR)},
        "F2": f2,
    }
    C.write_json(C.OUT / "funding_results.json", payload)
    print(f"N0=${N0:,.0f} N1=${N1:,.0f}")
    print(f"LINK: full {payload['link_leg']['mean_ann_pct']:+.2f}% ann, "
          f"t12m {payload['link_leg']['trailing_12m_ann_pct']:+.2f}%, "
          f"pinned {payload['link_leg']['pinned_frac_full']*100:.1f}%")
    print(f"ETH:  full {payload['eth_leg']['mean_ann_pct']:+.2f}% ann, "
          f"t12m {payload['eth_leg']['trailing_12m_ann_pct']:+.2f}%")
    p = payload["package_daily_usd"]
    print(f"package: full ${p['full_mean_per_day']:+.3f}/d  "
          f"t12m ${p['trailing_12m_mean_per_day']:+.3f}/d  "
          f"worst30d ${p['worst_rolling_30d_per_day']:+.3f}/d "
          f"({p['worst_rolling_30d_start']})  longest neg run "
          f"{p['longest_negative_run_days']}d")
    print(f"F1 passes: {payload['F1']['passes']}")
    for label, v in f2.items():
        print(f"F2 {label}: stage2 {v['stage2_central_per_day']:+.3f} "
              f"dfund {v['dfund_per_day']:+.3f} -> adj "
              f"{v['stage2_adj_per_day']:+.3f}/d "
              f"(floor pass: {v['passes_f2_floor']})")
    print(f"wrote {C.OUT/'funding_results.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
