#!/usr/bin/env python3
"""Fetch complete trial-window pool data from Arbitrum RPC.

    nix develop .#gate1 -c python backtest_model_server/gate1/fetch_rpc_window.py --trial 5

The B2 daily archive covers only 11 of the 24 hours in each trial window
(gate1/REPORT.md finding D1), so per-swap replay against B2 alone undercounts
fees by roughly half. This pulls the window from `eth_getLogs` instead, which
is complete by construction, plus the exact Mint/Burn/Collect logs for every
recorded action tx.

Writes, per trial, under gate1/data/rpc/T<n>/:
    swaps.parquet      every Swap event in the window, with block timestamps
    actions.json       decoded Mint/Burn/Collect per recorded tx hash
    meta.json          block anchors, call counts, provenance
"""

from __future__ import annotations

import argparse
import bisect
import csv
import glob
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from engine.b2 import read_env  # noqa: E402
from engine.rpc import ArbRPC  # noqa: E402

GATE1 = Path(__file__).resolve().parent
TRIALS_DIR = Path("/home/poon/developments/llaminet/bot/analysis/trials")

# Windows are the documented AUM windows (bot analysis/trials/<n>/output/data/summary.json).
WINDOWS = {
    4: ("2026-05-12T16:00:00Z", "2026-05-13T16:00:00Z"),
    5: ("2026-05-14T05:00:00Z", "2026-05-15T05:00:00Z"),
}
# Anchor from the strategy review's RPC probe; Arbitrum runs ~0.247 s/block.
ANCHOR_BLOCK = 460836219
ANCHOR_TS = 1778371200  # 2026-05-09T16:00:00Z, refined at runtime
SEC_PER_BLOCK = 0.247

DEFAULT_RPC = "https://arb1.arbitrum.io/rpc"


def parse_iso(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def load_actions(trial: int) -> list[dict]:
    f = glob.glob(str(TRIALS_DIR / str(trial) / "rebalance-history-*.csv"))[0]
    rows = sorted(
        csv.DictReader(open(f, encoding="utf-8-sig")), key=lambda r: r["timestamp"]
    )
    out = []
    for r in rows:
        if r["status"] == "executed_rebalance" and r["create_tx_hash"].strip():
            out.append(
                {
                    "kind": "mint",
                    "ts": r["timestamp"],
                    "tx": r["create_tx_hash"].strip(),
                    "tick_lower": r["applied_tick_lower"],
                    "tick_upper": r["applied_tick_upper"],
                    "accumulated_fees_usd": r["accumulated_fees_usd"],
                    "position_usd": r["position_usd"],
                    "wallet_usd": r["wallet_usd"],
                }
            )
        elif r["status"] == "executed_exit" and r["remove_tx_hashes"].strip():
            for tx in [t.strip() for t in r["remove_tx_hashes"].split(";") if t.strip()]:
                out.append(
                    {
                        "kind": "burn",
                        "ts": r["timestamp"],
                        "tx": tx,
                        "accumulated_fees_usd": r["accumulated_fees_usd"],
                        "position_usd": r["position_usd"],
                        "wallet_usd": r["wallet_usd"],
                    }
                )
    return out


def find_block_at(rpc: ArbRPC, target_ts: int, cache: dict) -> int:
    """Binary search for the first block at or after `target_ts`, tightly seeded."""
    est = ANCHOR_BLOCK + int((target_ts - cache["anchor_ts"]) / SEC_PER_BLOCK)
    lo, hi = est - 40_000, est + 40_000
    # Widen until the bracket actually contains the target.
    for _ in range(6):
        if rpc.block_timestamp(lo) <= target_ts <= rpc.block_timestamp(hi):
            break
        span = hi - lo
        lo -= span
        hi += span
    return rpc.block_at_time(target_ts, lo, hi)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trial", type=int, required=True, choices=[4, 5])
    ap.add_argument("--rpc", default=None, help="default: public arb1 (archive-capable)")
    ap.add_argument("--pad-hours", type=float, default=1.5,
                    help="extra span each side so cycle edges are never clipped")
    ap.add_argument("--reuse-edges", action="store_true",
                    help="reuse hour-boundary blocks from an existing meta.json "
                         "(they cost ~470 RPC calls and never change)")
    args = ap.parse_args()

    url = args.rpc or DEFAULT_RPC
    rpc = ArbRPC(url)
    out_dir = GATE1 / "data" / "rpc" / f"T{args.trial}"
    out_dir.mkdir(parents=True, exist_ok=True)

    w0, w1 = (parse_iso(x) for x in WINDOWS[args.trial])
    pad = pd.Timedelta(hours=args.pad_hours)
    f0, f1 = pd.Timestamp(w0) - pad, pd.Timestamp(w1) + pad
    print(f"T{args.trial} window {w0} -> {w1}  (fetch {f0} -> {f1})")
    print(f"rpc: {url.split('/')[2]}")

    cache = {"anchor_ts": rpc.block_timestamp(ANCHOR_BLOCK)}
    print(f"anchor block {ANCHOR_BLOCK} ts={cache['anchor_ts']} "
          f"({datetime.fromtimestamp(cache['anchor_ts'], timezone.utc)})")

    b0 = find_block_at(rpc, int(f0.timestamp()), cache)
    b1 = find_block_at(rpc, int(f1.timestamp()), cache)
    print(f"block range {b0} -> {b1}  ({b1-b0:,} blocks)")

    # --- receipts for every recorded action tx -----------------------------
    actions = load_actions(args.trial)
    print(f"recorded action txs: {len(actions)}")
    hashes = [a["tx"] for a in actions]
    receipts = {}
    for i in range(0, len(hashes), 20):
        part = hashes[i : i + 20]
        try:
            receipts.update(rpc.receipts(part))
        except Exception:
            for h in part:
                receipts[h.lower()] = rpc.receipt(h)
        time.sleep(0.2)

    decoded = []
    for a in actions:
        rcpt = receipts.get(a["tx"].lower())
        ev = rpc.pool_events_in_receipt(rcpt)
        blk = int(rcpt["blockNumber"], 16) if rcpt else None
        decoded.append({**a, "block": blk, "events": ev,
                        "status": rcpt.get("status") if rcpt else None})
        n = len(ev["mint"]) + len(ev["burn"]) + len(ev["collect"])
        print(f"  {a['ts'][:19]} {a['kind']:5s} blk={blk} "
              f"mint={len(ev['mint'])} burn={len(ev['burn'])} collect={len(ev['collect'])}"
              + ("  <-- NO POOL EVENTS" if n == 0 else ""))

    # --- every swap in the window ------------------------------------------
    t0 = time.time()
    swaps = rpc.get_swaps(b0, b1)
    print(f"swaps: {len(swaps):,} in {time.time()-t0:.1f}s")

    # --- hour boundaries, not per-swap headers ------------------------------
    # Cycle slicing uses the mint/burn block numbers from the receipts above, so
    # per-swap timestamps are never needed for the replay itself. Fetching a
    # header for each of ~15k swap-carrying blocks costs ~15k RPC calls; binary
    # searching the 25 hour boundaries costs ~300 and is exact where it matters.
    hour_edges = pd.date_range(f0.ceil("h"), f1.floor("h"), freq="h")
    meta_path = out_dir / "meta.json"
    cached_edges = None
    if args.reuse_edges and meta_path.exists():
        prev = json.loads(meta_path.read_text())
        if len(prev.get("hour_edge_blocks", [])) == len(hour_edges):
            cached_edges = prev["hour_edge_blocks"]
            print(f"reusing {len(cached_edges)} cached hour-boundary blocks")

    print(f"resolving {len(hour_edges)} hour-boundary blocks")
    t0 = time.time()
    edge_blocks: list[int] = list(cached_edges) if cached_edges else []
    for i, h in enumerate([] if cached_edges else hour_edges):
        target = int(h.timestamp())
        if edge_blocks:
            est = edge_blocks[-1] + int(3600 / SEC_PER_BLOCK)
            lo, hi = est - 4_000, est + 4_000
            if not (rpc.block_timestamp(lo) <= target <= rpc.block_timestamp(hi)):
                lo, hi = b0, b1 + 60_000
            blk = rpc.block_at_time(target, lo, hi)
        else:
            blk = find_block_at(rpc, target, cache)
        edge_blocks.append(blk)
    print(f"  boundaries done in {time.time()-t0:.1f}s ({rpc.calls} calls so far)")

    edge_ts = [int(h.timestamp()) for h in hour_edges]

    def approx_ts(block: int) -> int:
        """Interpolate a swap's timestamp between the two enclosing hour edges."""
        i = bisect.bisect_right(edge_blocks, block) - 1
        if i < 0:
            return edge_ts[0] - int((edge_blocks[0] - block) * SEC_PER_BLOCK)
        if i >= len(edge_blocks) - 1:
            return edge_ts[-1] + int((block - edge_blocks[-1]) * SEC_PER_BLOCK)
        b_lo, b_hi = edge_blocks[i], edge_blocks[i + 1]
        t_lo, t_hi = edge_ts[i], edge_ts[i + 1]
        if b_hi == b_lo:
            return t_lo
        return int(t_lo + (block - b_lo) * (t_hi - t_lo) / (b_hi - b_lo))

    rows = []
    for s in swaps:
        rows.append(
            {
                "block_number": s.block_number,
                "log_index": s.log_index,
                "timestamp": approx_ts(s.block_number),
                "tx_hash": s.tx_hash,
                "amount0": str(s.amount0),
                "amount1": str(s.amount1),
                "sqrt_price_x96": str(s.sqrt_price_x96),
                "liquidity": str(s.liquidity),
                "tick": s.tick,
                "sender": s.sender,
                "recipient": s.recipient,
            }
        )
    df = pd.DataFrame(rows)
    df.to_parquet(out_dir / "swaps.parquet", index=False)

    ts = pd.to_datetime(df["timestamp"], unit="s", utc=True)
    hours_in_window = ts[(ts >= pd.Timestamp(w0)) & (ts < pd.Timestamp(w1))].dt.floor("h").nunique()
    print(f"hours covered inside the 24h window: {hours_in_window}/24")

    meta = {
        "trial": args.trial,
        "window_start_utc": w0.isoformat(),
        "window_end_utc": w1.isoformat(),
        "fetch_start_utc": f0.isoformat(),
        "fetch_end_utc": f1.isoformat(),
        "block_from": b0,
        "block_to": b1,
        "n_swaps": len(df),
        "hours_covered_in_window": int(hours_in_window),
        "rpc_host": url.split("/")[2],
        "rpc_calls": rpc.calls,
        "hour_edge_blocks": edge_blocks,
        "hour_edge_ts": edge_ts,
        "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2))
    (out_dir / "actions.json").write_text(json.dumps(decoded, indent=2))
    print(f"wrote {out_dir}  ({rpc.calls} rpc calls)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
