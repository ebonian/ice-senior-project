#!/usr/bin/env python3
"""E009 contract tests — the blocking validity gate plus data hygiene.

    nix develop .#gate1 -c python backtest_model_server/e009/test_e009_contracts.py

Gate semantics (prereg): V1/V2 failure means STOP — report the discrepancy,
do not proceed to the verdict. Every test prints PASS/FAIL; exit 1 on any
FAIL.
"""

from __future__ import annotations

import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

E009 = Path(__file__).resolve().parent
sys.path.insert(0, str(E009))
import analyze as A  # noqa: E402

FAILED = []


def check(name: str, ok: bool, detail: str) -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}: {detail}")
    if not ok:
        FAILED.append(name)


def main() -> int:
    hl = A.load_hl()
    pkg = A.frozen_package()

    # ---- V1: identity vs E005's committed window --------------------
    committed = {}
    with open(A.E005_FUNDING_CSV) as f:
        for r in csv.DictReader(f):
            committed[int(r["time_ms"]) // 3_600_000 * 3600] = \
                float(r["funding_rate_hourly"])
    fresh = {t: r for t, r, _ in hl}
    overlap = [t for t in committed if t in fresh]
    max_diff = max((abs(fresh[t] - committed[t]) for t in overlap), default=1.0)
    frac = len(overlap) / len(committed)
    check("V1 identity", frac >= 0.999 and max_diff <= 1e-12,
          f"{len(overlap)}/{len(committed)} committed hours present "
          f"({frac:.4%}), max |drate| = {max_diff:.2e}")

    # ---- V2: figure reproduction (±5% of E005's committed replay) ----
    w0 = int(datetime(2026, 5, 1, tzinfo=timezone.utc).timestamp())
    w1 = int(datetime(2026, 8, 28, tzinfo=timezone.utc).timestamp())
    recomputed = sum(r for t, r, _ in hl if w0 <= t < w1) * A.NOTIONAL_USD / 119.0
    target = pkg["e005_funding_per_day"]
    rel = recomputed / target - 1.0
    check("V2 reproduction", abs(rel) <= 0.05,
          f"recomputed ${recomputed:.5f}/day vs committed ${target:.5f}/day "
          f"({rel:+.2%}; calibrated expectation -4.28%)")

    # ---- coverage census: <=2% missing per 90-day span ---------------
    # Runs over the hourly-era analysis coverage (COVERAGE_START_DAY on):
    # HL's 2023-05/06 records are 8h-interval era, excluded by design
    # (documented deviation in the experiment file).
    from datetime import datetime as _dt
    cov_s = int(_dt.strptime(A.COVERAGE_START_DAY, "%Y-%m-%d")
                .replace(tzinfo=timezone.utc).timestamp())
    hl = [x for x in hl if x[0] >= cov_s]
    fresh = {t: r for t, r, _ in hl}
    t_first, t_last = hl[0][0], hl[-1][0]
    expected = (t_last - t_first) // 3600 + 1
    have = set(fresh)
    missing_total = expected - len(have)
    worst_span, worst_start = 0.0, None
    span = 90 * 24 * 3600
    t = t_first
    while t <= t_last:
        e = min(t + span, t_last + 3600)
        n_exp = (e - t) // 3600
        n_have = sum(1 for h in range(t, e, 3600) if h in have)
        miss = 1.0 - n_have / n_exp
        if miss > worst_span:
            worst_span, worst_start = miss, t
        t += span
    check("coverage census", worst_span <= 0.02,
          f"{missing_total}/{expected} hours missing overall "
          f"({missing_total / expected:.2%}); worst 90d span "
          f"{worst_span:.2%} starting "
          f"{datetime.fromtimestamp(worst_start, tz=timezone.utc).date()}")

    # ---- no-lookahead: rolling stats and regime labels ---------------
    res_pkg = A.frozen_package()
    days, carry, package, _ = A.daily_series(hl, res_pkg["residual_per_day"])
    cut = len(days) - 200
    days_t, package_t = days[:cut], package[:cut]
    full_windows = {}
    s = None
    for i in range(len(package) - 30 + 1):
        full_windows[days[i]] = sum(package[i:i + 30]) / 30
    trunc_windows = {}
    for i in range(len(package_t) - 30 + 1):
        trunc_windows[days_t[i]] = sum(package_t[i:i + 30]) / 30
    diffs = [abs(full_windows[d] - trunc_windows[d]) for d in trunc_windows]
    check("no-lookahead rolling", max(diffs) == 0.0,
          f"{len(trunc_windows)} truncated 30d windows identical to full-series "
          f"values (max diff {max(diffs):.1e})")

    closes = A.load_binance_daily()
    daylist = sorted(closes)
    probe = days[cut]
    idx = daylist.index(probe)
    lab_full = closes[daylist[idx - 1]] / closes[daylist[idx - 31]] - 1.0
    closes_t = {d: c for d, c in closes.items() if d < probe}
    daylist_t = sorted(closes_t)
    lab_trunc = closes_t[daylist_t[-1]] / closes_t[daylist_t[-31]] - 1.0
    check("no-lookahead regime", lab_full == lab_trunc
          and daylist_t[-1] == daylist[idx - 1],
          f"regime input for {probe} uses closes through {daylist_t[-1]} only")

    # ---- determinism: run() twice, byte-identical ---------------------
    r1 = json.dumps(A.run(), sort_keys=True)
    r2 = json.dumps(A.run(), sort_keys=True)
    check("determinism", r1 == r2, f"{len(r1)} bytes, identical across runs")

    print()
    if FAILED:
        print("CONTRACTS FAILED:", ", ".join(FAILED))
        if any(f.startswith("V") for f in FAILED):
            print("VALIDITY GATE FAILED — prereg says STOP; "
                  "report the discrepancy, do not judge.")
        return 1
    print("all contracts PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
