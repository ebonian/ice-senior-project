#!/usr/bin/env python3
"""E009 companion L — descriptive LP-leg durability sketch (non-deciding).

    nix develop .#gate1 -c python backtest_model_server/e009/lp_leg_sketch.py

Extends the wstETH/WETH 0.01% fee-flow observation back to 2026-01 with a
**volume proxy**, not the full E005 fee engine: monthly proxy fees =
month volume (USD) x fee tier x LP fee share x E005's full-window implied
liquidity share (derived below from committed numbers, not retyped). The
proxy is validated against E005's four committed monthly fee cells first;
the January–April months are then fetched as raw Swap logs (public RPC,
checkpointed per month, resumable). No anchors, no parquets — monthly
totals only, so month boundaries are block bounds from timestamp bisection.

This is a sketch: it cannot see in-range fraction or share drift, and it
decides nothing (E009 prereg, companion L).
"""

from __future__ import annotations

import csv
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

E009 = Path(__file__).resolve().parent
BMS = E009.parent
sys.path.insert(0, str(BMS / "gate1"))
sys.path.insert(0, str(BMS / "e005"))

from engine.rpc import ArbRPC  # noqa: E402

POOL = "0x35218a1cbac5bbc3e57fd9bd38219d37571b3537"  # wstETH/WETH 0.01%
RPC_URL = "https://arb1.arbitrum.io/rpc"
FEE_TIER = 0.0001
LP_FEE_SHARE = 0.75
MAY_BLOCK_FROM = 458_085_624   # committed: e005 swaps/wsteth 2026-05.meta.json
OUT = E009 / "out" / "lp_leg_sketch.json"

E005_RESULTS = (BMS / "e005" / "out" / "wsteth_weth_0p01" / "lag1h_rh1h"
                / "results.json")
E005_SWAPS = BMS / "e005" / "data" / "swaps" / "wsteth_weth_0p01"

MONTHS = ["2026-01", "2026-02", "2026-03", "2026-04"]


def monthly_eth_price() -> dict[str, float]:
    """Monthly mean close from the committed e009 daily klines."""
    acc: dict[str, list[float]] = {}
    with open(E009 / "data" / "binance_ethusdt_1d.csv") as f:
        for r in csv.DictReader(f):
            m = r["iso_utc"][:7]
            acc.setdefault(m, []).append(float(r["close"]))
    return {m: sum(v) / len(v) for m, v in acc.items()}


def implied_share() -> tuple[float, dict]:
    """E005's full-window fee credit / (in-range volume x tier x lp share)."""
    j = json.loads(E005_RESULTS.read_text())
    arm = next(a for a in j["arms"] if a["arm"] == "arm_0.1pct")
    tot = arm["total"]
    share = tot["lp_fees_usd"] / (tot["volume_in_range_usd"] * FEE_TIER
                                  * LP_FEE_SHARE)
    return share, {m: b for m, b in arm["months"].items()}


def validate_proxy(share: float, cells: dict, px: dict) -> dict:
    """Proxy vs committed monthly fee cells, from committed parquets."""
    import pandas as pd
    out = {}
    for m in ["2026-05", "2026-06", "2026-07", "2026-08"]:
        df = pd.read_parquet(E005_SWAPS / f"{m}.parquet")
        vol_eth = float(df["vol_token1"].sum())
        vol_usd = vol_eth * px[m]
        proxy = vol_usd * FEE_TIER * LP_FEE_SHARE * share
        committed = cells[m]["lp_fees_usd"]
        out[m] = {"n_swaps": int(len(df)), "vol_eth": vol_eth,
                  "vol_usd": vol_usd, "proxy_fees_usd": proxy,
                  "committed_fees_usd": committed,
                  "proxy_over_committed": proxy / committed}
    return out


def fetch_month_volume(rpc: ArbRPC, b0: int, b1: int, label: str,
                       part: dict, save) -> dict:
    """Raw Swap logs over [b0, b1], 1M-block segments, monthly totals only.
    `part` carries checkpoint state (next_block, n_swaps, vol_eth) so an
    interrupted run resumes mid-month; `save` persists it per segment."""
    seg = 1_000_000
    b = part.get("next_block", b0)
    t_start = time.time()
    while b <= b1:
        e = min(b + seg - 1, b1)
        swaps = rpc.get_swaps(b, e)
        part["n_swaps"] = part.get("n_swaps", 0) + len(swaps)
        part["vol_eth"] = (part.get("vol_eth", 0.0)
                           + sum(abs(s.amount1) for s in swaps) / 1e18)
        part["next_block"] = e + 1
        save()
        b = e + 1
        print(f"  [{label}] ..{e:,} ({part['n_swaps']} swaps, "
              f"{time.time() - t_start:.0f}s)", flush=True)
    return {"block_from": b0, "block_to": b1, "n_swaps": part["n_swaps"],
            "vol_eth": part["vol_eth"]}


def main() -> int:
    px = monthly_eth_price()
    share, cells = implied_share()
    state = json.loads(OUT.read_text()) if OUT.exists() else {}
    state["implied_share"] = share
    state.setdefault("validation_committed_months",
                     validate_proxy(share, cells, px))
    OUT.parent.mkdir(parents=True, exist_ok=True)

    rpc = ArbRPC(RPC_URL, pool=POOL)

    # Month boundary blocks: bisect timestamps; 2026-05-01 bound committed.
    bounds = state.setdefault("month_bounds", {})
    bounds["2026-05"] = MAY_BLOCK_FROM
    lo_guess = 400_000_000
    for m in MONTHS:
        if m in bounds:
            continue
        ts = int(datetime.strptime(m, "%Y-%m").replace(
            tzinfo=timezone.utc).timestamp())
        bounds[m] = rpc.block_at_time(ts, lo_guess, MAY_BLOCK_FROM)
        print(f"[{m}] first block {bounds[m]:,}", flush=True)
        OUT.write_text(json.dumps(state, indent=1, sort_keys=True) + "\n")

    months_out = state.setdefault("extension_months", {})
    partials = state.setdefault("partials", {})

    def save():
        OUT.write_text(json.dumps(state, indent=1, sort_keys=True) + "\n")

    for i, m in enumerate(MONTHS):
        if m in months_out:
            continue
        b0 = bounds[m]
        b1 = (bounds[MONTHS[i + 1]] if i + 1 < len(MONTHS)
              else bounds["2026-05"]) - 1
        r = fetch_month_volume(rpc, b0, b1, m, partials.setdefault(m, {}),
                               save)
        partials.pop(m, None)
        r["vol_usd"] = r["vol_eth"] * px[m]
        r["proxy_fees_usd"] = r["vol_usd"] * FEE_TIER * LP_FEE_SHARE * share
        r["proxy_fees_per_day"] = r["proxy_fees_usd"] / 30.44
        months_out[m] = r
        OUT.write_text(json.dumps(state, indent=1, sort_keys=True) + "\n")
        print(f"[{m}] {r['n_swaps']} swaps, vol ${r['vol_usd']:,.0f}, "
              f"proxy fees ${r['proxy_fees_usd']:.3f}", flush=True)

    print("done ->", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
