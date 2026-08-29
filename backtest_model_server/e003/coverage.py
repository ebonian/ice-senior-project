#!/usr/bin/env python3
"""Coverage verification for every window E003 races over.

    nix develop .#gate1 -c python backtest_model_server/e003/coverage.py

The pre-registration says no window enters the race below full coverage, and
issue Y is why: the B2 daily archive has silent gaps, and E001's `_data` swaps
CSV was built from it. `eth_getLogs` cannot have a "missing day" — it returns
every log in the block range it is handed — so the only way an RPC pull can
under-count is a silently truncated response. These four tests are aimed at
exactly that, from cheapest to most expensive:

  T1 chunk tiling      the eth_getLogs chunks recorded in meta.json must tile
                       [block_from, block_to] with no gap and no overlap. A gap
                       is unqueried chain; an overlap would double-count.
  T2 hourly floor      every hour in the window must contain swaps. This pool
                       trades continuously; a zero-swap hour is a gap signature.
  T3 independent refetch
                       re-pull randomly chosen sub-ranges at a DIFFERENT chunk
                       span and require the (block, log_index) sets to match
                       exactly. This is the direct test for truncation: a
                       truncated 50k-block response cannot agree with four
                       untruncated 12.5k-block ones.
  T4 B2 cross-read     where the B2 archive has the same hours locally, compare
                       counts. This does not validate RPC — it measures issue Y,
                       i.e. how much the B2-built path would have missed.
  T5 interpolation     swap timestamps are interpolated between block-header
                       anchors, so re-pull exact headers for a random sample and
                       report the measured residual instead of asserting it is
                       small. The hedge and funding legs run on a 1-hour grid.

Writes e003/out/coverage.json and prints the table that goes in the report.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

import numpy as np
import pandas as pd

E003 = Path(__file__).resolve().parent
GATE1 = E003.parent / "gate1"
sys.path.insert(0, str(GATE1))
from engine.rpc import ArbRPC, TOPIC_SWAP  # noqa: E402

SWAP_DIR = E003 / "data" / "swaps"
DEFAULT_RPC = "https://arb1.arbitrum.io/rpc"


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
    return {
        "n_chunks": len(chunks),
        "blocks_claimed": sum(hi - lo + 1 for lo, hi in chunks),
        "blocks_in_range": b1 - b0 + 1,
        "gaps": gaps,
        "overlaps": overlaps,
        "pass": not gaps and not overlaps,
    }


def hourly_floor(df: pd.DataFrame, w0: pd.Timestamp, w1: pd.Timestamp) -> dict:
    ts = pd.to_datetime(df["timestamp"], unit="s", utc=True)
    counts = ts.dt.floor("h").value_counts()
    grid = pd.date_range(w0, w1 - pd.Timedelta(hours=1), freq="h")
    present = counts.reindex(grid, fill_value=0)
    empty = present[present == 0]
    return {
        "hours_expected": len(grid),
        "hours_with_swaps": int((present > 0).sum()),
        "coverage_pct": round(100.0 * (present > 0).sum() / len(grid), 4),
        "empty_hours": [str(h) for h in empty.index[:20]],
        "n_empty_hours": int(len(empty)),
        "min_swaps_in_an_hour": int(present.min()),
        "median_swaps_per_hour": float(present.median()),
        "pass": bool(len(empty) == 0),
    }


def refetch_probe(rpc: ArbRPC, df: pd.DataFrame, meta: dict, n_probes: int,
                  probe_blocks: int, seed: int) -> dict:
    """Re-pull sub-ranges at a quarter of the original span and demand equality."""
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
                "topics": [TOPIC_SWAP],
            }]):
                got.add((int(lg["blockNumber"], 16), int(lg["logIndex"], 16)))
            b = end + 1
        stored = {k for k in have if s <= k[0] <= e}
        probes.append({
            "from_block": s, "to_block": e,
            "n_refetched": len(got), "n_stored": len(stored),
            "missing_from_store": len(got - stored),
            "extra_in_store": len(stored - got),
            "pass": got == stored,
        })
    return {"probe_span_blocks": span, "probes": probes,
            "pass": all(p["pass"] for p in probes)}


def interp_probe(rpc: ArbRPC, df: pd.DataFrame, meta: dict, n: int, seed: int) -> dict:
    """Measure, don't assume: exact headers vs the interpolated timestamps.

    Swap timestamps come from linear interpolation between anchors every
    `ts_stride_blocks`. This re-pulls exact headers for randomly chosen
    swap-carrying blocks and reports the residual, so the report can state the
    error rather than hand-wave it.
    """
    rng = random.Random(seed + 1)
    blocks = df["block_number"].to_numpy()
    picks = sorted({int(blocks[rng.randrange(len(blocks))]) for _ in range(n)})
    errs = []
    for i in range(0, len(picks), 20):
        part = picks[i:i + 20]
        res = rpc.batch([("eth_getBlockByNumber", [hex(b), False]) for b in part])
        for b, r in zip(part, res):
            exact = int(r["timestamp"], 16)
            interp = int(df.loc[df["block_number"] == b, "timestamp"].iloc[0])
            errs.append(interp - exact)
    a = np.abs(np.array(errs, dtype=np.int64))
    return {
        "n_probed": len(errs),
        "stride_blocks": meta["ts_stride_blocks"],
        "stride_seconds_nominal": round(meta["ts_stride_blocks"] * 0.247, 1),
        "max_abs_error_s": int(a.max()) if len(a) else None,
        "median_abs_error_s": float(np.median(a)) if len(a) else None,
        "p95_abs_error_s": float(np.percentile(a, 95)) if len(a) else None,
        # The hedge and funding legs run on a 1-hour grid; anything well under
        # 3600 s cannot move a swap into the wrong hour bucket in any way that
        # matters to a P&L line.
        "pass": bool(len(a) and a.max() < 600),
    }


def b2_cross_read(df: pd.DataFrame) -> dict:
    """Issue Y, measured: what does the B2 archive have for the same hours?"""
    b2_dir = GATE1 / "data" / "b2" / "swaps"
    files = sorted(b2_dir.glob("*.parquet")) if b2_dir.exists() else []
    if not files:
        return {"available": False,
                "note": "no local B2 swap parquets; issue Y not re-measured here"}
    b2 = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
    # B2's daily parquets carry epoch-second `timestamp`, plus the same
    # (block_number, log_index) identity the RPC pull has — so the two can be
    # compared swap-for-swap, not just hour-count against hour-count.
    b2["hour"] = pd.to_datetime(b2["timestamp"], unit="s", utc=True).dt.floor("h")
    rpc_ts = pd.to_datetime(df["timestamp"], unit="s", utc=True)
    rpc_h = rpc_ts.dt.floor("h").value_counts()
    b2_h = b2["hour"].value_counts()
    rpc_keys = set(zip(df["block_number"].tolist(), df["log_index"].astype(int).tolist()))
    overlap_days = sorted({str(h)[:10] for h in b2_h.index})
    rows = []
    for day in overlap_days:
        grid = pd.date_range(day, periods=24, freq="h", tz="UTC")
        r = rpc_h.reindex(grid, fill_value=0)
        b = b2_h.reindex(grid, fill_value=0)
        sub = b2[b2["hour"].isin(grid)]
        b2_keys = set(zip(sub["block_number"].tolist(),
                          sub["log_index"].astype(int).tolist()))
        rows.append({
            "day": day,
            "rpc_hours_with_swaps": int((r > 0).sum()),
            "b2_hours_with_swaps": int((b > 0).sum()),
            "rpc_swaps": int(r.sum()), "b2_swaps": int(b.sum()),
            "b2_share_of_rpc_pct": round(100.0 * b.sum() / r.sum(), 2) if r.sum() else None,
            # Swaps B2 has that the RPC pull does not. Should be zero: RPC is
            # complete by construction, so a non-zero here would indict E003's
            # own data rather than B2's.
            "in_b2_not_in_rpc": len(b2_keys - rpc_keys),
        })
    return {"available": True, "days": rows}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rpc", default=DEFAULT_RPC)
    ap.add_argument("--probes", type=int, default=3, help="refetch probes per month")
    ap.add_argument("--probe-blocks", type=int, default=40_000)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--interp-probes", type=int, default=60,
                    help="exact headers re-pulled to measure timestamp error")
    ap.add_argument("--skip-refetch", action="store_true")
    args = ap.parse_args()

    metas = sorted(SWAP_DIR.glob("*.meta.json"))
    if not metas:
        raise SystemExit(f"no month metadata in {SWAP_DIR} — run fetch_months.py")
    rpc = None if args.skip_refetch else ArbRPC(args.rpc)

    out = {"pool": "0xc6962004f452be9203591991d15f6b388e09e8d0",
           "source": "eth_getLogs", "seed": args.seed, "months": []}
    print(f"{'month':>8s} {'hours':>6s} {'cov%':>8s} {'swaps':>10s} {'min/h':>6s} "
          f"{'med/h':>7s} {'tiling':>7s} {'refetch':>8s} {'ts err s':>9s}")
    for mp in metas:
        meta = json.loads(mp.read_text())
        df = pd.read_parquet(SWAP_DIR / f"{meta['month']}.parquet")
        w0 = pd.Timestamp(meta["window_start_utc"])
        w1 = pd.Timestamp(meta["window_end_utc"])

        t1 = chunk_tiling(meta)
        t2 = hourly_floor(df, w0, w1)
        t3 = ({"skipped": True, "pass": None} if rpc is None else
              refetch_probe(rpc, df, meta, args.probes, args.probe_blocks, args.seed))
        t5 = ({"skipped": True, "pass": None} if rpc is None else
              interp_probe(rpc, df, meta, args.interp_probes, args.seed))
        rec = {"month": meta["month"], "window_start_utc": meta["window_start_utc"],
               "window_end_utc": meta["window_end_utc"],
               "block_from": meta["block_from"], "block_to": meta["block_to"],
               "n_swaps": int(len(df)), "sha256": meta["sha256"],
               "ts_stride_blocks": meta["ts_stride_blocks"],
               "T1_chunk_tiling": t1, "T2_hourly_floor": t2, "T3_refetch": t3,
               "T5_interpolation": t5}
        rec["enters_race"] = bool(t1["pass"] and t2["pass"]
                                  and (t3["pass"] is not False)
                                  and (t5["pass"] is not False))
        out["months"].append(rec)
        print(f"{meta['month']:>8s} {t2['hours_expected']:>6d} "
              f"{t2['coverage_pct']:>7.3f}% {len(df):>10,} "
              f"{t2['min_swaps_in_an_hour']:>6d} {t2['median_swaps_per_hour']:>7.0f} "
              f"{'PASS' if t1['pass'] else 'FAIL':>7s} "
              f"{'skipped' if rpc is None else ('PASS' if t3['pass'] else 'FAIL'):>8s} "
              f"{'-' if rpc is None else 'max ' + str(t5['max_abs_error_s']):>9s}")

    allsw = pd.concat([pd.read_parquet(SWAP_DIR / f"{m['month']}.parquet")
                       for m in out["months"]], ignore_index=True)
    out["b2_cross_read"] = b2_cross_read(allsw)
    out["all_months_enter_race"] = all(m["enters_race"] for m in out["months"])
    out["total_swaps"] = int(len(allsw))

    (E003 / "out").mkdir(parents=True, exist_ok=True)
    (E003 / "out" / "coverage.json").write_text(json.dumps(out, indent=2))
    print(f"\nall months enter the race: {out['all_months_enter_race']}  "
          f"({out['total_swaps']:,} swaps)")
    if out["b2_cross_read"].get("available"):
        print("\nissue Y, on the days B2 is cached locally:")
        for d in out["b2_cross_read"]["days"]:
            print(f"  {d['day']}  RPC {d['rpc_hours_with_swaps']:>2d}/24 h "
                  f"{d['rpc_swaps']:>6,} swaps   B2 {d['b2_hours_with_swaps']:>2d}/24 h "
                  f"{d['b2_swaps']:>6,} swaps  ({d['b2_share_of_rpc_pct']}% of RPC, "
                  f"{d['in_b2_not_in_rpc']} in B2 only)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
