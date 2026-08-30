#!/usr/bin/env python3
"""Fetch whole months of Swap events for one E005 candidate pool.

    nix develop .#gate1 -c python backtest_model_server/e005/fetch_pool_months.py \
        --slug wbtc_weth_0p05 [--span 200000]

E003's `fetch_months.py`, generalized to arbitrary pools, minus two phases it
no longer needs:

  - month BLOCK RANGES are frozen in `pools.MONTH_BLOCKS` (E003's own ranges,
    committed in e003/data/swaps/<month>.blocks.json), so every pool is
    measured over the identical chain window;
  - timestamp ANCHORS are reused from e003/data/swaps/<month>.anchors.json —
    block timestamps are pool-independent, and E003's coverage already
    measured the interpolation error (max < 600 s on a 1 h grid).

What remains per pool is the eth_getLogs pull, checkpointed per month and
resumable, with the chunk list recorded so coverage.py can assert tiling.
Candidate pools are far sparser than the control, so the default span is 4x
E003's; the adaptive splitter halves on rejection either way.

Output: data/swaps/<slug>/<YYYY-MM>.{raw.parquet,parquet,meta.json,blocks.json}
Columns: block_number, log_index, timestamp, price (human token1-per-token0),
vol_token1 (|amount1| / 10^d1), pool_liquidity, tick. USD conversion happens
in the race, at the hour grid, from the committed Binance marks.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

E005 = Path(__file__).resolve().parent
sys.path.insert(0, str(E005))
import pools as P  # noqa: E402

GATE1 = E005.parent / "gate1"
E003_SWAPS = E005.parent / "e003" / "data" / "swaps"
sys.path.insert(0, str(GATE1))
from engine.rpc import ArbRPC, TOPIC_SWAP, _i256, _u256, _i24, _words  # noqa: E402


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def get_swaps_adaptive(rpc: ArbRPC, pool: str, b0: int, b1: int, span: int,
                       pace: float):
    """Every Swap in [b0, b1] for `pool`; returns rows + exact chunk list."""
    rows: list[dict] = []
    chunks: list[tuple[int, int]] = []
    stack = [(b0, b1)]
    while stack:
        lo, hi = stack.pop(0)
        if hi - lo + 1 > span:
            mid = lo + span - 1
            stack.insert(0, (mid + 1, hi))
            hi = mid
        try:
            logs = rpc.call("eth_getLogs", [{
                "address": pool, "fromBlock": hex(lo), "toBlock": hex(hi),
                "topics": [TOPIC_SWAP]}])
        except Exception as e:
            if hi - lo < 5_000:
                raise
            msg = str(e).lower()
            if not any(k in msg for k in ("limit", "too many", "range", "size",
                                          "timeout", "large", "429", "results",
                                          "response", "batch")):
                raise
            mid = (lo + hi) // 2
            stack.insert(0, (mid + 1, hi))
            stack.insert(0, (lo, mid))
            time.sleep(2.0)
            continue
        for lg in logs:
            w = _words(lg["data"])
            rows.append({
                "block_number": int(lg["blockNumber"], 16),
                "log_index": int(lg["logIndex"], 16),
                "amount1": _i256(w[1]),
                "sqrt_price_x96": _u256(w[2]),
                "liquidity": _u256(w[3]),
                "tick": _i24(w[4]),
            })
        chunks.append((lo, hi))
        if len(chunks) % 25 == 0:
            print(f"    {len(chunks)} chunks, {len(rows):,} swaps", flush=True)
        if pace:
            time.sleep(pace)
    return rows, sorted(chunks)


def load_anchors(label: str) -> dict[int, int]:
    f = E003_SWAPS / f"{label}.anchors.json"
    return {int(k): int(v) for k, v in json.loads(f.read_text()).items()}


def fetch_month(rpc: ArbRPC, cand: dict, out_dir: Path, label: str,
                w0: pd.Timestamp, w1: pd.Timestamp, span: int, pace: float) -> dict:
    pool = cand["address"]
    d0, d1 = cand["decimals0"], cand["decimals1"]
    blocks_f = out_dir / f"{label}.blocks.json"
    raw_f = out_dir / f"{label}.raw.parquet"
    pq = out_dir / f"{label}.parquet"
    mj = out_dir / f"{label}.meta.json"
    calls0 = rpc.calls
    t_start = time.time()

    b0, b1 = P.MONTH_BLOCKS[label]
    br = json.loads(blocks_f.read_text()) if blocks_f.exists() else {
        "block_from": b0, "block_to": b1,
        "source": "e003 frozen month ranges (pools.MONTH_BLOCKS)"}

    if raw_f.exists() and "getlogs_chunks" in br:
        raw = pd.read_parquet(raw_f)
        chunks = [tuple(c) for c in br["getlogs_chunks"]]
        print(f"[{cand['slug']} {label}] reusing {len(raw):,} cached logs", flush=True)
    else:
        print(f"[{cand['slug']} {label}] blocks {b0:,}..{b1:,} span {span:,}",
              flush=True)
        rows, chunks = get_swaps_adaptive(rpc, pool, b0, b1, span, pace)
        raw = pd.DataFrame(rows, columns=["block_number", "log_index", "amount1",
                                          "sqrt_price_x96", "liquidity", "tick"])
        raw = raw.astype({"block_number": "int64", "log_index": "int32",
                          "amount1": "float64", "sqrt_price_x96": "float64",
                          "liquidity": "float64", "tick": "int32"})
        raw = raw.sort_values(["block_number", "log_index"]).reset_index(drop=True)
        raw.to_parquet(raw_f, index=False, compression="zstd")
        br["getlogs_chunks"] = [[int(a), int(b)] for a, b in chunks]
        br["getlogs_span"] = span
        blocks_f.write_text(json.dumps(br))

    anchors = load_anchors(label)
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
    hours = tsx.dt.floor("h")
    days = tsx.dt.floor("d")
    meta = {
        "slug": cand["slug"], "pool": pool, "month": label,
        "decimals0": d0, "decimals1": d1,
        "window_start_utc": w0.isoformat(), "window_end_utc": w1.isoformat(),
        "block_from": int(b0), "block_to": int(b1), "n_blocks": int(b1 - b0 + 1),
        "n_swaps": int(len(df)),
        "getlogs_span": br.get("getlogs_span", span),
        "getlogs_chunks": br["getlogs_chunks"],
        "n_getlogs_chunks": len(br["getlogs_chunks"]),
        "anchors_source": f"e003/data/swaps/{label}.anchors.json",
        "ts_stride_blocks": 2000, "n_ts_anchors": len(anchors),
        "hours_expected": int((w1 - w0).total_seconds() // 3600),
        "hours_with_swaps": int(hours.nunique()),
        "days_with_swaps": int(days.nunique()),
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


def month_bounds():
    t0 = pd.Timestamp(P.WINDOW_START, tz="UTC")
    t1 = pd.Timestamp(P.WINDOW_END, tz="UTC")
    out, cur = [], t0
    while cur < t1:
        nxt = cur + pd.offsets.MonthBegin(1)
        out.append((cur.strftime("%Y-%m"), cur, min(nxt, t1)))
        cur = nxt
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", required=True)
    ap.add_argument("--rpc", default=P.RPC_URL)
    ap.add_argument("--span", type=int, default=200_000)
    ap.add_argument("--pace", type=float, default=0.15)
    args = ap.parse_args()

    cands = json.loads((E005 / "out" / "candidates.json").read_text())["candidates"]
    cand = next((c for c in cands if c["slug"] == args.slug), None)
    if cand is None or cand.get("status") not in ("RESOLVED",):
        raise SystemExit(f"slug {args.slug} not RESOLVED in candidates.json")

    out_dir = E005 / "data" / "swaps" / args.slug
    out_dir.mkdir(parents=True, exist_ok=True)
    gi = E005 / "data" / ".gitignore"
    if not gi.exists():
        gi.write_text("# Raw chain data, re-derivable from the committed month\n"
                      "# block ranges + e003 anchors + sha256 in meta.json.\n"
                      "*.parquet\n*.log\n")

    rpc = ArbRPC(args.rpc, pool=cand["address"])
    metas = []
    for label, w0, w1 in month_bounds():
        mj = out_dir / f"{label}.meta.json"
        if mj.exists():
            m = json.loads(mj.read_text())
            print(f"[{args.slug} {label}] already assembled "
                  f"({m['n_swaps']:,} swaps), skipping", flush=True)
            metas.append(m)
            continue
        metas.append(fetch_month(rpc, cand, out_dir, label, w0, w1,
                                 args.span, args.pace))
    print(f"done {args.slug}: {sum(m['n_swaps'] for m in metas):,} swaps, "
          f"{rpc.calls} rpc calls")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
