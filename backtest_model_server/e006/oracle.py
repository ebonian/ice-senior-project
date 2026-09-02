#!/usr/bin/env python3
"""E006 stage 1 — the perfect-foresight timing UPPER BOUND.

    nix develop .#gate1 -c python backtest_model_server/e006/oracle.py

For each width arm, every hour of the E003 window gets a payoff computed AS IF
the position were freshly centered at that hour's start price:

    payoff_h = fees_h + funding_h + gamma_pnl_h          (gamma_pnl_h <= 0)

  fees_h      gate1 fee_engine over the hour's swaps, protocol-fee correct,
              our $1,015 share against recorded in-range pool liquidity
  funding_h   recorded hourly HL rate x the fresh position's ETH-delta short
  gamma_pnl_h [V(p1)-V(p0)] + a0(p0)*(p0-p1): what the delta hedge leaves
              behind over the hour (E003 SS2's hedged gamma, one hour at a time)

An O(N) two-state DP then selects the held-hour set maximizing total payoff
minus switch costs (enter = mint-path txs + swap-to-mix + hedge open; exit =
burn+collect txs + swap-back + hedge close; hedge legs priced at the chosen
envelope point). The verdict reads the CENTRAL point; the other two are
reported.

WHY THIS BOUNDS EVERY TIMING POLICY FROM ABOVE. Any realizable in/out policy
(a) cannot re-center for free every hour — its position drifts off-center
between recenters, earning at most what a freshly centered position earns in
fees minus nothing it gains elsewhere; (b) pays at least these switch costs on
every transition, and pays intra-streak recenter and rehedge execution costs
this stage does not charge at all; (c) pays the entry cost out of working
capital (here fees are credited on the full $1,015 every hour); (d) receives a
funding tick here for every held hour, where the exact loop books none at the
mint boundary. Every one of those approximations OVER-credits the timing
policy, so the DP optimum is an upper bound on any policy's net — including
`always_in` (one unbroken streak) and `always_cash` (the empty set), which the
DP dominates by construction because both are in its feasible set.

The bound is deliberately loose in one direction only. Stage 2
([exact.py](exact.py)) re-simulates the DP-chosen streaks exactly through
E003's `run_arm` and is the realistic oracle number.

Outputs: out/stage1_results.json, out/stage1_hours_w<W>.csv.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

E006 = Path(__file__).resolve().parent
BMS = E006.parent
for p in (BMS / "gate1", BMS / "e003"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
from engine import cost_model as CM            # noqa: E402
from engine import fee_engine, harness as H, il_ledger  # noqa: E402
import envelope as ENV                          # noqa: E402
import race                                     # noqa: E402

# E006 arms — the pre-registered subset of E003's WIDTH_ARMS.
ARMS = (4, 10, 40, 160)
NEG = -1e18


# --------------------------------------------------------------------------
def hour_grid(ts_epoch: np.ndarray) -> np.ndarray:
    """Hour-start epochs covering the window, first boundary at-or-after the
    first swap, last hour the (possibly partial) one containing the last swap."""
    h_first = -(-int(ts_epoch[0]) // 3600) * 3600
    h_last = (int(ts_epoch[-1]) // 3600) * 3600
    return np.arange(h_first, h_last + 1, 3600, dtype=np.int64)


def hourly_payoffs(width: int, swaps: pd.DataFrame, funding: dict,
                   hs: np.ndarray, lp_capital: float) -> pd.DataFrame:
    """Per-hour payoff of a freshly centered width-`width` position."""
    ts = swaps["timestamp"].to_numpy(np.int64)
    prices = swaps["price"].to_numpy(np.float64)
    ticks = swaps["v3_tick"].to_numpy(np.int64)
    half = ENV.half_width_ticks(width)
    n_hours = len(hs)

    idx0 = np.searchsorted(ts, hs, side="right") - 1          # state at hour start
    idx1 = np.searchsorted(ts, hs + 3600, side="right") - 1   # state at hour end

    cols = {k: np.zeros(n_hours) for k in
            ("p0", "p1", "fees_usd", "funding_usd", "gamma_pnl_usd",
             "payoff_usd", "eth_ntl_usd", "exit_ntl_usd")}
    n_missing_rate = 0

    for h in range(n_hours):
        i0, i1 = int(idx0[h]), int(idx1[h])
        p0, k0, p1 = float(prices[i0]), int(ticks[i0]), float(prices[i1])
        center = (k0 // ENV.TICK_SPACING) * ENV.TICK_SPACING
        lo_t, hi_t = center - half, center + half
        pl, pu = H.v3_tick_to_price(lo_t), H.v3_tick_to_price(hi_t)
        L = H.compute_liquidity_from_capital(lp_capital, p0, pl, pu)
        q, _ = il_ledger.position_amounts(p0, pl, pu, L)

        acc = fee_engine.accrue_fees(
            swaps.iloc[i0 + 1: i1 + 1], L, lo_t, hi_t, pl, pu,
            prev_price=p0, prev_v3_tick=k0,
            pool_fee=race.POOL_FEE, liquidity_scale=race.LIQ_SCALE,
            track_path=False)

        v0 = H.compute_position_value(p0, pl, pu, L)
        v1 = H.compute_position_value(p1, pl, pu, L)
        gamma_pnl = (v1 - v0) + q * (p0 - p1)

        rate = funding.get(pd.Timestamp(int(hs[h]), unit="s", tz="UTC"))
        if rate is None:
            n_missing_rate += 1
            fund = 0.0
        else:
            fund = rate * q * p0

        a0_exit, _ = il_ledger.position_amounts(p1, pl, pu, L)
        cols["p0"][h], cols["p1"][h] = p0, p1
        cols["fees_usd"][h] = acc.fee_usd
        cols["funding_usd"][h] = fund
        cols["gamma_pnl_usd"][h] = gamma_pnl
        cols["payoff_usd"][h] = acc.fee_usd + fund + gamma_pnl
        cols["eth_ntl_usd"][h] = q * p0            # swap+hedge notional to ENTER at h
        cols["exit_ntl_usd"][h] = a0_exit * p1     # notional to EXIT at boundary h+1

    df = pd.DataFrame({"hour_epoch": hs, **cols})
    df.attrs["n_missing_rate"] = n_missing_rate
    return df


# --------------------------------------------------------------------------
def switch_costs(hours: pd.DataFrame, point) -> tuple[np.ndarray, np.ndarray]:
    """(enter_cost[h], exit_cost[b]) for b in 0..N — exit at boundary b unwinds
    the position freshly centered at hour b-1 at that hour's end price. The
    hedge open/close legs are priced at the given envelope point; on-chain legs
    use the frozen cost model's own function."""
    n = len(hours)
    enter = np.zeros(n)
    exit_ = np.zeros(n + 1)
    eth = hours["eth_ntl_usd"].to_numpy()
    ex = hours["exit_ntl_usd"].to_numpy()
    for h in range(n):
        enter[h] = (CM.onchain_cost(eth[h], 1, 0, n_tx=ENV.TX_PER_RECENTER).total_usd
                    + point.cost(eth[h]))
        exit_[h + 1] = (CM.onchain_cost(ex[h], 0, 1, n_tx=CM.TX_PER_EXIT).total_usd
                        + point.cost(ex[h]))
    exit_[0] = float("inf")   # cannot exit before entering
    return enter, exit_


def dp_select(payoff: np.ndarray, enter: np.ndarray,
              exit_: np.ndarray) -> tuple[float, np.ndarray]:
    """O(N) two-state DP. Returns (optimal value, held mask)."""
    n = len(payoff)
    in_prev, out_prev = NEG, 0.0
    from_in = np.zeros(n, dtype=bool)    # True: in[h] came from in[h-1]
    from_out = np.zeros(n, dtype=bool)   # True: out[h] came from out[h-1]
    for h in range(n):
        via_enter = out_prev - enter[h]
        if in_prev >= via_enter:
            in_cur, from_in[h] = in_prev + payoff[h], True
        else:
            in_cur = via_enter + payoff[h]
        via_exit = in_prev - exit_[h]
        if out_prev >= via_exit:
            out_cur, from_out[h] = out_prev, True
        else:
            out_cur = via_exit
        in_prev, out_prev = in_cur, out_cur

    end_exit = in_prev - exit_[n]
    value = max(out_prev, end_exit)
    held = np.zeros(n, dtype=bool)
    state = "in" if end_exit > out_prev else "out"
    for h in range(n - 1, -1, -1):
        if state == "in":
            held[h] = True
            state = "in" if from_in[h] else "out"
        else:
            state = "out" if from_out[h] else "in"
    return value, held


def streaks_of(held: np.ndarray) -> list[tuple[int, int]]:
    """[(start_idx, end_idx_inclusive), ...] of maximal held runs."""
    out, start = [], None
    for h, v in enumerate(held):
        if v and start is None:
            start = h
        elif not v and start is not None:
            out.append((start, h - 1))
            start = None
    if start is not None:
        out.append((start, len(held) - 1))
    return out


# --------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-05-01")
    ap.add_argument("--end", default="2026-08-28")
    ap.add_argument("--lp-capital", type=float, default=ENV.LP_CAPITAL_USD)
    ap.add_argument("--force", action="store_true",
                    help="recompute hourly payoffs even if the CSV checkpoint exists")
    args = ap.parse_args()

    out_dir = E006 / "out"
    out_dir.mkdir(parents=True, exist_ok=True)

    swaps = race.load_swaps(args.start, args.end)
    funding = race.load_funding()
    ts = swaps["timestamp"].to_numpy(np.int64)
    hs = hour_grid(ts)
    days = (int(ts[-1]) - int(ts[0])) / 86400.0
    print(f"swaps {len(swaps):,}  hours {len(hs):,}  days {days:.5f}")

    payload = {
        "experiment": "E006", "stage": 1,
        "cost_model_version": CM.COST_MODEL_VERSION,
        "envelope_version": ENV.E003_ENVELOPE_VERSION,
        "window": {"start": args.start, "end": args.end, "days": days,
                   "n_swaps": int(len(swaps)), "n_hours": int(len(hs)),
                   "first_swap_utc": str(swaps["ts"].iloc[0]),
                   "last_swap_utc": str(swaps["ts"].iloc[-1])},
        "lp_capital_usd": args.lp_capital,
        "target_usd_per_day": ENV.TARGET_USD_PER_DAY,
        "arms": {},
    }

    for w in ARMS:
        csv = out_dir / f"stage1_hours_w{w}.csv"
        t0 = time.time()
        if csv.exists() and not args.force:
            hours = pd.read_csv(csv)
            n_missing = int(hours.attrs.get("n_missing_rate", 0))
            print(f"W{w}: reusing {csv.name}")
        else:
            hours = hourly_payoffs(w, swaps, funding, hs, args.lp_capital)
            n_missing = hours.attrs["n_missing_rate"]

        arm = {
            "width": w, "width_pct": ENV.width_pct(w),
            "n_missing_funding_rates": n_missing,
            "sum_fees_usd": float(hours["fees_usd"].sum()),
            "sum_funding_usd": float(hours["funding_usd"].sum()),
            "sum_gamma_pnl_usd": float(hours["gamma_pnl_usd"].sum()),
            "sum_payoff_usd": float(hours["payoff_usd"].sum()),
            "points": {},
        }
        for point in ENV.ENVELOPE:
            enter, exit_ = switch_costs(hours, point)
            value, held = dp_select(hours["payoff_usd"].to_numpy(), enter, exit_)
            runs = streaks_of(held)
            # stage-1 valuation of the always-in path (one unbroken streak),
            # for the domination contract
            alwaysin = float(-enter[0] + hours["payoff_usd"].sum() - exit_[-1])
            arm["points"][point.name] = {
                "value_usd": float(value), "per_day_usd": float(value / days),
                "held_hours": int(held.sum()),
                "held_frac": float(held.mean()),
                "n_streaks": len(runs),
                "alwaysin_stage1_usd": alwaysin,
                "dominates_alwaysin": bool(value >= alwaysin),
                "dominates_alwayscash": bool(value >= 0.0),
            }
            hours[f"held_{point.name}"] = held
        arm_pts = arm["points"]
        print(f"W{w:<4d} UB central ${arm_pts['central']['value_usd']:.2f} "
              f"(${arm_pts['central']['per_day_usd']:+.3f}/day) "
              f"held {arm_pts['central']['held_frac']*100:.1f}% "
              f"in {arm_pts['central']['n_streaks']} streaks "
              f"[opt {arm_pts['optimistic']['per_day_usd']:+.3f} "
              f"pess {arm_pts['pessimistic']['per_day_usd']:+.3f}] "
              f"{time.time()-t0:.0f}s")
        hours.to_csv(csv, index=False)
        payload["arms"][f"w{w}"] = arm

    best = max(payload["arms"].values(),
               key=lambda a: a["points"]["central"]["per_day_usd"])
    payload["best_arm_central"] = f"w{best['width']}"
    (out_dir / "stage1_results.json").write_text(json.dumps(payload, indent=2))
    print(f"wrote {out_dir/'stage1_results.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
