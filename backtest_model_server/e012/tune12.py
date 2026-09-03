#!/usr/bin/env python3
"""E012 tune phase — every grid cell, stage-2 exact, TUNE WINDOW ONLY.

    nix develop .#gate1 -c python backtest_model_server/e012/tune12.py [--budget-seconds N] [--freeze]

Tune slice: 2026-05-01 → 2026-08-01 (exclusive). The evaluator raises on
any simulated hour at or past the boundary (common12.eval_mask); a held
run open at the boundary is force-exited there and charged the exit
(run_streaks always books the exit at slice end) — identical convention
for every config.

Checkpoints out/tune_results.json after every cell; identical masks are
served from out/eval_cache.json (exact evaluator outputs keyed by mask
hash — determinism contract re-runs bypass it). --freeze selects the best
config per candidate x arm by tune central $/day (grid order breaks ties)
and writes out/params_frozen.json in one atomic write. EVERY grid point's
result is committed — the zero-positive-tune-configs framing needs the
whole surface.
"""

from __future__ import annotations

import argparse
import time

import numpy as np

import common12 as C12
import gates12 as G12

TUNE_JSON = C12.OUT / "tune_results.json"
CACHE_JSON = C12.OUT / "eval_cache.json"
FROZEN_JSON = C12.OUT / "params_frozen.json"


def tune_days() -> float:
    _, swaps, _, _ = C12.C11.load_all()
    ts0 = int(swaps["timestamp"].to_numpy()[0])
    return (C12.TUNE_END_EPOCH - ts0) / 86400.0


def cell_key(cid: str, arm_label: str, cfg: dict) -> str:
    return f"{cid}|{arm_label}|{G12.cfg_label(cfg)}"


def all_cells():
    for cid, cand in G12.CANDIDATES.items():
        for arm in C12.arms12():
            for cfg in cand["grid"]:
                yield cid, cand, arm, cfg


def eval_cell(cid: str, cand: dict, arm: dict, cfg: dict,
              cache: dict | None) -> dict:
    hs, _ = C12.hours_and_closes()
    sig, zstats = G12.signal_for(cand, cfg)
    thr = G12.thresholds_from_tune(cand, cfg, sig)
    mask = G12.build_mask(cand, cfg, sig, thr, hs)
    ck = C12.mask_key(arm["label"], mask & (hs < C12.TUNE_END_EPOCH),
                      C12.TUNE_END_EPOCH, ("central",))
    if cache is not None and ck in cache:
        rec = cache[ck]
    else:
        res = C12.eval_mask(arm, mask, hs, points=("central",),
                            t_max=C12.TUNE_END_EPOCH)
        c = res["points"]["central"]
        rec = {k: c[k] for k in
               ("net_usd", "n_streaks_simulated", "held_hours_simulated",
                "n_recenters", "max_lp_value_abs_gap_usd")}
        rec["n_streaks_selected"] = res["n_streaks"]
        rec["held_hours_mask_tune"] = int(
            (mask & (hs < C12.TUNE_END_EPOCH)).sum())
        if cache is not None:
            cache[ck] = rec
    days = tune_days()
    out = {
        "candidate": cid, "arm": arm["label"], "cfg": cfg,
        "thresholds_abs": thr,
        "central": dict(rec, per_day_usd=rec["net_usd"] / days),
    }
    if zstats is not None:
        out["har_zstats_tune"] = zstats
    return out


def eval_cell_by_key(key: str) -> dict:
    """Cache-free re-evaluation of one cell (determinism contract)."""
    cid, arm_label, _ = key.split("|", 2)
    cand = G12.CANDIDATES[cid]
    arm = next(a for a in C12.arms12() if a["label"] == arm_label)
    cfg = next(c for c in cand["grid"]
               if cell_key(cid, arm_label, c) == key)
    return eval_cell(cid, cand, arm, cfg, cache=None)


def freeze() -> None:
    tr = C12.read_json(TUNE_JSON)
    cells = tr["cells"]
    want = sum(len(c["grid"]) for c in G12.CANDIDATES.values()) * 2
    if len(cells) != want:
        raise RuntimeError(f"tune incomplete: {len(cells)}/{want} cells")
    frozen = []
    for cid, cand in G12.CANDIDATES.items():
        for arm_label in C12.ARM_LABELS:
            best = None
            for cfg in cand["grid"]:            # grid order breaks ties
                cell = cells[cell_key(cid, arm_label, cfg)]
                if (best is None or cell["central"]["per_day_usd"]
                        > best["central"]["per_day_usd"]):
                    best = cell
            frozen.append({
                "candidate": cid, "arm": arm_label, "cfg": best["cfg"],
                "thresholds_abs": best["thresholds_abs"],
                **({"har_zstats_tune": best["har_zstats_tune"]}
                   if "har_zstats_tune" in best else {}),
                "tune": best["central"],
            })
    C12.write_json(FROZEN_JSON, {
        "experiment": "E012", "phase": "params-frozen",
        "tune_window": ["2026-05-01", "2026-08-01"],
        "tune_days": tune_days(),
        "selection": "max tune central $/day per candidate x arm; "
                     "grid order breaks ties",
        "cells": frozen,
    })
    print(f"froze {len(frozen)} cells -> {FROZEN_JSON}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--budget-seconds", type=float, default=1e9)
    ap.add_argument("--freeze", action="store_true")
    args = ap.parse_args()
    if args.freeze:
        freeze()
        return 0

    C12.OUT.mkdir(parents=True, exist_ok=True)
    tr = (C12.read_json(TUNE_JSON) if TUNE_JSON.exists()
          else {"experiment": "E012", "phase": "tune",
                "tune_window": ["2026-05-01", "2026-08-01"],
                "tune_days": tune_days(), "cells": {}})
    cache = C12.read_json(CACHE_JSON) if CACHE_JSON.exists() else {}
    t0 = time.time()
    todo = [(cid, cand, arm, cfg) for cid, cand, arm, cfg in all_cells()
            if cell_key(cid, arm["label"], cfg) not in tr["cells"]]
    print(f"{len(todo)} cells to go ({len(tr['cells'])} done)")
    for cid, cand, arm, cfg in todo:
        key = cell_key(cid, arm["label"], cfg)
        tc = time.time()
        cell = eval_cell(cid, cand, arm, cfg, cache)
        tr["cells"][key] = cell
        C12.write_json(TUNE_JSON, tr)
        C12.write_json(CACHE_JSON, cache)
        c = cell["central"]
        print(f"{key:<48s} ${c['per_day_usd']:+8.3f}/d "
              f"held {cell['central']['held_hours_mask_tune']:>4d}h "
              f"in {c['n_streaks_simulated']:>3d} streaks "
              f"{time.time()-tc:.0f}s", flush=True)
        if time.time() - t0 > args.budget_seconds:
            print(f"budget reached; {len(todo)} remaining cells resume "
                  f"on next invocation")
            return 0
    print("tune complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
