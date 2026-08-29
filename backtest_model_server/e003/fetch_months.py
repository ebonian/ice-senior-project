#!/usr/bin/env python3
"""Fetch whole months of ETH/USDC 0.05% Swap events from Arbitrum RPC.

    nix develop .#gate1 -c python backtest_model_server/e003/fetch_months.py \
        --start 2026-05-01 --end 2026-08-28

E003 races fixed-width rules over a multi-month window, and issue Y says the B2
daily archive has silent gaps (gate1/REPORT.md finding F3/D1: only 11 of 24
hours present in each trial window). So every swap this experiment sees comes
from `eth_getLogs`, which is complete by construction over the block range it is
handed — there is no "missing day" failure mode, only a truncated-response one,
and `coverage.py` tests for exactly that.

RESUMABILITY. Public `arb1.arbitrum.io/rpc` throttles sustained batch traffic
with HTTP 429, and the log pull is the expensive half (~10 min/month). So each
month runs as four checkpointed phases and re-running skips whatever is already
on disk:

    <YYYY-MM>.blocks.json   the month's block range          (2 binary searches)
    <YYYY-MM>.raw.parquet   every Swap log, no timestamps    (~215 getLogs calls)
    <YYYY-MM>.anchors.json  exact block timestamps on a stride (paced batches)
    <YYYY-MM>.parquet       the assembled frame + .meta.json

TIMESTAMPS. A header per swap-carrying block would be ~1M calls. Instead exact
headers are pulled every `--ts-stride` blocks and each swap is linearly
interpolated between its two bracketing anchors. The error this introduces is
not assumed — `coverage.py` re-pulls a random sample of exact headers and
reports the measured residual against the interpolated value.
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

E003 = Path(__file__).resolve().parent
GATE1 = E003.parent / "gate1"
sys.path.insert(0, str(GATE1))
from engine.rpc import ArbRPC, TOPIC_SWAP, _i256, _i24, _u256, _words  # noqa: E402

DEFAULT_RPC = "https://arb1.arbitrum.io/rpc"
SEC_PER_BLOCK = 0.247          # Arbitrum, from gate1/fetch_rpc_window.py
ANCHOR_BLOCK = 460836219
ANCHOR_TS = 1778371200         # 2026-05-09T16:00:00Z

SWAP_DIR = E003 / "data" / "swaps"


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def find_block_at(rpc: ArbRPC, target_ts: int) -> int:
    """First block at or after `target_ts`, seeded from a known (block, ts) pair.

    The upper bracket is clamped to the chain head: the last window this
    experiment uses ends about a day before now, and an unclamped widening step
    asks for a block that does not exist yet, which the node answers with null.
    """
    head = rpc.block_number()
    head_ts = rpc.block_timestamp(head)
    if target_ts > head_ts:
        raise ValueError(
            f"target {target_ts} is past the chain head {head} ({head_ts})")
    est = ANCHOR_BLOCK + int((target_ts - ANCHOR_TS) / SEC_PER_BLOCK)
    lo, hi = max(est - 200_000, 1), min(est + 200_000, head)
    for _ in range(8):
        if rpc.block_timestamp(lo) <= target_ts <= rpc.block_timestamp(hi):
            break
        span = hi - lo
        lo = max(lo - span, 1)
        hi = min(hi + span, head)
    return rpc.block_at_time(target_ts, lo, hi)


def paced_batch(rpc: ArbRPC, reqs: list, size: int, pace: float, tries: int = 8) -> list:
    """`rpc.batch` in small slices with backoff. The public endpoint 429s on
    200-wide header batches, and gate1's linear retry does not outlast a
    sustained throttle. gate1/engine is not modified; this wraps it."""
    out = []
    for i in range(0, len(reqs), size):
        part = reqs[i:i + size]
        for attempt in range(tries):
            try:
                out.extend(rpc.batch(part, tries=1))
                break
            except Exception as e:
                if attempt == tries - 1:
                    raise
                wait = min(2.0 * (2 ** attempt), 60.0)
                print(f"      throttled ({str(e)[:60]}), backing off {wait:.0f}s",
                      flush=True)
                time.sleep(wait)
        if pace:
            time.sleep(pace)
    return out


# --- phase 2: the logs -----------------------------------------------------
def get_swaps_adaptive(rpc: ArbRPC, b0: int, b1: int, span: int, pace: float):
    """Every Swap in [b0, b1], halving the span if a chunk is rejected.

    Returns rows plus the exact chunk boundaries queried, so coverage.py can
    assert the chunks tile [b0, b1] with no gap and no overlap. A silently
    truncated response is the one way an RPC pull can under-count, and it is the
    failure mode that assertion exists to catch.
    """
    rows: list[dict] = []
    chunks: list[tuple[int, int]] = []
    stack = [(b0, b1)]
    done = 0
    while stack:
        lo, hi = stack.pop(0)
        if hi - lo + 1 > span:
            mid = lo + span - 1
            stack.insert(0, (mid + 1, hi))
            hi = mid
        try:
            logs = rpc.call("eth_getLogs", [{
                "address": rpc.pool, "fromBlock": hex(lo), "toBlock": hex(hi),
                "topics": [TOPIC_SWAP],
            }])
        except Exception as e:
            if hi - lo < 200:
                raise
            msg = str(e).lower()
            if not any(k in msg for k in
                       ("limit", "too many", "range", "size", "timeout", "large", "429")):
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
        done += hi - lo + 1
        if len(chunks) % 25 == 0:
            print(f"    logs {done:,}/{b1 - b0 + 1:,} blocks, {len(rows):,} swaps",
                  flush=True)
        if pace:
            time.sleep(pace)
    return rows, sorted(chunks)


def fetch_month(rpc: ArbRPC, label: str, w0: pd.Timestamp, w1: pd.Timestamp,
                span: int, ts_stride: int, pace: float, batch_size: int,
                batch_pace: float) -> dict:
    SWAP_DIR.mkdir(parents=True, exist_ok=True)
    blocks_f = SWAP_DIR / f"{label}.blocks.json"
    raw_f = SWAP_DIR / f"{label}.raw.parquet"
    anch_f = SWAP_DIR / f"{label}.anchors.json"
    pq = SWAP_DIR / f"{label}.parquet"
    mj = SWAP_DIR / f"{label}.meta.json"

    calls0 = rpc.calls
    t_start = time.time()
    print(f"[{label}] {w0} -> {w1}", flush=True)

    # --- phase 1: block range ---------------------------------------------
    if blocks_f.exists():
        br = json.loads(blocks_f.read_text())
    else:
        b0 = find_block_at(rpc, int(w0.timestamp()))
        b1 = find_block_at(rpc, int(w1.timestamp())) - 1
        br = {"block_from": b0, "block_to": b1}
        blocks_f.write_text(json.dumps(br))
    b0, b1 = br["block_from"], br["block_to"]
    print(f"[{label}] blocks {b0:,} .. {b1:,}  ({b1 - b0 + 1:,} blocks)", flush=True)

    # --- phase 2: swap logs ------------------------------------------------
    if raw_f.exists() and "getlogs_chunks" in br:
        raw = pd.read_parquet(raw_f)
        chunks = [tuple(c) for c in br["getlogs_chunks"]]
        print(f"[{label}] reusing {len(raw):,} cached swap logs", flush=True)
    else:
        rows, chunks = get_swaps_adaptive(rpc, b0, b1, span, pace)
        raw = pd.DataFrame(rows).astype({
            "block_number": "int64", "log_index": "int32",
            "amount1": "float64", "sqrt_price_x96": "float64",
            "liquidity": "float64", "tick": "int32"})
        raw = raw.sort_values(["block_number", "log_index"]).reset_index(drop=True)
        raw.to_parquet(raw_f, index=False, compression="zstd")
        br["getlogs_chunks"] = [[int(a), int(b)] for a, b in chunks]
        br["getlogs_span"] = span
        blocks_f.write_text(json.dumps(br))
        print(f"[{label}] {len(raw):,} swaps in {len(chunks)} chunks "
              f"({time.time() - t_start:.0f}s)", flush=True)

    # --- phase 3: timestamp anchors, checkpointed --------------------------
    want = list(range(b0, b1 + 1, ts_stride))
    if want[-1] != b1:
        want.append(b1)
    anchors: dict[int, int] = {}
    if anch_f.exists():
        anchors = {int(k): int(v) for k, v in json.loads(anch_f.read_text()).items()}
    todo = [b for b in want if b not in anchors]
    if todo:
        print(f"[{label}] {len(todo):,} timestamp anchors to resolve "
              f"(stride {ts_stride:,}, {len(anchors):,} cached)", flush=True)
        STEP = batch_size * 20
        for i in range(0, len(todo), STEP):
            part = todo[i:i + STEP]
            res = paced_batch(rpc, [("eth_getBlockByNumber", [hex(b), False])
                                    for b in part], batch_size, batch_pace)
            for b, r in zip(part, res):
                anchors[b] = int(r["timestamp"], 16)
            anch_f.write_text(json.dumps({str(k): v for k, v in anchors.items()}))
            print(f"    anchors {min(i + STEP, len(todo)):,}/{len(todo):,}", flush=True)

    # --- phase 4: assemble -------------------------------------------------
    ab = np.array(sorted(anchors), dtype=np.float64)
    at = np.array([anchors[int(b)] for b in ab], dtype=np.float64)
    blocks = raw["block_number"].to_numpy(dtype=np.float64)
    ts = np.rint(np.interp(blocks, ab, at)).astype(np.int64)

    df = pd.DataFrame({
        "block_number": raw["block_number"].to_numpy(dtype=np.int64),
        "log_index": raw["log_index"].to_numpy(dtype=np.int32),
        "timestamp": ts,
        # Same derivation as gate1/replay_mode_a.load_window_swaps.
        "price": (raw["sqrt_price_x96"].to_numpy() / (2 ** 96)) ** 2 * 1e12,
        "volume_usd": np.abs(raw["amount1"].to_numpy()) / 1e6,
        "pool_liquidity": raw["liquidity"].to_numpy(dtype=np.float64),
        "tick": raw["tick"].to_numpy(dtype=np.int32),
    })
    df.to_parquet(pq, index=False, compression="zstd")

    tsx = pd.to_datetime(df["timestamp"], unit="s", utc=True)
    hours = tsx.dt.floor("h")
    expected_hours = int((w1 - w0).total_seconds() // 3600)
    meta = {
        "month": label,
        "window_start_utc": w0.isoformat(), "window_end_utc": w1.isoformat(),
        "block_from": int(b0), "block_to": int(b1), "n_blocks": int(b1 - b0 + 1),
        "n_swaps": int(len(df)),
        "getlogs_span": br.get("getlogs_span", span),
        "getlogs_chunks": br["getlogs_chunks"],
        "n_getlogs_chunks": len(br["getlogs_chunks"]),
        "ts_stride_blocks": ts_stride, "n_ts_anchors": len(anchors),
        "hours_expected": expected_hours,
        "hours_with_swaps": int(hours.nunique()),
        "first_swap_utc": str(tsx.iloc[0]) if len(df) else None,
        "last_swap_utc": str(tsx.iloc[-1]) if len(df) else None,
        "rpc_host": rpc.url.split("/")[2], "rpc_calls": rpc.calls - calls0,
        "elapsed_s": round(time.time() - t_start, 1),
        "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
        "sha256": sha256_file(pq), "pool": rpc.pool,
    }
    mj.write_text(json.dumps(meta, indent=2))
    print(f"[{label}] wrote {pq.name}  {len(df):,} swaps, "
          f"{meta['hours_with_swaps']}/{expected_hours} hours, "
          f"{meta['rpc_calls']} calls, {meta['elapsed_s']}s", flush=True)
    return meta


def month_bounds(start: str, end: str):
    """[(label, month_start, month_end_exclusive)], clipped to [start, end)."""
    t0, t1 = pd.Timestamp(start, tz="UTC"), pd.Timestamp(end, tz="UTC")
    out, cur = [], t0.normalize().replace(day=1)
    while cur < t1:
        nxt = cur + pd.offsets.MonthBegin(1)
        out.append((cur.strftime("%Y-%m"), max(cur, t0), min(nxt, t1)))
        cur = nxt
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-05-01")
    ap.add_argument("--end", default="2026-08-28", help="exclusive")
    ap.add_argument("--rpc", default=DEFAULT_RPC)
    ap.add_argument("--span", type=int, default=50_000, help="blocks per eth_getLogs")
    ap.add_argument("--ts-stride", type=int, default=2_000)
    ap.add_argument("--pace", type=float, default=0.0, help="sleep between getLogs")
    ap.add_argument("--batch-size", type=int, default=25,
                    help="headers per HTTP batch; the public endpoint 429s above ~50")
    ap.add_argument("--batch-pace", type=float, default=0.4)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    rpc = ArbRPC(args.rpc)
    metas = []
    for label, w0, w1 in month_bounds(args.start, args.end):
        mj = SWAP_DIR / f"{label}.meta.json"
        if mj.exists() and not args.force:
            print(f"[{label}] already assembled, skipping (--force to redo)", flush=True)
            metas.append(json.loads(mj.read_text()))
            continue
        metas.append(fetch_month(rpc, label, w0, w1, args.span, args.ts_stride,
                                 args.pace, args.batch_size, args.batch_pace))

    print(f"\ndone: {len(metas)} months, {sum(m['n_swaps'] for m in metas):,} swaps, "
          f"{rpc.calls} rpc calls")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
