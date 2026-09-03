#!/usr/bin/env python3
"""E010 race runner: e005's generalized simulator, capital- and chain-aware.

    nix develop .#gate1 -c python backtest_model_server/e010/race10.py \
        --slug m_weth_usdc_0p05 --capital 10000 --gas-point central

Reused BY IMPORT from e005/race.py (loaded by explicit file path — e003 also
ships a race.py): PoolSpec, run_arm, always_cash, load_swaps, first_exit —
the entire simulation. What this wrapper adds, and only this:

  CAPITAL   --capital is TOTAL reference capital; the LP notional is
            capital x (1015/1420), E003's C2 split (registry.lp_notional).
  GAS       the chain's measured $/tx envelope point replaces the frozen
            Arbitrum constant for the duration of the run
            (CM.GAS_USD_PER_TX is set and restored; onchain_cost reads it at
            call time). Arbitrum runs never patch — the frozen value IS the
            Arbitrum envelope, all points.
  SPEC      candidates come from e010/out/candidates.json (same schema);
            marks/funding loaders know USDT-as-stable and the UNI CSV.

Envelope coupling (pre-registered): a run tagged gas point g is read at HPL
envelope point g by tables10.py; results.json still records all three HPL
points for transparency.

Control reproduction (validity gate i): --slug control_weth_usdc_0p05 races
E005's control on E003's parquets + funding, no gas patch, capital 1420 —
must land inside E005 §4's tolerances (contract test).
"""

from __future__ import annotations

import argparse
import importlib.util as _ilu
import json
import sys
from dataclasses import asdict
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
from engine import cost_model as CM  # noqa: E402

_spec = _ilu.spec_from_file_location("e005_race", BMS / "e005" / "race.py")
R5 = _ilu.module_from_spec(_spec)
sys.modules["e005_race"] = R5      # dataclass introspection needs the entry
_spec.loader.exec_module(R5)

ENVELOPE = R.ENVELOPE
BINANCE_FOR = {"WETH": "ethusdt"}   # every e010 non-stable quote is WETH


def load_spec10(slug: str) -> R5.PoolSpec:
    rows = json.loads((E010 / "out" / "candidates.json").read_text())["candidates"]
    c = next((r for r in rows if r["slug"] == slug), None)
    if c is None or c["status"] != "RESOLVED":
        raise SystemExit(f"{slug} is not a RESOLVED e010 candidate")
    shares = {round(s["lp_fee_share"], 10) for s in c["lp_fee_share_schedule"]}
    if len(shares) != 1:
        raise NotImplementedError(
            f"{slug}: lp_fee_share changed mid-window {c['lp_fee_share_schedule']}"
            " — piecewise accrual required (no 2026 candidate needed it; "
            "implement before racing this pool)")
    legs = c["legs"]
    beta = any(v.get("hedge") == "eth-beta" for v in legs.values())
    coin0 = (legs["token0"].get("hl_coin")
             if legs["token0"]["hedge"] != "stable-unhedged" else None)
    coin1 = (legs["token1"].get("hl_coin")
             if legs["token1"]["hedge"] != "stable-unhedged" else None)
    return R5.PoolSpec(
        slug=slug, family=c["family"], address=c["address"], fee=c["fee"],
        tick_spacing=c["pool_state"]["tick_spacing"],
        decimals0=c["decimals0"], decimals1=c["decimals1"],
        token0=c["token0_symbol"], token1=c["token1_symbol"],
        lp_fee_share=shares.pop(),
        hedge_mode="static-beta" if beta else "per-leg",
        coin0=coin0, coin1=coin1,
        quote_is_usd=c["token1_symbol"] in R.STABLES,
    ), c["chain"]


def load_marks10(token1: str):
    if token1 in R.STABLES:
        return None
    f = BMS / "e005" / "data" / "marks" / f"binance_{BINANCE_FOR[token1]}_1h.csv"
    m = pd.read_csv(f)
    return (m["open_time_ms"].to_numpy(np.int64) // 1000,
            m["open"].to_numpy(np.float64))


def load_funding10(coin: str) -> dict:
    d = E010 / "data" / "funding" / f"hl_funding_{coin.lower()}_hourly.csv"
    if not d.exists():
        d = BMS / "e005" / "data" / "funding" / f"hl_funding_{coin.lower()}_hourly.csv"
    f = pd.read_csv(d)
    ts = pd.to_datetime(f["time_ms"], unit="ms", utc=True).dt.floor("h")
    return dict(zip(ts, pd.to_numeric(f["funding_rate_hourly"])))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", required=True,
                    help="e010 slug, or control_weth_usdc_0p05 for gate (i)")
    ap.add_argument("--capital", type=float, default=R.REFERENCE_CAPITAL_USD,
                    help="TOTAL reference capital; LP notional = x1015/1420")
    ap.add_argument("--gas-point", default="central",
                    choices=["optimistic", "central", "pessimistic"])
    ap.add_argument("--detect-lag-hours", type=int, default=1)
    ap.add_argument("--rehedge-hours", type=int, default=1)
    ap.add_argument("--tag", default=None)
    args = ap.parse_args()

    control = args.slug == "control_weth_usdc_0p05"
    if control:
        # E005's control spec, E003's parquets and exact funding CSV.
        sys.path.insert(0, str(BMS / "e005"))
        spec = R5.load_spec("weth_usdc_0p05")
        chain = "arbitrum"
        marks = None
        funding = {"ETH": R5.load_funding_bot_eth()}
        swaps = R5.load_swaps(spec, R.WINDOW_START, R.WINDOW_END, None,
                              BMS / "e003" / "data" / "swaps")
        lp_capital = 1015.0
    elif args.slug.startswith("e005:"):
        # Part B measured re-bind: an E005 Arbitrum pool re-raced at the
        # reference capital on its own committed parquets, funding and marks.
        # Frozen Arbitrum gas; gas-point is ignored by construction.
        slug5 = args.slug.split(":", 1)[1]
        spec = R5.load_spec(slug5)
        chain = "arbitrum"
        marks = R5.load_marks(spec.token1)
        funding = {}
        for coin in {spec.coin0, spec.coin1,
                     "ETH" if spec.hedge_mode == "static-beta" else None}:
            if coin:
                funding[coin] = R5.load_funding_csv(coin)
        swaps = R5.load_swaps(spec, R.WINDOW_START, R.WINDOW_END, marks, None)
        lp_capital = R.lp_notional(args.capital)
    else:
        spec, chain = load_spec10(args.slug)
        marks = load_marks10(spec.token1)
        funding = {}
        for coin in {spec.coin0, spec.coin1,
                     "ETH" if spec.hedge_mode == "static-beta" else None}:
            if coin:
                funding[coin] = load_funding10(coin)
        swaps = R5.load_swaps(spec, R.WINDOW_START, R.WINDOW_END, marks,
                              E010 / "data" / "swaps" / spec.slug)
        lp_capital = R.lp_notional(args.capital)

    gas_tx = R.gas_usd_per_tx(chain, args.gas_point)
    print(f"{spec.slug}: {len(swaps):,} swaps  chain={chain} "
          f"capital={args.capital:,.0f} lp_notional={lp_capital:,.2f} "
          f"gas[{args.gas_point}]=${gas_tx:.4f}/tx hedge={spec.hedge_mode} "
          f"coins=({spec.coin0},{spec.coin1}) lp_share={spec.lp_fee_share:.4f}",
          flush=True)

    ts_epoch = swaps["timestamp"].to_numpy(dtype=np.int64)
    h0 = (int(ts_epoch[0]) // 3600 + 1) * 3600
    h1 = (int(ts_epoch[-1]) // 3600) * 3600
    hour_ts = np.arange(h0, h1 + 1, 3600, dtype=np.int64)
    hour_idx = np.searchsorted(ts_epoch, hour_ts, side="right") - 1
    hour_px = np.where(hour_idx >= 0,
                       swaps["price"].to_numpy()[np.clip(hour_idx, 0, None)],
                       np.nan)

    tag = args.tag or (f"lag{args.detect_lag_hours}h_rh{args.rehedge_hours}h"
                       f"_cap{int(args.capital)}_gas-{args.gas_point}")
    if control:
        tag = args.tag or "control_lag1h_rh1h"
    out_dir = E010 / "out" / spec.slug / tag
    out_dir.mkdir(parents=True, exist_ok=True)

    arms = R.arms_for_spacing(spec.tick_spacing)
    gas_prev = CM.GAS_USD_PER_TX
    results = []
    try:
        CM.GAS_USD_PER_TX = gas_tx        # chain-gas override (frozen on arb)
        for arm in arms:
            r = R5.run_arm(spec, arm, swaps, funding, marks, hour_ts, hour_px,
                           hour_idx, args.detect_lag_hours, args.rehedge_hours,
                           lp_capital)
            results.append(r)
            t = r.total
            gam = t.lp_value_change_usd + t.hedge_price_pnl_usd
            fg = t.lp_fees_usd / abs(gam) if gam else float("nan")
            print(f"  {r.arm:<24s} +-{r.width_pct*100:5.2f}% "
                  f"rec={t.n_recenters:>5,} fees=${t.lp_fees_usd:>10,.2f} "
                  f"gamma=${gam:>11,.2f} f/g={fg:6.3f} "
                  f"{args.gas_point[:4]}=$"
                  f"{t.per_day(R.ENVELOPE_BY_NAME[args.gas_point]):>9.3f}/d "
                  f"[chk {r.checks['lp_value_abs_gap_usd']:.1e}]", flush=True)
    finally:
        CM.GAS_USD_PER_TX = gas_prev

    results.append(R5.always_cash(results[0].total.hours,
                                  {k: b.hours for k, b in results[0].months.items()}))

    payload = {
        "experiment": "E010",
        "pool": {"slug": spec.slug, "family": spec.family, "chain": chain,
                 "address": spec.address, "fee": spec.fee,
                 "tick_spacing": spec.tick_spacing,
                 "token0": spec.token0, "token1": spec.token1,
                 "lp_fee_share": spec.lp_fee_share,
                 "hedge_mode": spec.hedge_mode,
                 "coins": [spec.coin0, spec.coin1],
                 "quote_is_usd": spec.quote_is_usd},
        "cost_model_version": R.COST_MODEL_VERSION,
        "envelope_version": R.ENVELOPE_VERSION,
        "gas": {"point": args.gas_point, "usd_per_tx": gas_tx,
                "source": ("frozen gate1 constant" if chain == "arbitrum"
                           else "e010 measured envelope (out/gas_envelope.json)")},
        "window": {"start": R.WINDOW_START, "end": R.WINDOW_END,
                   "hours": results[0].total.hours,
                   "n_swaps": int(len(swaps)),
                   "first_swap_utc": str(swaps["ts"].iloc[0]),
                   "last_swap_utc": str(swaps["ts"].iloc[-1])},
        "policy": {
            "detect_lag_hours": args.detect_lag_hours,
            "rehedge_hours": args.rehedge_hours,
            "total_capital_usd": args.capital,
            "lp_capital_usd": lp_capital,
            "hedge_equity_usd": R.hedge_equity(args.capital),
            "lp_fraction": R.LP_FRACTION,
            "notional_mode": "constant",
            "target_usd_per_day": R.target_usd_per_day(args.capital),
            "tx_per_recenter": R.TX_PER_RECENTER,
        },
        "envelope": [
            {"name": p.name, "maker_share_notional": p.maker_share_notional,
             "fee_bps": p.fee_bps, "slippage_bps": p.slippage_bps,
             "chase_bps": p.chase_bps, "total_bps": p.total_bps}
            for p in ENVELOPE],
        "arms": [],
    }
    for r in results:
        payload["arms"].append({
            "arm": r.arm, "half_width_ticks": r.half_width_ticks,
            "width_pct": r.width_pct, "target_pcts": r.target_pcts,
            "checks": r.checks,
            "total": {**asdict(r.total),
                      **{f"net_usd_{p.name}": r.total.net_usd(p) for p in ENVELOPE},
                      **{f"per_day_{p.name}": r.total.per_day(p) for p in ENVELOPE}},
            "months": {k: {**asdict(b),
                           **{f"net_usd_{p.name}": b.net_usd(p) for p in ENVELOPE},
                           **{f"per_day_{p.name}": b.per_day(p) for p in ENVELOPE}}
                       for k, b in r.months.items()},
        })
    (out_dir / "results.json").write_text(json.dumps(payload, indent=2))
    print(f"wrote {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
