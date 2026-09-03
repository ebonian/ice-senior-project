#!/usr/bin/env python3
"""Derive per-chain month block ranges, timestamp anchors, and basefee samples.

    nix develop .#gate1 -c python backtest_model_server/e010/derive_blocks.py --chain mainnet

E005 reused E003's frozen Arbitrum month blocks; mainnet and Base need their
own, derived the same way E003 derived its: binary search on block timestamps
at the UTC month boundaries, so every venue is measured over the identical
UTC window (2026-05-01 -> 2026-08-28, end exclusive).

Anchors serve two purposes at once:
  - timestamp interpolation for swap rows (e003's method; T5 gate re-measures
    the error per pool against exact headers), and
  - the measured gas regime: each anchor header's baseFeePerGas is recorded,
    which is the pre-registered input to the E010 gas envelope (M004 §2.2).

Everything written here is committed (small JSONs/CSV): month_blocks.json,
<month>.anchors.json, basefees.csv.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path

import pandas as pd

E010 = Path(__file__).resolve().parent
sys.path.insert(0, str(E010))
import registry as R  # noqa: E402

sys.path.insert(0, str(E010.parent / "gate1"))
from engine.rpc import ArbRPC  # noqa: E402  (chain-agnostic JSON-RPC client)


def boundaries() -> list[tuple[str, int]]:
    """(label, epoch) for every month start in the window plus the exclusive
    window end."""
    t0 = pd.Timestamp(R.WINDOW_START, tz="UTC")
    t1 = pd.Timestamp(R.WINDOW_END, tz="UTC")
    out, cur = [], t0
    while cur < t1:
        out.append((cur.strftime("%Y-%m"), int(cur.timestamp())))
        cur = cur + pd.offsets.MonthBegin(1)
    out.append(("window_end", int(t1.timestamp())))
    return out


def headers_batched(rpc: ArbRPC, blocks: list[int], chunk: int = 200,
                    pace: float = 0.1) -> dict[int, dict]:
    out: dict[int, dict] = {}
    uniq = sorted(set(blocks))
    for i in range(0, len(uniq), chunk):
        part = uniq[i:i + chunk]
        res = rpc.batch([("eth_getBlockByNumber", [hex(b), False]) for b in part])
        for b, r in zip(part, res):
            out[b] = r
        if pace:
            time.sleep(pace)
        if (i // chunk) % 5 == 4:
            print(f"    headers {i + len(part)}/{len(uniq)}", flush=True)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--chain", required=True, choices=["mainnet", "base"])
    ap.add_argument("--rpc", default=None)
    args = ap.parse_args()

    ch = R.CHAINS[args.chain]
    rpc = ArbRPC(args.rpc or ch["state_rpc"][0])
    head = rpc.block_number()
    head_ts = rpc.block_timestamp(head)
    print(f"{args.chain}: head {head:,} @ {head_ts}")

    out_dir = R.BLOCKS_DIR / args.chain
    out_dir.mkdir(parents=True, exist_ok=True)
    mb_file = R.BLOCKS_DIR / f"{args.chain}.month_blocks.json"

    if mb_file.exists():
        mb = {k: tuple(v) for k, v in
              json.loads(mb_file.read_text())["month_blocks"].items()}
        print(f"  month blocks cached: {mb}")
    else:
        bts = boundaries()
        # conservative lower bound for the search: 2x the average block time
        span_s = head_ts - bts[0][1]
        avg_bt = 12.0 if args.chain == "mainnet" else 2.0
        lo0 = max(1, head - int(span_s / avg_bt * 2.5))
        marks = {}
        for label, epoch in bts:
            b = rpc.block_at_time(epoch, lo0, head)
            marks[label] = b
            print(f"  first block ts>={epoch} ({label}): {b:,} "
                  f"(ts {rpc.block_timestamp(b)})", flush=True)
        labels = [lb for lb, _ in bts[:-1]]
        mb = {}
        for i, lb in enumerate(labels):
            b0 = marks[lb]
            b1 = (marks[labels[i + 1]] if i + 1 < len(labels)
                  else marks["window_end"]) - 1
            mb[lb] = (b0, b1)
        mb_file.write_text(json.dumps({
            "chain": args.chain, "window": [R.WINDOW_START, R.WINDOW_END],
            "derived_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "rpc": rpc.url, "head_at_derivation": head,
            "month_blocks": {k: list(v) for k, v in mb.items()},
        }, indent=2))
        print(f"  wrote {mb_file}")

    stride = ch["anchor_stride"]
    bf_rows = []
    for label, (b0, b1) in mb.items():
        af = out_dir / f"{label}.anchors.json"
        if af.exists():
            print(f"  {label}: anchors cached")
            a = {int(k): int(v) for k, v in json.loads(af.read_text()).items()}
            bfc = out_dir / f"{label}.basefees.csv"
            if bfc.exists():
                continue
        blocks = list(range(b0, b1 + 1, stride))
        if blocks[-1] != b1:
            blocks.append(b1)
        print(f"  {label}: fetching {len(blocks)} anchor headers "
              f"({b0:,}..{b1:,} stride {stride})", flush=True)
        hd = headers_batched(rpc, blocks)
        a = {b: int(hd[b]["timestamp"], 16) for b in blocks}
        af.write_text(json.dumps({str(k): v for k, v in sorted(a.items())}))
        with open(out_dir / f"{label}.basefees.csv", "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["block", "timestamp", "base_fee_wei"])
            for b in blocks:
                w.writerow([b, a[b], int(hd[b]["baseFeePerGas"], 16)])
        print(f"  {label}: wrote {len(blocks)} anchors + basefees")

    # sanity: anchors monotone in ts
    for label in mb:
        a = {int(k): int(v) for k, v in
             json.loads((out_dir / f"{label}.anchors.json").read_text()).items()}
        ts = [a[b] for b in sorted(a)]
        assert all(t2 >= t1 for t1, t2 in zip(ts, ts[1:])), f"{label} non-monotone"
    print(f"done ({rpc.calls} rpc calls)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
