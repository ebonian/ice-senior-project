#!/usr/bin/env python3
"""Per-pool coverage verification for E010 fetches (e005's T-gates, chain-aware).

    nix develop .#gate1 -c python backtest_model_server/e010/coverage10.py [--slug S]

T1 chunk tiling, T2 participation (no zero-swap day, empty-hour runs <= 24h),
T3 independent refetch probes, T5 timestamp-interpolation error < 600s — all
imported unchanged from e005/coverage.py (same window, same thresholds); only
the RPC endpoint and the candidates file differ. Writes out/coverage.json.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

E010 = Path(__file__).resolve().parent
BMS = E010.parent
for p in (str(BMS / "gate1"), str(BMS / "e005")):
    if p not in sys.path:
        sys.path.insert(0, p)
sys.path.append(str(E010))

import registry as R  # noqa: E402
from engine.rpc import ArbRPC  # noqa: E402

# e003 and e005 both ship a coverage.py; load e005's by explicit file path so
# sys.path order cannot swap it (the shared-window constants are identical).
import importlib.util as _ilu  # noqa: E402

_spec = _ilu.spec_from_file_location("e005_coverage", BMS / "e005" / "coverage.py")
_cov5 = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_cov5)
chunk_tiling = _cov5.chunk_tiling
participation = _cov5.participation
refetch_probe = _cov5.refetch_probe
interp_probe = _cov5.interp_probe
daily_stats = _cov5.daily_stats


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", default=None)
    ap.add_argument("--probes", type=int, default=2)
    ap.add_argument("--probe-blocks", type=int, default=24_000)
    ap.add_argument("--interp-probes", type=int, default=25)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--skip-refetch", action="store_true")
    args = ap.parse_args()

    swap_root = E010 / "data" / "swaps"
    slugs = ([args.slug] if args.slug else
             sorted(d.name for d in swap_root.iterdir() if d.is_dir()))
    out_f = E010 / "out" / "coverage.json"
    out = json.loads(out_f.read_text()) if out_f.exists() else {"pools": {}}
    cands = {c["slug"]: c for c in
             json.loads((E010 / "out" / "candidates.json").read_text())["candidates"]}

    for slug in slugs:
        d = swap_root / slug
        metas = sorted(d.glob("*.meta.json"))
        if not metas:
            print(f"[{slug}] no fetched months, skipping")
            continue
        cand = cands[slug]
        rpc = ArbRPC(R.CHAINS[cand["chain"]]["logs_rpc"][0], pool=cand["address"])
        months, dfs = [], []
        for mp in metas:
            meta = json.loads(mp.read_text())
            df = pd.read_parquet(d / f"{meta['month']}.parquet")
            dfs.append(df)
            w0 = pd.Timestamp(meta["window_start_utc"])
            w1 = pd.Timestamp(meta["window_end_utc"])
            t1 = chunk_tiling(meta)
            t2 = participation(df, w0, w1)
            t3 = ({"skipped": True, "pass": None} if args.skip_refetch else
                  refetch_probe(rpc, df, meta, args.probes, args.probe_blocks,
                                args.seed))
            t5 = ({"skipped": True, "pass": None} if args.skip_refetch else
                  interp_probe(rpc, df, args.interp_probes, args.seed))
            ok = bool(t1["pass"] and t2["pass"] and (t3["pass"] is not False)
                      and (t5["pass"] is not False))
            months.append({"month": meta["month"], "n_swaps": int(len(df)),
                           "sha256": meta["sha256"],
                           "T1_chunk_tiling": t1, "T2_participation": t2,
                           "T3_refetch": t3, "T5_interpolation": t5,
                           "enters_race": ok})
            print(f"[{slug} {meta['month']}] swaps={len(df):>9,} "
                  f"hcov={t2['hour_coverage_pct']:7.3f}% "
                  f"run<={t2['max_contiguous_empty_hours']:>3d}h "
                  f"T1={'P' if t1['pass'] else 'F'} "
                  f"T2={'P' if t2['pass'] else 'F'} "
                  f"T3={'-' if t3['pass'] is None else ('P' if t3['pass'] else 'F')} "
                  f"T5={'-' if t5['pass'] is None else ('P' if t5['pass'] else 'F')}"
                  + (f" interp_max={t5.get('max_abs_error_s')}s"
                     if t5.get("max_abs_error_s") is not None else ""),
                  flush=True)
        rec = {"address": cand["address"], "chain": cand["chain"],
               "months": months,
               "all_months_enter_race": all(m["enters_race"] for m in months),
               "daily": daily_stats(dfs)}
        rec["data_status"] = "OK" if rec["all_months_enter_race"] else "DATA-FAIL"
        out["pools"][slug] = rec
        print(f"[{slug}] {rec['data_status']}  median/day="
              f"{rec['daily']['median_swaps_per_day']:.0f} "
              f"eligible={rec['daily']['eligible_median_ge_48']}", flush=True)

    out["seed"] = args.seed
    out_f.write_text(json.dumps(out, indent=2))
    print(f"wrote {out_f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
