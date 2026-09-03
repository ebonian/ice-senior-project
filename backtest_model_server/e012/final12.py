#!/usr/bin/env python3
"""E012 final phase — frozen rules on the full window, all coupled points.

    nix develop .#gate1 -c python backtest_model_server/e012/final12.py [--budget-seconds N]

REFUSES to run without a complete out/params_frozen.json (12 cells) — the
blocking isolation contract. Masks are rebuilt from the frozen ABSOLUTE
thresholds (and, for V3, the frozen z-stats); no quantile is recomputed.
Each cell is evaluated stage-2 exact at all three coupled envelope points
over the full 118.99-day window; August = the 2026-08 calendar bucket of
that same run (costs land in the month booked — E011's convention).
Baselines: the all-ones mask per arm (== E010's committed race rows, by
contract) evaluated identically.

Output: out/final_results.json (checkpointed per cell).
"""

from __future__ import annotations

import argparse
import time

import numpy as np

import common12 as C12
import gates12 as G12

FROZEN_JSON = C12.OUT / "params_frozen.json"
FINAL_JSON = C12.OUT / "final_results.json"


def load_frozen(path=FROZEN_JSON) -> dict:
    if not path.exists():
        raise FileNotFoundError(
            f"{path} missing — the final phase refuses to run until every "
            f"candidate x arm parameter set is frozen (prereg isolation)")
    frozen = C12.read_json(path)
    want = {(cid, arm) for cid in G12.CANDIDATES for arm in C12.ARM_LABELS}
    have = {(c["candidate"], c["arm"]) for c in frozen["cells"]}
    if have != want:
        raise ValueError(f"frozen file incomplete: {sorted(want - have)}")
    return frozen


def eval_frozen_cell(cell: dict) -> dict:
    hs, _ = C12.hours_and_closes()
    cand = G12.CANDIDATES[cell["candidate"]]
    arm = next(a for a in C12.arms12() if a["label"] == cell["arm"])
    sig, _ = G12.signal_for(cand, cell["cfg"],
                            zstats=cell.get("har_zstats_tune"))
    mask = G12.build_mask(cand, cell["cfg"], sig,
                          cell["thresholds_abs"], hs)
    _, swaps, _, _ = C12.C11.load_all()
    days = C12.C11.window_days(swaps)
    res = C12.eval_mask(arm, mask, hs, points=C12.POINTS,
                        unlock_heldout=True)
    out = {"candidate": cell["candidate"], "arm": cell["arm"],
           "cfg": cell["cfg"], "thresholds_abs": cell["thresholds_abs"],
           "tune": cell["tune"], "days": days,
           "held_hours_mask": res["held_hours_mask"],
           "held_frac_mask": res["held_hours_mask"] / len(hs),
           "n_streaks": res["n_streaks"], "points": {}}
    for pn in C12.POINTS:
        c = res["points"][pn]
        out["points"][pn] = {
            "net_usd": c["net_usd"],
            "per_day_usd": c["net_usd"] / days,
            "august_net_usd": c["months_net_usd"].get("2026-08", 0.0),
            "months_net_usd": c["months_net_usd"],
            "n_streaks_simulated": c["n_streaks_simulated"],
            "held_hours_simulated": c["held_hours_simulated"],
            "n_recenters": c["n_recenters"],
            "max_lp_value_abs_gap_usd": c["max_lp_value_abs_gap_usd"],
        }
        if pn == "central":
            out["streak_rows"] = res["points"][pn]["streak_rows"]
    return out


def baselines() -> dict:
    """always_in per arm = E010's committed race rows, regenerated as the
    swap-anchored spanning streak (E011's baseline-contract construction;
    equality with the committed rows is contract-tested). The gate cells
    are hour-anchored like the ceiling; the head-sliver difference is
    bound-checked in tests (<= $5)."""
    C11 = C12.C11
    _, swaps, _, _ = C11.load_all()
    ts = swaps["timestamp"].to_numpy(np.int64)
    t_from, t_to = int(ts[0]), int(ts[-1]) + 1
    days = C11.window_days(swaps)
    out = {}
    for arm in C12.arms12():
        rec = {}
        for pn in C12.POINTS:
            with C11.chain_gas(pn):
                r = C11.simulate_streak(arm, t_from, t_to)
            pt = C11.ENVELOPE_BY_NAME[pn]
            months = {}
            for lab, b in sorted(r.months.items()):
                d = {}
                C11.add_bucket(d, b)
                months[lab] = C11.net_usd(d, pt)
            rec[pn] = {"net_usd": r.total.net_usd(pt),
                       "per_day_usd": r.total.per_day(pt),
                       "august_net_usd": months.get("2026-08", 0.0),
                       "months_net_usd": months}
        out[arm["label"]] = rec
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--budget-seconds", type=float, default=1e9)
    args = ap.parse_args()
    frozen = load_frozen()
    fin = (C12.read_json(FINAL_JSON) if FINAL_JSON.exists()
           else {"experiment": "E012", "phase": "final",
                 "policy": "frozen masks over the full window; three "
                           "coupled points; August = 2026-08 bucket",
                 "cells": {}})
    t0 = time.time()
    if "baselines" not in fin:
        fin["baselines"] = baselines()
        C12.write_json(FINAL_JSON, fin)
        print("baselines (always-in) done", flush=True)
    for cell in frozen["cells"]:
        key = f"{cell['candidate']}|{cell['arm']}"
        if key in fin["cells"]:
            continue
        tc = time.time()
        fin["cells"][key] = eval_frozen_cell(cell)
        C12.write_json(FINAL_JSON, fin)
        c = fin["cells"][key]["points"]["central"]
        print(f"{key:<38s} full ${c['per_day_usd']:+8.3f}/d "
              f"aug ${c['august_net_usd']:+8.2f} "
              f"held {fin['cells'][key]['held_frac_mask']*100:5.1f}% "
              f"in {c['n_streaks_simulated']:>3d} streaks "
              f"{time.time()-tc:.0f}s", flush=True)
        if time.time() - t0 > args.budget_seconds:
            print("budget reached; resume on next invocation")
            return 0
    print(f"final complete -> {FINAL_JSON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
