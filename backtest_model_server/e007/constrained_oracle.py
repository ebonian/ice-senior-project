#!/usr/bin/env python3
"""E007 memo-phase — CONSTRAINED oracle ceilings (the coarseness question).

    nix develop .#gate1 -c python backtest_model_server/e007/constrained_oracle.py

E006's oracle re-decides every hour and holds short streaks (median 3h). Before
hunting hour-scale causal signals, measure how much ceiling survives when the
oracle is forced to be COARSE — because coarse regime calls are what persistent
(daily-scale) signals can actually deliver:

  min-hold H   once entered, must stay >= H hours (H in 6, 12, 24)
  grain g      enter/exit only at UTC boundaries aligned to g hours
               (g in 4, 24 — 24 = a daily regime call at 00:00 UTC)

Same per-hour stage-1 payoffs and switch costs as E006 (out/stage1_hours_w*.csv,
byte-identical inputs), same two-state DP extended with the constraint, CENTRAL
envelope point. The constrained DP value is a stage-1 upper bound on every
timing policy OBEYING the constraint (same over-crediting as oracle.py). The
chosen streaks are then re-simulated exactly through E003's `run_arm` via
e006/exact.py's `simulate_streak` — the realistic constrained ceiling.

This is descriptive input to memo M001 (feeds candidate ranking), not a verdict.

Output: out/constrained_oracle.json, printed table.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

E007 = Path(__file__).resolve().parent
BMS = E007.parent
for p in (BMS / "gate1", BMS / "e003", BMS / "e006"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
import envelope as ENV     # noqa: E402
import race                # noqa: E402
import oracle              # noqa: E402
import exact               # noqa: E402

NEG = -1e18
ARMS = (4, 10, 40, 160)
E006_OUT = BMS / "e006" / "out"


def dp_minhold(payoff: np.ndarray, enter: np.ndarray, exit_: np.ndarray,
               H: int) -> tuple[float, np.ndarray]:
    """DP with a minimum hold of H (>= 2) hours. States at boundary t: out;
    in with age a in 1..H-1 (exit forbidden); in-free (age >= H). Strict: no
    exit before age H, including at the window end. Full n*H value table,
    then a walk back — O(n*H) time and memory, small here."""
    n = len(payoff)
    out_v = np.full(n + 1, NEG); out_v[0] = 0.0
    age_v = np.full((n + 1, H), NEG)      # age_v[t, a], a in 1..H-1
    free_v = np.full(n + 1, NEG)
    for t in range(n):
        via_exit = free_v[t] - exit_[t]
        out_v[t + 1] = max(out_v[t], via_exit)
        age_v[t + 1, 1] = out_v[t] - enter[t] + payoff[t]
        for a in range(2, H):
            if age_v[t, a - 1] > NEG / 2:
                age_v[t + 1, a] = age_v[t, a - 1] + payoff[t]
        best = max(free_v[t], age_v[t, H - 1])
        if best > NEG / 2:
            free_v[t + 1] = best + payoff[t]
    end_exit = free_v[n] - exit_[n]
    value = max(out_v[n], end_exit)

    held = np.zeros(n, dtype=bool)
    state: tuple = ("out",) if out_v[n] >= end_exit else ("free",)
    for t in range(n - 1, -1, -1):
        if state[0] == "out":
            via_exit = free_v[t] - exit_[t]
            state = ("free",) if via_exit > out_v[t] else ("out",)
        elif state[0] == "free":
            held[t] = True
            state = ("free",) if free_v[t] >= age_v[t, H - 1] else ("age", H - 1)
        else:
            held[t] = True
            a = state[1]
            state = ("out",) if a == 1 else ("age", a - 1)
    return value, held


def dp_grain(payoff: np.ndarray, enter: np.ndarray, exit_: np.ndarray,
             hs: np.ndarray, g: int) -> tuple[float, np.ndarray]:
    """Two-state DP where enter/exit are allowed only at UTC epoch boundaries
    divisible by g hours (window end always allows the closing exit)."""
    n = len(payoff)
    can = (hs % (g * 3600)) == 0        # decision allowed at hour t's start
    in_prev, out_prev = NEG, 0.0
    from_in = np.zeros(n, dtype=bool)
    from_out = np.zeros(n, dtype=bool)
    for t in range(n):
        if can[t]:
            via_enter = out_prev - enter[t]
            if in_prev >= via_enter:
                in_cur, from_in[t] = in_prev + payoff[t], True
            else:
                in_cur = via_enter + payoff[t]
            via_exit = in_prev - exit_[t]
            if out_prev >= via_exit:
                out_cur, from_out[t] = out_prev, True
            else:
                out_cur = via_exit
        else:
            in_cur, from_in[t] = (in_prev + payoff[t] if in_prev > NEG / 2
                                  else NEG), True
            out_cur, from_out[t] = out_prev, True
        in_prev, out_prev = in_cur, out_cur
    end_exit = in_prev - exit_[n]
    value = max(out_prev, end_exit)
    held = np.zeros(n, dtype=bool)
    state = "in" if end_exit > out_prev else "out"
    for t in range(n - 1, -1, -1):
        if state == "in":
            held[t] = True
            state = "in" if from_in[t] else "out"
        else:
            state = "out" if from_out[t] else "in"
    return value, held


def stage2_exact(w: int, held: np.ndarray, hs: np.ndarray,
                 swaps: pd.DataFrame, funding: dict, days: float) -> dict:
    runs = oracle.streaks_of(held)
    total: dict = {}
    n_sim = 0
    for (i, j) in runs:
        r = exact.simulate_streak(w, swaps, funding, int(hs[i]), int(hs[j]) + 3600)
        if r is None:
            continue
        exact.add_bucket(total, r.total)
        n_sim += 1
    pt = ENV.ENVELOPE_BY_NAME["central"]
    v = exact.net_usd(total, pt) if total else 0.0
    return {"net_central_usd": v, "per_day_usd": v / days,
            "n_streaks": len(runs), "n_simulated": n_sim,
            "held_hours": total.get("hours", 0.0)}


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--arms", type=int, nargs="*", default=list(ARMS))
    args = ap.parse_args()

    stage1 = json.loads((E006_OUT / "stage1_results.json").read_text())
    days = stage1["window"]["days"]
    swaps = race.load_swaps(stage1["window"]["start"], stage1["window"]["end"])
    funding = race.load_funding()
    point = ENV.ENVELOPE_BY_NAME["central"]

    variants = ([("unconstrained", None, None)]
                + [(f"minhold_{H}h", H, None) for H in (6, 12, 24)]
                + [(f"grain_{g}h", None, g) for g in (4, 24)])

    payload = {"experiment": "E007-memo", "purpose":
               "constrained stage-1 oracle ceilings + stage-2 exact re-sim "
               "(central envelope) — memo M001 coarseness question",
               "cost_model_version": stage1["cost_model_version"],
               "envelope_version": stage1["envelope_version"],
               "window": stage1["window"], "arms": {}}
    out = E007.joinpath("out", "constrained_oracle.json")
    if out.exists():
        payload["arms"] = json.loads(out.read_text()).get("arms", {})

    for w in args.arms:
        if f"w{w}" in payload["arms"]:
            print(f"w{w}: checkpointed, skipping")
            continue
        hours = pd.read_csv(E006_OUT / f"stage1_hours_w{w}.csv")
        hs = hours["hour_epoch"].to_numpy(np.int64)
        pay = hours["payoff_usd"].to_numpy()
        enter, exit_ = oracle.switch_costs(hours, point)
        arm_out = {}
        for name, H, g in variants:
            t0 = time.time()
            if H is None and g is None:
                value, held = oracle.dp_select(pay, enter, exit_)
            elif H is not None:
                value, held = dp_minhold(pay, enter, exit_, H)
            else:
                value, held = dp_grain(pay, enter, exit_, hs, g)
            runs = oracle.streaks_of(held)
            lens = np.array([j - i + 1 for i, j in runs]) if runs else np.array([0])
            s2 = stage2_exact(w, held, hs, swaps, funding, days)
            arm_out[name] = {
                "stage1_value_usd": float(value),
                "stage1_per_day_usd": float(value / days),
                "held_frac": float(held.mean()),
                "n_streaks": len(runs),
                "streak_hours_median": float(np.percentile(lens, 50)),
                "stage2": s2,
            }
            print(f"w{w:<4d} {name:<14s} UB ${value/days:+7.3f}/d  "
                  f"exact ${s2['per_day_usd']:+7.3f}/d  held {held.mean()*100:5.1f}%  "
                  f"{len(runs):4d} streaks (med {np.percentile(lens, 50):.0f}h)  "
                  f"{time.time()-t0:.0f}s")
        payload["arms"][f"w{w}"] = arm_out
        out.write_text(json.dumps(payload, indent=2))
        print(f"checkpointed {out} after w{w}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
