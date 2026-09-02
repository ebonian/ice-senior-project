#!/usr/bin/env python3
"""E007 — tune (2026-05→07) and judge (full window + held-out August).

    nix develop .#gate1 -c python backtest_model_server/e007/run_candidates.py \
        --phase tune --candidate c1 --arm 4
    ... (all 6 candidates x both arms) ...
    nix develop .#gate1 -c python backtest_model_server/e007/run_candidates.py \
        --phase final --arm 4

Tune phase: the tuning routine receives ONLY rows with hour < 2026-08-01
(asserted — contract 5). Objective: stage-2 exact net $/day, CENTRAL, on the
tune window. Grids are the pre-registered ones in causal_signals.py; the
argmax (ties: first in listed parameter order, then lowest θ) is frozen into
out/tune_<cand>_w<W>.json.

Final phase refuses to run until every candidate's tune file exists for BOTH
arms — no August number is computed before all parameters are frozen. It then
evaluates each frozen policy over the full window, reports all three envelope
points, the monthly split, held-out August $/day, and the descriptive AUC of
the tuned signal for E006's oracle-held hours (warmup 48h excluded, oriented
so >0.5 means the signal points toward held per its own rule direction).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

E007 = Path(__file__).resolve().parent
BMS = E007.parent
for p in (BMS / "gate1", BMS / "e003", BMS / "e006", E007):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
import race                      # noqa: E402
import oracle                    # noqa: E402
import causal_signals as CS      # noqa: E402
import evaluate as EV            # noqa: E402

CANDIDATES = ("c1", "c2", "c3", "c4", "c5", "c6")
ARMS = (4, 10)
WARMUP_H = 48


def auc(score: np.ndarray, label: np.ndarray) -> float:
    m = ~np.isnan(score)
    x, y = score[m], label[m]
    n1, n0 = int(y.sum()), int((~y).sum())
    if n1 == 0 or n0 == 0:
        return float("nan")
    r = pd.Series(x).rank(method="average").to_numpy()
    return float((r[y].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def rule_mask(signal: np.ndarray, theta: float, direction: int) -> np.ndarray:
    with np.errstate(invalid="ignore"):
        return (signal >= theta) if direction > 0 else (signal <= theta)


def candidate_family(cand: str, w: int, swaps: pd.DataFrame,
                     fam_cache: dict) -> dict:
    """{param_key: (signal, direction)} for one candidate; c6 inherits."""
    if "fam" not in fam_cache:
        fam_cache["fam"] = CS.build_all(w, swaps)
    if cand != "c6":
        return fam_cache["fam"][cand]
    lam = _best("c1", w)["param"]
    kap = _best("c3", w)["param"]
    s1, _ = fam_cache["fam"]["c1"][lam]
    s3, _ = fam_cache["fam"]["c3"][kap]
    return {f"lam{lam}_kap{kap}": ((s1, s3), +1)}


def _tune_path(cand: str, w: int) -> Path:
    return E007 / "out" / f"tune_{cand}_w{w}.json"


def _best(cand: str, w: int) -> dict:
    p = _tune_path(cand, w)
    if not p.exists():
        raise FileNotFoundError(f"{p} — tune {cand} w{w} first")
    return json.loads(p.read_text())["best"]


def tune_candidate(cand: str, family: dict, hs_tune: np.ndarray,
                   days_tune: float, swaps, funding, cache) -> dict:
    assert (hs_tune < CS.AUG1_EPOCH).all(), "tuning saw held-out data"
    n = len(hs_tune)
    grid = []
    for pkey, (sig, direction) in family.items():
        if cand == "c6":
            s1, s3 = sig
            s1t, s3t = s1[:n], s3[:n]
            th1 = np.nanpercentile(s1t, CS.THETA_DECILES)
            th2 = np.nanpercentile(s3t, CS.THETA_DECILES)
            combos = [((float(a), float(b)),
                       rule_mask(s1t, a, +1) & rule_mask(s3t, b, +1))
                      for a in th1 for b in th2]
        else:
            st = sig[:n]
            thetas = np.nanpercentile(st, CS.THETA_DECILES)
            combos = [((float(t),), rule_mask(st, t, direction)) for t in thetas]
        for theta, mask in combos:
            r = EV.evaluate_mask(mask, hs_tune, swaps, funding, cache)
            per_day = EV.net_usd(r["total"], "central") / days_tune
            grid.append({"param": pkey, "theta": theta,
                         "per_day_central": per_day,
                         "held_frac": float(mask.mean()),
                         "n_streaks": r["n_streaks"]})
    best = max(grid, key=lambda g: g["per_day_central"])
    return {"candidate": cand, "days_tune": days_tune,
            "grid": grid, "best": best}


def final_candidate(cand: str, w: int, hours: pd.DataFrame, days_full: float,
                    swaps, funding, cache, fam_cache) -> dict:
    hs = hours["hour_epoch"].to_numpy(np.int64)
    held_oracle = hours["held_central"].to_numpy(bool)
    best = _best(cand, w)
    family = candidate_family(cand, w, swaps, fam_cache)

    if cand == "c6":
        (s1, s3), _ = next(iter(family.values()))
        th1, th2 = best["theta"]
        mask = rule_mask(s1, th1, +1) & rule_mask(s3, th2, +1)
        score = np.minimum(pd.Series(s1).rank(pct=True).to_numpy(),
                           pd.Series(s3).rank(pct=True).to_numpy())
        pkey = best["param"]
    else:
        pkey = best["param"]
        sig, direction = family[pkey if pkey in family else int(pkey)]
        theta = best["theta"][0] if isinstance(best["theta"], list) else best["theta"]
        mask = rule_mask(sig, theta, direction)
        score = sig * direction

    r = EV.evaluate_mask(mask, hs, swaps, funding, cache)
    nets = {p: EV.net_usd(r["total"], p) for p in
            ("optimistic", "central", "pessimistic")}
    months = {lab: EV.net_usd(b, "central") for lab, b in sorted(r["months"].items())}
    ts_last = int(swaps["timestamp"].iloc[-1])
    days_aug = (ts_last - CS.AUG1_EPOCH) / 86400.0
    aug = months.get("2026-08", 0.0)
    runs = oracle.streaks_of(mask)
    lens = np.array([j - i + 1 for i, j in runs]) if runs else np.array([0])

    valid = np.zeros(len(hs), dtype=bool)
    valid[WARMUP_H:] = True
    return {
        "candidate": cand, "width": w, "param": pkey,
        "theta": best["theta"],
        "tune_per_day_central": best["per_day_central"],
        "full_window": {
            "days": days_full,
            "net_usd": nets,
            "per_day_usd": {k: v / days_full for k, v in nets.items()},
        },
        "months_net_central_usd": months,
        "months_positive": int(sum(v > 0 for v in months.values())),
        "heldout_august": {"days": days_aug, "net_central_usd": aug,
                           "per_day_usd": aug / days_aug},
        "held_frac": float(mask.mean()),
        "n_streaks": len(runs),
        "streak_hours_median": float(np.percentile(lens, 50)),
        "auc_oriented_vs_oracle_held":
            auc(np.where(valid, score, np.nan), held_oracle),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", choices=("tune", "final"), required=True)
    ap.add_argument("--candidate", choices=CANDIDATES)
    ap.add_argument("--arm", type=int, choices=ARMS, required=True)
    args = ap.parse_args()

    (E007 / "out").mkdir(exist_ok=True)
    stage1 = json.loads((BMS / "e006" / "out" / "stage1_results.json").read_text())
    days_full = stage1["window"]["days"]
    swaps = race.load_swaps(stage1["window"]["start"], stage1["window"]["end"])
    funding = race.load_funding()
    w = args.arm
    hours = CS.load_hours(w)
    hs = hours["hour_epoch"].to_numpy(np.int64)
    cache = EV.StreakCache(w)
    fam_cache: dict = {}

    if args.phase == "tune":
        if not args.candidate:
            raise SystemExit("--candidate required for tune")
        t0 = time.time()
        n_tune = int((hs < CS.AUG1_EPOCH).sum())
        days_tune = (CS.AUG1_EPOCH - int(hs[0])) / 86400.0
        family = candidate_family(args.candidate, w, swaps, fam_cache)
        out = tune_candidate(args.candidate, family, hs[:n_tune], days_tune,
                             swaps, funding, cache)
        cache.save()
        _tune_path(args.candidate, w).write_text(json.dumps(out, indent=2))
        b = out["best"]
        print(f"{args.candidate} w{w}: best param={b['param']} theta={b['theta']} "
              f"tune ${b['per_day_central']:+.3f}/day central "
              f"(held {b['held_frac']*100:.0f}%, {b['n_streaks']} streaks) "
              f"[{len(out['grid'])} configs, {time.time()-t0:.0f}s]")
        return 0

    # final: every candidate frozen on both arms first
    missing = [f"{c} w{a}" for c in CANDIDATES for a in ARMS
               if not _tune_path(c, a).exists()]
    if missing:
        raise SystemExit(f"final refused — untuned: {missing}")
    results = {}
    for cand in CANDIDATES:
        t0 = time.time()
        res = final_candidate(cand, w, hours, days_full, swaps, funding,
                              cache, fam_cache)
        cache.save()
        results[cand] = res
        (E007 / "out" / f"final_{cand}_w{w}.json").write_text(
            json.dumps(res, indent=2))
        fw = res["full_window"]["per_day_usd"]
        print(f"{cand} w{w}: full ${fw['central']:+.3f}/d "
              f"[opt {fw['optimistic']:+.3f} pess {fw['pessimistic']:+.3f}] "
              f"aug ${res['heldout_august']['per_day_usd']:+.3f}/d "
              f"months+ {res['months_positive']}/4 "
              f"AUC {res['auc_oriented_vs_oracle_held']:.3f} "
              f"({time.time()-t0:.0f}s)")
    (E007 / "out" / f"final_w{w}.json").write_text(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
