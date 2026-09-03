#!/usr/bin/env python3
"""Fetch whole months of Swap events for one E010 candidate pool.

    nix develop .#gate1 -c python backtest_model_server/e010/fetch10.py \
        --slug m_weth_usdc_0p05 [--span 8000] [--rpc URL]

e005/fetch_pool_months.py, chain-parameterized:
  - month BLOCK RANGES come from the committed per-chain derivation
    (data/blocks/<chain>.month_blocks.json, derive_blocks.py) so every venue
    is measured over the identical UTC window;
  - timestamp ANCHORS are E010's own committed per-chain headers (same files
    that supply the gas envelope's basefees); interpolation error is
    re-measured per pool by coverage10's T5 gate, threshold unchanged (600s);
  - the logs RPC is the chain's `logs_rpc` (public archive-serving gateway,
    probed and recorded in registry.py); the adaptive splitter halves on
    rejection exactly as e005's did.

Output schema is byte-compatible with e005's:
data/swaps/<slug>/<YYYY-MM>.{raw.parquet,parquet,meta.json,blocks.json}
Columns: block_number, log_index, timestamp, price, vol_token1,
pool_liquidity, tick. Parquets are gitignored; blocks/meta (sha256) committed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

E010 = Path(__file__).resolve().parent
BMS = E010.parent
for p in (str(BMS / "gate1"), str(BMS / "e005")):
    if p not in sys.path:
        sys.path.insert(0, p)
sys.path.append(str(E010))

import registry as R  # noqa: E402
from engine.rpc import ArbRPC, TOPIC_SWAP, _i256, _u256, _i24, _words  # noqa: E402
from fetch_pool_months import sha256_file, get_swaps_adaptive  # noqa: E402


def month_bounds():
    t0 = pd.Timestamp(R.WINDOW_START, tz="UTC")
    t1 = pd.Timestamp(R.WINDOW_END, tz="UTC")
    out, cur = [], t0
    while cur < t1:
        nxt = cur + pd.offsets.MonthBegin(1)
        out.append((cur.strftime("%Y-%m"), cur, min(nxt, t1)))
        cur = nxt
    return out


def fetch_month(rpc: ArbRPC, cand: dict, out_dir: Path, label: str,
                w0: pd.Timestamp, w1: pd.Timestamp, span: int, pace: float,
                mb: dict) -> dict:
    if shutil.disk_usage("/home").free < 2 * 1024**3:
        raise SystemExit("ABORT: free disk below 2 GB (pre-registered)")
    pool = cand["address"]
    d0, d1 = cand["decimals0"], cand["decimals1"]
    blocks_f = out_dir / f"{label}.blocks.json"
    raw_f = out_dir / f"{label}.raw.parquet"
    pq = out_dir / f"{label}.parquet"
    mj = out_dir / f"{label}.meta.json"
    calls0 = rpc.calls
    t_start = time.time()

    b0, b1 = mb[label]
    br = json.loads(blocks_f.read_text()) if blocks_f.exists() else {
        "block_from": b0, "block_to": b1,
        "source": f"e010 derive_blocks {cand['chain']} month ranges"}

    if raw_f.exists() and "getlogs_chunks" in br:
        raw = pd.read_parquet(raw_f)
        print(f"[{cand['slug']} {label}] reusing {len(raw):,} cached logs", flush=True)
    else:
        print(f"[{cand['slug']} {label}] blocks {b0:,}..{b1:,} span {span:,}",
              flush=True)
        # Segment-level checkpointing: big months (Base) cannot fetch inside
        # one foreground call, so pull ~30-chunk segments, each persisted as
        # <label>.seg<i>.parquet + its chunk list; a re-run resumes at the
        # first missing segment and the merge is order-stable.
        seg_blocks = span * 30
        seg_bounds = list(range(b0, b1 + 1, seg_blocks))
        cols = ["block_number", "log_index", "amount1",
                "sqrt_price_x96", "liquidity", "tick"]
        astype = {"block_number": "int64", "log_index": "int32",
                  "amount1": "float64", "sqrt_price_x96": "float64",
                  "liquidity": "float64", "tick": "int32"}
        all_chunks: list[list[int]] = []
        parts = []
        for si, s0 in enumerate(seg_bounds):
            s1 = min(s0 + seg_blocks - 1, b1)
            seg_f = out_dir / f"{label}.seg{si:03d}.parquet"
            seg_cf = out_dir / f"{label}.seg{si:03d}.chunks.json"
            if seg_f.exists() and seg_cf.exists():
                parts.append(pd.read_parquet(seg_f))
                all_chunks.extend(json.loads(seg_cf.read_text()))
                continue
            rows, chunks = get_swaps_adaptive(rpc, pool, s0, s1, span, pace)
            seg = pd.DataFrame(rows, columns=cols).astype(astype)
            seg.to_parquet(seg_f, index=False, compression="zstd")
            seg_cf.write_text(json.dumps([[int(a), int(b)] for a, b in chunks]))
            parts.append(seg)
            all_chunks.extend([[int(a), int(b)] for a, b in chunks])
            print(f"    seg {si + 1}/{len(seg_bounds)} done "
                  f"({sum(len(p) for p in parts):,} swaps)", flush=True)
        raw = pd.concat(parts, ignore_index=True) if parts else \
            pd.DataFrame(columns=cols).astype(astype)
        raw = raw.sort_values(["block_number", "log_index"]).reset_index(drop=True)
        raw.to_parquet(raw_f, index=False, compression="zstd")
        br["getlogs_chunks"] = sorted(map(list, {tuple(c) for c in all_chunks}))
        br["getlogs_span"] = span
        blocks_f.write_text(json.dumps(br))
        for si in range(len(seg_bounds)):
            (out_dir / f"{label}.seg{si:03d}.parquet").unlink(missing_ok=True)
            (out_dir / f"{label}.seg{si:03d}.chunks.json").unlink(missing_ok=True)

    anchors = R.load_anchors(cand["chain"], label)
    ab = np.array(sorted(anchors), dtype=np.float64)
    at = np.array([anchors[int(b)] for b in ab], dtype=np.float64)
    ts = np.rint(np.interp(raw["block_number"].to_numpy(dtype=np.float64),
                           ab, at)).astype(np.int64)

    df = pd.DataFrame({
        "block_number": raw["block_number"].to_numpy(dtype=np.int64),
        "log_index": raw["log_index"].to_numpy(dtype=np.int32),
        "timestamp": ts,
        "price": (raw["sqrt_price_x96"].to_numpy() / (2 ** 96)) ** 2
                 * 10.0 ** (d0 - d1),
        "vol_token1": np.abs(raw["amount1"].to_numpy()) / 10.0 ** d1,
        "pool_liquidity": raw["liquidity"].to_numpy(dtype=np.float64),
        "tick": raw["tick"].to_numpy(dtype=np.int32),
    })
    df.to_parquet(pq, index=False, compression="zstd")

    tsx = pd.to_datetime(df["timestamp"], unit="s", utc=True)
    meta = {
        "slug": cand["slug"], "chain": cand["chain"], "pool": pool,
        "month": label, "decimals0": d0, "decimals1": d1,
        "window_start_utc": w0.isoformat(), "window_end_utc": w1.isoformat(),
        "block_from": int(b0), "block_to": int(b1), "n_blocks": int(b1 - b0 + 1),
        "n_swaps": int(len(df)),
        "getlogs_span": br.get("getlogs_span", span),
        "getlogs_chunks": br["getlogs_chunks"],
        "n_getlogs_chunks": len(br["getlogs_chunks"]),
        "anchors_source": f"e010/data/blocks/{cand['chain']}/{label}.anchors.json",
        "ts_stride_blocks": R.CHAINS[cand["chain"]]["anchor_stride"],
        "n_ts_anchors": len(anchors),
        "hours_expected": int((w1 - w0).total_seconds() // 3600),
        "hours_with_swaps": int(tsx.dt.floor("h").nunique()),
        "days_with_swaps": int(tsx.dt.floor("d").nunique()),
        "first_swap_utc": str(tsx.iloc[0]) if len(df) else None,
        "last_swap_utc": str(tsx.iloc[-1]) if len(df) else None,
        "rpc_host": rpc.url.split("/")[2], "rpc_calls": rpc.calls - calls0,
        "elapsed_s": round(time.time() - t_start, 1),
        "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
        "sha256": sha256_file(pq),
    }
    mj.write_text(json.dumps(meta, indent=2))
    print(f"[{cand['slug']} {label}] {len(df):,} swaps, "
          f"{meta['hours_with_swaps']}/{meta['hours_expected']} h, "
          f"{meta['rpc_calls']} calls, {meta['elapsed_s']}s", flush=True)
    return meta


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", required=True)
    ap.add_argument("--rpc", default=None)
    ap.add_argument("--span", type=int, default=8_000)
    ap.add_argument("--pace", type=float, default=0.15)
    ap.add_argument("--months", default=None,
                    help="comma-separated subset, e.g. 2026-05,2026-06")
    args = ap.parse_args()

    cands = json.loads((E010 / "out" / "candidates.json").read_text())["candidates"]
    cand = next((c for c in cands if c["slug"] == args.slug), None)
    if cand is None or cand.get("status") != "RESOLVED":
        raise SystemExit(f"slug {args.slug} not RESOLVED in candidates.json")
    mb = R.month_blocks(cand["chain"])

    out_dir = E010 / "data" / "swaps" / args.slug
    out_dir.mkdir(parents=True, exist_ok=True)
    gi = E010 / "data" / ".gitignore"
    if not gi.exists():
        gi.write_text("# Raw chain data, re-derivable from the committed month\n"
                      "# block ranges + e010 anchors + sha256 in meta.json.\n"
                      "*.parquet\n*.log\n")

    rpc = ArbRPC(args.rpc or R.CHAINS[cand["chain"]]["logs_rpc"][0],
                 pool=cand["address"])
    only = set(args.months.split(",")) if args.months else None
    metas = []
    for label, w0, w1 in month_bounds():
        if only and label not in only:
            continue
        mj = out_dir / f"{label}.meta.json"
        if mj.exists():
            m = json.loads(mj.read_text())
            print(f"[{args.slug} {label}] already assembled "
                  f"({m['n_swaps']:,} swaps), skipping", flush=True)
            metas.append(m)
            continue
        metas.append(fetch_month(rpc, cand, out_dir, label, w0, w1,
                                 args.span, args.pace, mb))
    print(f"done {args.slug}: {sum(m['n_swaps'] for m in metas):,} swaps, "
          f"{rpc.calls} rpc calls")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
