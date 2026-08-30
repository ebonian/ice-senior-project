#!/usr/bin/env python3
"""Per-pool coverage verification for every E005 candidate fetch.

    nix develop .#gate1 -c python backtest_model_server/e005/coverage.py [--slug S]

E003's four RPC-truncation gates, generalized per pool:

  T1 chunk tiling     unchanged — recorded eth_getLogs chunks must tile the
                      month's block range with no gap and no overlap.
  T2 participation    E003's "every hour has swaps" floor is a property of a
                      3.4M-swap pool, not of the fetch. A sparse-but-eligible
                      pool legitimately has quiet hours, so the per-pool
                      generalization is: no zero-swap DAY, and no contiguous
                      empty-hour run longer than 24 h. A fetch gap shows up as
                      a long contiguous silence against the pool's own
                      baseline; scattered quiet hours do not.
  T3 refetch probes   unchanged — random sub-ranges re-pulled at a quarter of
                      the original span must match the stored (block,
                      log_index) set exactly.
  T5 interpolation    timestamps interpolate between e003's committed anchors
                      (block timestamps are pool-independent). Re-measured
                      here on each pool's own swap blocks anyway, because the
                      gate is pre-registered per pool. Threshold: max < 600 s
                      on a 1 h grid, as in E003.

Failure on any gate marks the pool DATA-FAIL (recorded, not silently dropped).
Also computes the per-day swap distribution the eligibility gate needs
(median over ALL window days, zero-swap days included).

Writes out/coverage.json.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

import numpy as np
import pandas as pd

E005 = Path(__file__).resolve().parent
sys.path.insert(0, str(E005))
import pools as P  # noqa: E402

GATE1 = E005.parent / "gate1"
sys.path.insert(0, str(GATE1))
from engine.rpc import ArbRPC, TOPIC_SWAP  # noqa: E402


def chunk_tiling(meta: dict) -> dict:
    chunks = sorted(tuple(c) for c in meta["getlogs_chunks"])
    b0, b1 = meta["block_from"], meta["block_to"]
    gaps, overlaps = [], []
    cur = b0
    for lo, hi in chunks:
        if lo > cur:
            gaps.append([cur, lo - 1])
        elif lo < cur:
            overlaps.append([lo, min(hi, cur - 1)])
        cur = max(cur, hi + 1)
    if cur <= b1:
        gaps.append([cur, b1])
    return {"n_chunks": len(chunks),
            "blocks_claimed": sum(hi - lo + 1 for lo, hi in chunks),
            "blocks_in_range": b1 - b0 + 1,
            "gaps": gaps, "overlaps": overlaps,
            "pass": not gaps and not overlaps}


def participation(df: pd.DataFrame, w0: pd.Timestamp, w1: pd.Timestamp) -> dict:
    ts = pd.to_datetime(df["timestamp"], unit="s", utc=True)
    hgrid = pd.date_range(w0, w1 - pd.Timedelta(hours=1), freq="h")
    hcounts = ts.dt.floor("h").value_counts().reindex(hgrid, fill_value=0)
    dgrid = pd.date_range(w0, w1 - pd.Timedelta(days=1), freq="d")
    dcounts = ts.dt.floor("d").value_counts().reindex(dgrid, fill_value=0)
    empty = (hcounts == 0).to_numpy()
    runs, cur = [], 0
    for e in empty:
        cur = cur + 1 if e else 0
        runs.append(cur)
    max_run = max(runs) if runs else 0
    return {"hours_expected": len(hgrid),
            "hours_with_swaps": int((hcounts > 0).sum()),
            "hour_coverage_pct": round(100.0 * (hcounts > 0).mean(), 3),
            "n_empty_hours": int(empty.sum()),
            "max_contiguous_empty_hours": int(max_run),
            "zero_swap_days": [str(d.date()) for d in dcounts[dcounts == 0].index],
            "n_zero_swap_days": int((dcounts == 0).sum()),
            "pass": bool((dcounts == 0).sum() == 0 and max_run <= 24)}


def refetch_probe(rpc: ArbRPC, df: pd.DataFrame, meta: dict, n_probes: int,
                  probe_blocks: int, seed: int) -> dict:
    rng = random.Random(seed)
    b0, b1 = meta["block_from"], meta["block_to"]
    span = max(meta["getlogs_span"] // 4, 1_000)
    have = set(zip(df["block_number"].tolist(), df["log_index"].tolist()))
    probes = []
    for _ in range(n_probes):
        s = rng.randint(b0, max(b0, b1 - probe_blocks))
        e = min(s + probe_blocks - 1, b1)
        got = set()
        b = s
        while b <= e:
            end = min(b + span - 1, e)
            for lg in rpc.call("eth_getLogs", [{
                    "address": rpc.pool, "fromBlock": hex(b), "toBlock": hex(end),
                    "topics": [TOPIC_SWAP]}]):
                got.add((int(lg["blockNumber"], 16), int(lg["logIndex"], 16)))
            b = end + 1
        stored = {k for k in have if s <= k[0] <= e}
        probes.append({"from_block": s, "to_block": e,
                       "n_refetched": len(got), "n_stored": len(stored),
                       "missing_from_store": len(got - stored),
                       "extra_in_store": len(stored - got),
                       "pass": got == stored})
    return {"probe_span_blocks": span, "probes": probes,
            "pass": all(p["pass"] for p in probes)}


def interp_probe(rpc: ArbRPC, df: pd.DataFrame, n: int, seed: int) -> dict:
    if len(df) == 0:
        return {"n_probed": 0, "pass": None}
    rng = random.Random(seed + 1)
    blocks = df["block_number"].to_numpy()
    picks = sorted({int(blocks[rng.randrange(len(blocks))]) for _ in range(n)})
    errs = []
    import time
    for i in range(0, len(picks), 20):
        part = picks[i:i + 20]
        for attempt in range(6):
            try:
                res = rpc.batch([("eth_getBlockByNumber", [hex(b), False])
                                 for b in part], tries=2)
                break
            except Exception:
                if attempt == 5:
                    raise
                time.sleep(30.0 * (attempt + 1))   # outlast a sustained 429
        for b, r in zip(part, res):
            exact = int(r["timestamp"], 16)
            interp = int(df.loc[df["block_number"] == b, "timestamp"].iloc[0])
            errs.append(interp - exact)
    a = np.abs(np.array(errs, dtype=np.int64))
    return {"n_probed": len(errs),
            "max_abs_error_s": int(a.max()) if len(a) else None,
            "p95_abs_error_s": float(np.percentile(a, 95)) if len(a) else None,
            "pass": bool(len(a) and a.max() < 600)}


def daily_stats(dfs: list[pd.DataFrame]) -> dict:
    df = pd.concat(dfs, ignore_index=True)
    ts = pd.to_datetime(df["timestamp"], unit="s", utc=True)
    w0 = pd.Timestamp(P.WINDOW_START, tz="UTC")
    w1 = pd.Timestamp(P.WINDOW_END, tz="UTC")
    dgrid = pd.date_range(w0, w1 - pd.Timedelta(days=1), freq="d")
    d = ts.dt.floor("d").value_counts().reindex(dgrid, fill_value=0)
    monthly = ts.dt.strftime("%Y-%m").value_counts().sort_index()
    return {"n_swaps": int(len(df)),
            "median_swaps_per_day": float(d.median()),
            "min_swaps_per_day": int(d.min()),
            "p10_swaps_per_day": float(d.quantile(0.10)),
            "monthly_swap_counts": {k: int(v) for k, v in monthly.items()},
            "eligible_median_ge_48": bool(d.median() >= P.MIN_MEDIAN_SWAPS_PER_DAY)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", default=None, help="one pool (default: all fetched)")
    ap.add_argument("--rpc", default=P.RPC_URL)
    ap.add_argument("--probes", type=int, default=2, help="refetch probes per month")
    ap.add_argument("--probe-blocks", type=int, default=60_000)
    ap.add_argument("--interp-probes", type=int, default=25, help="per month")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--skip-refetch", action="store_true")
    args = ap.parse_args()

    swap_root = E005 / "data" / "swaps"
    slugs = ([args.slug] if args.slug else
             sorted(d.name for d in swap_root.iterdir() if d.is_dir()))
    out_f = E005 / "out" / "coverage.json"
    out = json.loads(out_f.read_text()) if out_f.exists() else {"pools": {}}
    cands = {c["slug"]: c for c in
             json.loads((E005 / "out" / "candidates.json").read_text())["candidates"]}

    for slug in slugs:
        d = swap_root / slug
        metas = sorted(d.glob("*.meta.json"))
        if not metas:
            print(f"[{slug}] no fetched months, skipping")
            continue
        rpc = ArbRPC(args.rpc, pool=cands[slug]["address"])
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
                  f"hcov={t2['hour_coverage_pct']:7.3f}% run<={t2['max_contiguous_empty_hours']:>3d}h "
                  f"T1={'P' if t1['pass'] else 'F'} "
                  f"T2={'P' if t2['pass'] else 'F'} "
                  f"T3={'-' if t3['pass'] is None else ('P' if t3['pass'] else 'F')} "
                  f"T5={'-' if t5['pass'] is None else ('P' if t5['pass'] else 'F')}",
                  flush=True)
        rec = {"address": cands[slug]["address"], "months": months,
               "all_months_enter_race": all(m["enters_race"] for m in months),
               "daily": daily_stats(dfs)}
        rec["data_status"] = ("OK" if rec["all_months_enter_race"] else "DATA-FAIL")
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
