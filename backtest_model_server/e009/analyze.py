#!/usr/bin/env python3
"""E009 analysis — the M003 §3 pre-named persistence tests, nothing else.

    nix develop .#gate1 -c python backtest_model_server/e009/analyze.py

Reads only the committed CSVs under data/ plus E005's committed
results.json (for the frozen package constants). Deterministic, no RNG:
out/results.json must be byte-identical across runs (contract-tested).

Frozen package (E009 prereg): carry_$ = rate_h x $1,015 per hour;
package net = carry + the E005 non-funding residual, derived here from
E005's committed results.json rather than retyped.
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

E009 = Path(__file__).resolve().parent
DATA = E009 / "data"
OUT = E009 / "out"
E005_RESULTS = (E009.parent / "e005" / "out" / "wsteth_weth_0p01"
                / "lag1h_rh1h" / "results.json")
E005_FUNDING_CSV = (E009.parent / "e005" / "data" / "funding"
                    / "hl_funding_eth_hourly.csv")

NOTIONAL_USD = 1015.0          # frozen static full-notional ETH short (E005)
PIN_RATE = 1.25e-5             # HL interest component: 0.01%/8h = 0.00125%/h
PIN_TOL = 1e-9
END_DAY = "2026-09-03"         # frozen fetch boundary (exclusive)

# HL's first weeks used an 8h funding interval (records at 00/08/16 UTC,
# 7h gaps), transitioning to hourly through June 2023. The hourly clamp
# mechanics E009's tests assume only exist from the hourly era, so analysis
# coverage starts here; the fetched CSV keeps the early rows untouched.
# Recorded as a deviation in E009-funding-persistence.md.
COVERAGE_START_DAY = "2023-07-01"


# ---------------------------------------------------------------- loading

def frozen_package() -> dict:
    """E005 committed figures for arm_0.1pct central — the frozen anchors."""
    j = json.loads(E005_RESULTS.read_text())
    arm = next(a for a in j["arms"] if a["arm"] == "arm_0.1pct")
    tot = arm["total"]
    days = tot["hours"] / 24.0
    funding_per_day = tot["funding_usd"] / days
    residual_per_day = (tot["net_usd_central"] - tot["funding_usd"]) / days
    return {"e005_days": days,
            "e005_funding_usd_total": tot["funding_usd"],
            "e005_funding_per_day": funding_per_day,
            "e005_net_central_per_day": tot["per_day_central"],
            "residual_per_day": residual_per_day}


def load_hl() -> list[tuple[int, float, float | None]]:
    """(hour_epoch_s, rate, premium) sorted; hour = floor of record time."""
    rows = []
    with open(DATA / "hl_funding_eth_hourly_long.csv") as f:
        for r in csv.DictReader(f):
            t = int(r["time_ms"]) // 3_600_000 * 3600
            prem = float(r["premium"]) if r["premium"] else None
            rows.append((t, float(r["funding_rate_hourly"]), prem))
    rows.sort()
    return rows


def load_binance_funding() -> list[tuple[int, float]]:
    rows = []
    with open(DATA / "binance_ethusdt_funding_8h.csv") as f:
        for r in csv.DictReader(f):
            rows.append((int(r["funding_time_ms"]) // 1000,
                         float(r["funding_rate_8h"])))
    rows.sort()
    return rows


def load_binance_daily() -> dict[str, float]:
    closes = {}
    with open(DATA / "binance_ethusdt_1d.csv") as f:
        for r in csv.DictReader(f):
            day = datetime.fromtimestamp(int(r["open_time_ms"]) / 1000,
                                         tz=timezone.utc).strftime("%Y-%m-%d")
            closes[day] = float(r["close"])
    return closes


def day_of(epoch_s: int) -> str:
    return datetime.fromtimestamp(epoch_s, tz=timezone.utc).strftime("%Y-%m-%d")


def day_range(first: str, last_exclusive: str) -> list[str]:
    d = datetime.strptime(first, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    end = datetime.strptime(last_exclusive, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    out = []
    while d < end:
        out.append(d.strftime("%Y-%m-%d"))
        d += timedelta(days=1)
    return out


# ---------------------------------------------------------------- series

def daily_series(hl, residual_per_day, first_day=None, end_day=END_DAY):
    """Calendar-complete daily carry/package series (missing hours accrue 0)."""
    acc = defaultdict(float)
    nrows = defaultdict(int)
    for t, rate, _ in hl:
        acc[day_of(t)] += rate * NOTIONAL_USD
        nrows[day_of(t)] += 1
    first = first_day or day_of(hl[0][0])
    days = day_range(first, end_day)
    carry = [acc.get(d, 0.0) for d in days]
    package = [c + residual_per_day for c in carry]
    hours = [nrows.get(d, 0) for d in days]
    return days, carry, package, hours


def rolling_min(days, series, w):
    """(min_mean, window_start_day) over every fully contained w-day window."""
    best, best_day = None, None
    if len(series) < w:
        return None, None
    s = sum(series[:w])
    best, best_day = s / w, days[0]
    for i in range(1, len(series) - w + 1):
        s += series[i + w - 1] - series[i - 1]
        m = s / w
        if m < best:
            best, best_day = m, days[i]
    return best, best_day


def negative_runs(days, series):
    """Maximal runs of consecutive days with series < 0 → [(start, len)]."""
    runs, start, n = [], None, 0
    for d, v in zip(days, series):
        if v < 0:
            if start is None:
                start = d
            n += 1
        else:
            if start is not None:
                runs.append((start, n))
            start, n = None, 0
    if start is not None:
        runs.append((start, n))
    return runs


def ar1(series):
    xs = series[:-1]
    ys = series[1:]
    mx = sum(series) / len(series)
    num = sum((x - mx) * (y - mx) for x, y in zip(xs, ys))
    den = sum((x - mx) ** 2 for x in xs)
    if den == 0:
        return None, None
    phi = num / den
    import math
    hl_days = (math.log(0.5) / math.log(abs(phi))
               if 0 < abs(phi) < 1 else None)
    return phi, hl_days


# ---------------------------------------------------------------- tests

def run() -> dict:
    pkg = frozen_package()
    residual = pkg["residual_per_day"]
    hl_all = load_hl()
    cov_start_s = int(datetime.strptime(COVERAGE_START_DAY, "%Y-%m-%d")
                      .replace(tzinfo=timezone.utc).timestamp())
    hl = [x for x in hl_all if x[0] >= cov_start_s]
    bf = load_binance_funding()
    closes = load_binance_daily()

    days, carry, package, hours_per_day = daily_series(
        hl, residual, first_day=COVERAGE_START_DAY)
    res: dict = {"frozen": {**pkg, "notional_usd": NOTIONAL_USD,
                            "pin_rate": PIN_RATE, "end_day": END_DAY,
                            "coverage_start_day": COVERAGE_START_DAY},
                 "coverage": {
                     "hl_earliest_record_utc":
                         datetime.fromtimestamp(hl_all[0][0], tz=timezone.utc)
                         .strftime("%Y-%m-%dT%H:%M"),
                     "era_note": "2023-05-12..06-30 is HL's 8h-interval/"
                         "transition era; analysis coverage starts "
                         + COVERAGE_START_DAY + " (hourly era)",
                     "hl_last_hour_utc": datetime.fromtimestamp(hl[-1][0], tz=timezone.utc)
                         .strftime("%Y-%m-%dT%H:%M"),
                     "hl_rows_hourly_era": len(hl),
                     "hl_days": len(days),
                     "days_with_lt_20_hours":
                         sum(1 for h in hours_per_day if h < 20)}}

    # --- A: trailing-12m central --------------------------------------
    t12 = days[-365:]
    c12 = carry[-365:]
    p12 = package[-365:]
    res["A_trailing_12m"] = {
        "window": [t12[0], t12[-1]],
        "carry_per_day": sum(c12) / 365.0,
        "package_per_day": sum(p12) / 365.0,
        "package_apr_pct_on_1420": sum(p12) / 365.0 * 365 / 1420.0 * 100,
        "negative_package_day_fraction":
            sum(1 for v in p12 if v < 0) / 365.0}

    # --- B: full-history and regime-conditional means -----------------
    halves = defaultdict(list)
    for d, v in zip(days, package):
        y, m = d[:4], int(d[5:7])
        halves[f"{y}H{1 if m <= 6 else 2}"].append(v)
    regime = {}
    daylist = sorted(closes)
    idx = {d: i for i, d in enumerate(daylist)}
    for d in days:
        i = idx.get(d)
        if i is not None and i >= 31:
            r = closes[daylist[i - 1]] / closes[daylist[i - 31]] - 1.0
            regime[d] = "up" if r >= 0 else "down"
    up = [v for d, v in zip(days, package) if regime.get(d) == "up"]
    down = [v for d, v in zip(days, package) if regime.get(d) == "down"]
    res["B_regimes"] = {
        "full_history_package_per_day": sum(package) / len(package),
        "full_history_carry_per_day": sum(carry) / len(carry),
        "half_year_package_per_day":
            {k: sum(v) / len(v) for k, v in sorted(halves.items())},
        "up_regime_package_per_day": sum(up) / len(up) if up else None,
        "down_regime_package_per_day": sum(down) / len(down) if down else None,
        "down_regime_day_share": len(down) / (len(up) + len(down))
            if (up or down) else None}

    # --- C: worst stretches -------------------------------------------
    w30, w30d = rolling_min(days, package, 30)
    w90, w90d = rolling_min(days, package, 90)
    runs = negative_runs(days, package)
    longest = max((n for _, n in runs), default=0)
    res["C_stretches"] = {
        "worst_rolling_30d_package_per_day": w30,
        "worst_rolling_30d_window_start": w30d,
        "worst_rolling_90d_package_per_day": w90,
        "worst_rolling_90d_window_start": w90d,
        "longest_negative_package_run_days": longest,
        "runs_ge_14d": [(s, n) for s, n in runs if n >= 14]}

    # --- D: mean-reversion structure ----------------------------------
    phi, half_life = ar1(carry)
    lens = sorted((n for _, n in runs), reverse=True)
    neg_hours = sum(1 for _, r, _ in hl if r < 0)
    by_q = defaultdict(lambda: [0, 0])
    for t, r, _ in hl:
        q = day_of(t)[:4] + "Q" + str((int(day_of(t)[5:7]) - 1) // 3 + 1)
        by_q[q][0] += 1
        if r < 0:
            by_q[q][1] += 1
    res["D_structure"] = {
        "ar1_phi_daily_carry": phi,
        "ar1_half_life_days": half_life,
        "negative_hour_fraction_full": neg_hours / len(hl),
        "negative_hour_fraction_by_quarter":
            {q: c[1] / c[0] for q, c in sorted(by_q.items())},
        "negative_run_lengths_top10": lens[:10],
        "n_disjoint_runs_ge_14d": sum(1 for n in lens if n >= 14)}

    # --- E: clamp-pin decomposition -----------------------------------
    pinned = [(t, r) for t, r, _ in hl if abs(r - PIN_RATE) <= PIN_TOL]
    pin_carry = sum(r for _, r in pinned) * NOTIONAL_USD
    tot_carry = sum(r for _, r, _ in hl) * NOTIONAL_USD
    hl12_start = int(datetime.strptime(t12[0], "%Y-%m-%d")
                     .replace(tzinfo=timezone.utc).timestamp())
    hl12 = [(t, r) for t, r, _ in hl if t >= hl12_start]
    pinned12 = [(t, r) for t, r in hl12 if abs(r - PIN_RATE) <= PIN_TOL]
    res["E_pin"] = {
        "pinned_hour_fraction_full": len(pinned) / len(hl),
        "pinned_hour_fraction_trailing_12m":
            len(pinned12) / len(hl12) if hl12 else None,
        "pin_carry_share_of_total_full":
            pin_carry / tot_carry if tot_carry else None,
        "capped_hours_abs_rate_ge_4pct":
            sum(1 for _, r, _ in hl if abs(r) >= 0.04),
        "fully_pinned_package_per_day":
            PIN_RATE * 24 * NOTIONAL_USD + residual}

    # --- F: Binance cross-venue (descriptive) -------------------------
    hl_by_hour = {t: r for t, r, _ in hl}
    pairs = []
    for t, rate8 in bf:
        h = t // 3600 * 3600
        s = [hl_by_hour[h - k * 3600] for k in range(8)
             if (h - k * 3600) in hl_by_hour]
        if len(s) >= 6:
            pairs.append((sum(s), rate8))
    sign_agree = (sum(1 for a, b in pairs
                      if (a >= 0) == (b >= 0)) / len(pairs)) if pairs else None
    n = len(pairs)
    corr = None
    if n > 2:
        ma = sum(a for a, _ in pairs) / n
        mb = sum(b for _, b in pairs) / n
        ca = sum((a - ma) ** 2 for a, _ in pairs) ** 0.5
        cb = sum((b - mb) ** 2 for _, b in pairs) ** 0.5
        if ca and cb:
            corr = sum((a - ma) * (b - mb) for a, b in pairs) / (ca * cb)
    # Binance-only pre-HL era at the frozen notional (descriptive)
    bacc = defaultdict(float)
    for t, rate8 in bf:
        bacc[day_of(t - 1)] += rate8 * NOTIONAL_USD
    bdays_all = day_range(min(bacc), END_DAY)
    bpkg = [bacc.get(d, 0.0) + residual for d in bdays_all]
    bw30, bw30d = rolling_min(bdays_all, bpkg, 30)
    bruns = negative_runs(bdays_all, bpkg)
    res["F_binance"] = {
        "overlap_8h_intervals": n,
        "sign_agreement_fraction": sign_agree,
        "pearson_corr_8h_sums": corr,
        "binance_full_package_per_day": sum(bpkg) / len(bpkg),
        "binance_worst_rolling_30d": bw30,
        "binance_worst_rolling_30d_start": bw30d,
        "binance_longest_negative_run_days":
            max((r for _, r in bruns), default=0),
        "binance_runs_ge_21d": [(s, r) for s, r in bruns if r >= 21]}

    # --- decision (prereg clauses, mechanical) ------------------------
    central = res["A_trailing_12m"]["package_per_day"]
    c1 = w30 is not None and w30 >= -0.50
    c2 = longest <= 21
    d1 = res["D_structure"]["n_disjoint_runs_ge_14d"] < 2
    d2 = res["A_trailing_12m"]["negative_package_day_fraction"] <= 0.35
    guard = sign_agree is not None and sign_agree >= 0.60
    supported = central >= 0.15 and c1 and c2 and d1 and d2 and guard
    refuted = central < 0.10 or not c1 or not c2
    verdict = ("SUPPORTED" if supported
               else "REFUTED" if refuted else "INCONCLUSIVE")
    res["decision"] = {
        "central_package_per_day": central,
        "clauses": {"central_ge_0.15": central >= 0.15,
                    "central_lt_0.10": central < 0.10,
                    "C1_worst30d_ge_-0.50": c1,
                    "C2_longest_run_le_21d": c2,
                    "D1_lt_2_runs_ge_14d": d1,
                    "D2_neg_frac_le_35pct": d2,
                    "cross_venue_guard_ok": guard},
        "verdict": verdict}
    return res


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    res = run()
    with open(OUT / "results.json", "w") as f:
        json.dump(res, f, indent=1, sort_keys=True)
        f.write("\n")
    d = res["decision"]
    print(f"central (trailing-12m package): ${d['central_package_per_day']:.4f}/day")
    for k, v in d["clauses"].items():
        print(f"  {k}: {v}")
    print("verdict:", d["verdict"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
