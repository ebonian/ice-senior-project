#!/usr/bin/env python3
"""E008 — tune (2026-05→07) and judge (full window + held-out August).

    nix develop .#gate1 -c python backtest_model_server/e008/run_e008.py \
        --phase tune --candidate s1 --arm 4
    ... (all 6 candidates x both arms) ...
    nix develop .#gate1 -c python backtest_model_server/e008/run_e008.py \
        --phase final --arm 4

E007's runner pattern. Tune receives ONLY rows with hour < 2026-08-01
(asserted — contract 5); objective is stage-2 exact net $/day, CENTRAL, on
the tune window; grids are streak_rules.py's frozen enumerations; the argmax
(ties: first config in enumeration order — Python max keeps the first
maximum) is frozen into out/tune_<cand>_w<W>.json. Tune grids checkpoint
progressively to out/tune_<cand>_w<W>.partial.json so an interrupted grid
resumes without recomputation.

Final refuses to run until every candidate's tune file exists for BOTH arms
— no August number is computed before all parameters are frozen. It reports
all three envelope points, the monthly split, held-out August $/day, streak
stats, and the descriptive oriented AUC vs E006's oracle-held hours.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

E008 = Path(__file__).resolve().parent
BMS = E008.parent
for p in (BMS / "gate1", BMS / "e003", BMS / "e006", BMS / "e007", E008):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
import race                      # noqa: E402  (e003)
import oracle                    # noqa: E402  (e006)
import evaluate as EV            # noqa: E402  (e007)
from run_candidates import auc   # noqa: E402  (e007)
import streak_rules as SR        # noqa: E402

ARMS = (4, 10)
WARMUP_H = 48


def _tune_path(cand: str, w: int) -> Path:
    return E008 / "out" / f"tune_{cand}_w{w}.json"


def _best(cand: str, w: int) -> dict:
    p = _tune_path(cand, w)
    if not p.exists():
        raise FileNotFoundError(f"{p} — tune {cand} w{w} first")
    return json.loads(p.read_text())["best"]


def assert_all_frozen(out_dir: Path) -> None:
    missing = [f"{c} w{a}" for c in SR.CANDIDATES for a in ARMS
               if not (out_dir / f"tune_{c}_w{a}.json").exists()]
    if missing:
        raise SystemExit(f"final refused — untuned: {missing}")


def tune_candidate(cand: str, sigs: dict, hs_tune: np.ndarray,
                   days_tune: float, swaps, funding, cache,
                   partial_path: Path | None = None) -> dict:
    assert (hs_tune < SR.AUG1_EPOCH).all(), "tuning saw held-out data"
    n = len(hs_tune)
    done: dict[str, dict] = {}
    if partial_path is not None and partial_path.exists():
        done = {g["key"]: g for g in json.loads(partial_path.read_text())["grid"]}
    grid = []
    for i, cfg in enumerate(SR.grid_configs(cand)):
        key = SR.cfg_key(cfg)
        if key in done:
            grid.append(done[key])
            continue
        mask = SR.make_mask(cand, cfg, sigs, n=n)
        r = EV.evaluate_mask(mask, hs_tune, swaps, funding, cache)
        per_day = EV.net_usd(r["total"], "central") / days_tune
        grid.append({"key": key, "cfg": cfg,
                     "per_day_central": per_day,
                     "held_frac": float(mask.mean()),
                     "n_streaks": r["n_streaks"]})
        if partial_path is not None and (i % 10 == 9):
            cache.save()
            partial_path.write_text(json.dumps({"grid": grid}))
    best = max(grid, key=lambda g: g["per_day_central"])
    return {"candidate": cand, "days_tune": days_tune,
            "consts": sigs["consts"], "grid": grid, "best": best}


def final_candidate(cand: str, w: int, sigs: dict, days_full: float,
                    swaps, funding, cache) -> dict:
    hs = sigs["hs"]
    held_oracle = sigs["hours"]["held_central"].to_numpy(bool)
    best = _best(cand, w)
    cfg = best["cfg"]

    mask = SR.make_mask(cand, cfg, sigs)
    r = EV.evaluate_mask(mask, hs, swaps, funding, cache)
    nets = {p: EV.net_usd(r["total"], p) for p in
            ("optimistic", "central", "pessimistic")}
    months = {lab: EV.net_usd(b, "central") for lab, b in sorted(r["months"].items())}
    ts_last = int(swaps["timestamp"].iloc[-1])
    days_aug = (ts_last - SR.AUG1_EPOCH) / 86400.0
    aug = months.get("2026-08", 0.0)
    runs = oracle.streaks_of(mask)
    lens = np.array([j - i + 1 for i, j in runs]) if runs else np.array([0])
    aug_mask = mask & (hs >= SR.AUG1_EPOCH)

    score = SR.auc_score(cand, cfg, sigs)
    valid = np.zeros(len(hs), dtype=bool)
    valid[WARMUP_H:] = True

    return {
        "candidate": cand, "width": w, "cfg": cfg,
        "tune_per_day_central": best["per_day_central"],
        "full_window": {
            "days": days_full,
            "net_usd": nets,
            "per_day_usd": {k: v / days_full for k, v in nets.items()},
        },
        "months_net_central_usd": months,
        "months_positive": int(sum(v > 0 for v in months.values())),
        "heldout_august": {"days": days_aug, "net_central_usd": aug,
                           "per_day_usd": aug / days_aug,
                           "held_hours": int(aug_mask.sum())},
        "held_frac": float(mask.mean()),
        "n_streaks": len(runs),
        "streak_hours_median": float(np.percentile(lens, 50)),
        "streak_hours_mean": float(lens.mean()),
        "auc_oriented_vs_oracle_held":
            auc(np.where(valid, score, np.nan), held_oracle),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", choices=("tune", "final"), required=True)
    ap.add_argument("--candidate", choices=SR.CANDIDATES)
    ap.add_argument("--arm", type=int, choices=ARMS, required=True)
    args = ap.parse_args()

    (E008 / "out").mkdir(exist_ok=True)
    stage1 = json.loads((BMS / "e006" / "out" / "stage1_results.json").read_text())
    days_full = stage1["window"]["days"]
    swaps = race.load_swaps(stage1["window"]["start"], stage1["window"]["end"])
    funding = race.load_funding()
    w = args.arm
    sigs = SR.build_signals(w)
    hs = sigs["hs"]
    cache = SR.E008Cache(w)

    if args.phase == "tune":
        if not args.candidate:
            raise SystemExit("--candidate required for tune")
        t0 = time.time()
        n_tune = int((hs < SR.AUG1_EPOCH).sum())
        days_tune = (SR.AUG1_EPOCH - int(hs[0])) / 86400.0
        partial = E008 / "out" / f"tune_{args.candidate}_w{w}.partial.json"
        out = tune_candidate(args.candidate, sigs, hs[:n_tune], days_tune,
                             swaps, funding, cache, partial_path=partial)
        cache.save()
        _tune_path(args.candidate, w).write_text(json.dumps(out, indent=2))
        if partial.exists():
            partial.unlink()
        b = out["best"]
        print(f"{args.candidate} w{w}: best cfg={b['cfg']} "
              f"tune ${b['per_day_central']:+.3f}/day central "
              f"(held {b['held_frac']*100:.0f}%, {b['n_streaks']} streaks) "
              f"[{len(out['grid'])} configs, {time.time()-t0:.0f}s]")
        return 0

    # final: every candidate frozen on both arms first
    assert_all_frozen(E008 / "out")
    results = {}
    for cand in SR.CANDIDATES:
        t0 = time.time()
        res = final_candidate(cand, w, sigs, days_full, swaps, funding, cache)
        cache.save()
        results[cand] = res
        (E008 / "out" / f"final_{cand}_w{w}.json").write_text(
            json.dumps(res, indent=2))
        fw = res["full_window"]["per_day_usd"]
        print(f"{cand} w{w}: full ${fw['central']:+.3f}/d "
              f"[opt {fw['optimistic']:+.3f} pess {fw['pessimistic']:+.3f}] "
              f"aug ${res['heldout_august']['per_day_usd']:+.3f}/d "
              f"months+ {res['months_positive']}/4 "
              f"held {res['held_frac']*100:.0f}% "
              f"{res['n_streaks']} streaks (med {res['streak_hours_median']:.0f}h) "
              f"AUC {res['auc_oriented_vs_oracle_held']:.3f} "
              f"({time.time()-t0:.0f}s)")
    (E008 / "out" / f"final_w{w}.json").write_text(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
