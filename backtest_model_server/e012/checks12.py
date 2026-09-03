#!/usr/bin/env python3
"""E012 mandatory non-deciding checks (pre-registered):

    nix develop .#gate1 -c python backtest_model_server/e012/checks12.py

  - K15 wick honesty on every frozen candidate's held hours (top-10 swap
    share of held-hour fee weight vs the full-window reference).
  - Streak-length distributions per frozen candidate vs the same-arm
    oracle's; round-trip counts and switch-cost totals (the fragmentation
    measurement).
  - Tune-window baseline comparison: always-in evaluated on the tune slice
    per arm, and the count of grid cells beating it (the in-sample framing:
    the pre-registered zero-positive clause generalizes to "how many cells
    demonstrated positive GATING value in-sample").
  - August burst autopsy for each frozen cell: held/skipped state at the
    committed oracle's August skip episodes and at the window's worst
    stage-1 hours (mechanism evidence, judges nothing).
  - Funding-substitution (F2) runs only on SUPPORTED cells; if none, the
    check records why it did not run.

Output: out/checks_results.json.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

import common12 as C12
import gates12 as G12
import final12 as F12

C11 = C12.C11


def wick_for_mask(mask: np.ndarray, hs: np.ndarray) -> dict:
    _, swaps, _, _ = C11.load_all()
    vol = swaps["volume_usd"].to_numpy(np.float64)
    liq = swaps["pool_liquidity"].to_numpy(np.float64)
    weight = vol / liq
    ts = swaps["timestamp"].to_numpy(np.int64)
    held_hours = set(int(h) for h in hs[mask])
    in_held = np.array([((t // 3600) * 3600) in held_hours for t in ts])
    w_held = np.sort(weight[in_held])[::-1]
    w_all = np.sort(weight)[::-1]
    tot_h, tot_a = float(w_held.sum()), float(w_all.sum())
    return {
        "held_n_swaps": int(in_held.sum()),
        "held_top10_share": float(w_held[:10].sum() / tot_h) if tot_h else None,
        "held_top50_share": float(w_held[:50].sum() / tot_h) if tot_h else None,
        "full_top10_share": float(w_all[:10].sum() / tot_a),
    }


def main() -> int:
    frozen = F12.load_frozen()
    fin = C12.read_json(F12.FINAL_JSON)
    tr = C12.read_json(C12.OUT / "tune_results.json")
    hs, _ = C12.hours_and_closes()
    _, swaps, _, _ = C11.load_all()
    ts = swaps["timestamp"].to_numpy(np.int64)
    tune_days = tr["tune_days"]

    out = {"experiment": "E012", "part": "mandatory-checks"}

    # --- tune-window always-in per arm + cells beating it ------------------
    print("[tune-baseline] always-in on the tune slice, per arm")
    tune_base = {}
    mask_tune = np.ones(len(hs), dtype=bool)
    for arm in C12.arms12():
        res = C12.eval_mask(arm, mask_tune, hs, points=("central",),
                            t_max=C12.TUNE_END_EPOCH)
        net = res["points"]["central"]["net_usd"]
        tune_base[arm["label"]] = {"net_usd": net,
                                   "per_day_usd": net / tune_days}
        print(f"  {arm['label']:<26s} always-in tune "
              f"${net / tune_days:+7.3f}/d")
    beat = {lab: 0 for lab in C12.ARM_LABELS}
    for key, cell in tr["cells"].items():
        lab = cell["arm"]
        if (cell["central"]["per_day_usd"]
                > tune_base[lab]["per_day_usd"]):
            beat[lab] += 1
    n_arm = {lab: sum(1 for c in tr["cells"].values() if c["arm"] == lab)
             for lab in C12.ARM_LABELS}
    out["tune_baseline"] = {
        "always_in_tune": tune_base,
        "cells_beating_same_arm_always_in":
            {lab: f"{beat[lab]}/{n_arm[lab]}" for lab in C12.ARM_LABELS},
        "cells_positive_in_tune": int(sum(
            1 for c in tr["cells"].values()
            if c["central"]["per_day_usd"] > 0)),
        "n_cells": len(tr["cells"]),
    }
    print(f"  cells beating same-arm always-in in tune: {beat}")

    # --- oracle streak reference -------------------------------------------
    oracle = {}
    for lab in C12.ARM_LABELS:
        hrs = pd.read_csv(C11.OUT / f"stage1_hours_{lab}.csv")
        m = hrs["held_central"].to_numpy(bool)
        runs = C11.E6O.streaks_of(m)
        lens = [j - i + 1 for i, j in runs]
        oracle[lab] = {"mask": m, "n_streaks": len(runs),
                       "median_h": float(np.median(lens)),
                       "held_frac": float(m.mean())}

    # --- per frozen cell: wick, streaks, roundtrips, August autopsy --------
    aug_episodes = {}
    for lab in C12.ARM_LABELS:
        m = oracle[lab]["mask"]
        runs_skip = C11.E6O.streaks_of(~m)
        aug_episodes[lab] = [
            (int(hs[i]), int(hs[j]) + 3600) for i, j in runs_skip
            if hs[i] >= C12.TUNE_END_EPOCH]
    verdict_hrs = pd.read_csv(
        C11.OUT / "stage1_hours_arm_0.1pct_0.2pct_0.5pct.csv")
    pay = verdict_hrs["payoff_usd"].to_numpy()
    worst_idx = np.argsort(pay)[:10]

    cells_out = {}
    print("[cells] wick / streaks / roundtrips / August autopsy")
    for cell in frozen["cells"]:
        cid, lab = cell["candidate"], cell["arm"]
        key = f"{cid}|{lab}"
        cand = G12.CANDIDATES[cid]
        sig, _ = G12.signal_for(cand, cell["cfg"],
                                zstats=cell.get("har_zstats_tune"))
        mask = G12.build_mask(cand, cell["cfg"], sig,
                              cell["thresholds_abs"], hs)
        runs = C11.E6O.streaks_of(mask)
        lens = [j - i + 1 for i, j in runs]
        # oracle-episode coverage: fraction of each August oracle-skip
        # episode's hours that this cell also skips
        cover = []
        for (t0, t1) in aug_episodes[lab]:
            sel = (hs >= t0) & (hs < t1)
            cover.append(float((~mask[sel]).mean()) if sel.any() else None)
        held_at_worst = [bool(mask[i]) for i in worst_idx]
        wick = wick_for_mask(mask, hs)
        n_rt = len(runs)
        cells_out[key] = {
            "cfg": cell["cfg"],
            "wick": wick,
            "n_streaks": n_rt,
            "streak_hours": {"median": float(np.median(lens)),
                             "p90": float(np.percentile(lens, 90)),
                             "max": int(max(lens))} if lens else None,
            "oracle_ref": {k: oracle[lab][k]
                           for k in ("n_streaks", "median_h", "held_frac")},
            "held_frac": float(mask.mean()),
            "roundtrips": n_rt,
            "aug_oracle_episode_skip_coverage": cover,
            "held_at_10_worst_stage1_hours": held_at_worst,
        }
        print(f"  {key:<38s} wick top10 {wick['held_top10_share']:.4f} "
              f"(full {wick['full_top10_share']:.4f})  "
              f"{n_rt} streaks med {np.median(lens):.0f}h  "
              f"aug-episode skip coverage "
              f"{[None if c is None else round(c, 2) for c in cover]}")
    out["cells"] = cells_out
    out["notes_worst_hours"] = [
        {"utc": str(pd.Timestamp(int(hs[i]), unit='s', tz='UTC')),
         "stage1_payoff_usd": float(pay[i])} for i in worst_idx]

    # --- F2 funding substitution: only on SUPPORTED cells ------------------
    supported = [k for k, c in fin["cells"].items()
                 if (c["points"]["central"]["per_day_usd"]
                     >= C12.TARGET_10PCT
                     and c["points"]["central"]["august_net_usd"] > 0)]
    out["funding_substitution"] = {
        "ran": bool(supported),
        "reason": ("no cell met the SUPPORTED preconditions"
                   if not supported else None),
        "cells": supported,
    }

    C12.write_json(C12.OUT / "checks_results.json", out)
    print(f"wrote {C12.OUT / 'checks_results.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
