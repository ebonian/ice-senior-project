#!/usr/bin/env python3
"""E003 — the cost-honest width race (mode C, synthetic-rule replay).

    nix develop .#gate1 -c python backtest_model_server/e003/race.py

One variable: width. Every arm runs the identical policy —

    always in position at width W; recenter on the pool's own tick leaving the
    range; never EXIT to cash; no dwell, no hysteresis, no deadband.

against the same RPC-sourced swap stream, the same recorded funding series, and
the same frozen cost model (`gate1/engine/cost_model.py`, version
`gate1-2026-08-29`, imported unmodified). `always_cash` is the zero line.

WHAT IS REPLAYED VS MODELLED
  replayed   every Swap event (price, volume, pool liquidity, tick) from
             `eth_getLogs`; every hourly Hyperliquid ETH funding rate
  closed form LP fee accrual, position value, ETH delta, IL — all from the
             harness math gate1 verified, called through gate1's own modules
  modelled   on-chain cost (5.155 bps of swapped notional + gas), and the hedge
             leg's EXECUTION COST as a three-point envelope. The hedge RATIO is
             not modelled and not varied: the short tracks the LP position's ETH
             delta on a fixed cadence (--rehedge-hours, default 1h) and at
             every recenter, identically for every arm and every envelope
             point.

The LP path and the hedge notional path are simulated ONCE per arm; the envelope
then prices that one path three ways. That is deliberate — it makes it
impossible for an envelope point to change the strategy's behaviour, which is
the whole point of calling it a cost envelope.

Outputs land in e003/out/.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path

import numpy as np
import pandas as pd

E003 = Path(__file__).resolve().parent
GATE1 = E003.parent / "gate1"
sys.path.insert(0, str(GATE1))
sys.path.insert(0, str(E003))
from engine import cost_model as CM  # noqa: E402
from engine import fee_engine, harness as H, il_ledger  # noqa: E402

import envelope as ENV  # noqa: E402

POOL_FEE = 0.0005
LIQ_SCALE = H.liquidity_scale(18, 6)
FUNDING_CSV = Path(
    "/home/poon/developments/llaminet/bot/analysis/strategy-review/data/"
    "hl_funding_eth_hourly.csv"
)


# --------------------------------------------------------------------------
def load_swaps(start: str, end: str, swap_dir: Path | None = None) -> pd.DataFrame:
    """Every RPC-sourced swap in [start, end), in pool order.

    Column names match what `gate1/engine/fee_engine.accrue_fees` expects, so the
    Gate-1 fee arithmetic is called with no adapter and no re-derivation.
    """
    d = swap_dir or (E003 / "data" / "swaps")
    files = sorted(d.glob("*.parquet"))
    if not files:
        raise FileNotFoundError(f"no swap parquets in {d} — run fetch_months.py")
    df = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
    df = df.sort_values(["block_number", "log_index"]).reset_index(drop=True)
    df["ts"] = pd.to_datetime(df["timestamp"], unit="s", utc=True)
    t0 = pd.Timestamp(start, tz="UTC")
    t1 = pd.Timestamp(end, tz="UTC")
    df = df[(df["ts"] >= t0) & (df["ts"] < t1)].reset_index(drop=True)
    df["v3_tick"] = df["tick"].astype(np.int64)
    return df


def load_funding(path: Path | None = None) -> dict:
    """hour (UTC, floored) -> hourly funding rate. Recorded, never modelled."""
    f = pd.read_csv(path or FUNDING_CSV)
    ts = pd.to_datetime(f["iso_utc"], utc=True, format="mixed").dt.floor("h")
    return dict(zip(ts, pd.to_numeric(f["funding_rate_hourly"])))


def first_exit(ticks: np.ndarray, start: int, lo: int, hi: int) -> int | None:
    """Index of the first swap at or after `start` whose post-swap tick is OOR.

    Chunked and doubling so a short cycle costs O(cycle length) rather than
    O(remaining stream) — the narrow arms have tens of thousands of cycles.
    """
    n = len(ticks)
    i, chunk = start, 4096
    while i < n:
        j = min(i + chunk, n)
        seg = ticks[i:j]
        m = (seg < lo) | (seg > hi)
        if m.any():
            return i + int(np.argmax(m))
        i = j
        chunk = min(chunk * 2, 1 << 20)
    return None


# --------------------------------------------------------------------------
@dataclass
class Bucket:
    """Every P&L line for one sub-window. All USD. Signs as booked."""
    label: str = ""
    hours: float = 0.0
    lp_fees_usd: float = 0.0
    il_usd: float = 0.0
    basket_delta_usd: float = 0.0
    lp_value_change_usd: float = 0.0
    onchain_cost_usd: float = 0.0
    hedge_price_pnl_usd: float = 0.0
    funding_usd: float = 0.0
    rehedge_notional_usd: float = 0.0
    swapped_notional_usd: float = 0.0
    n_recenters: int = 0
    n_rehedges: int = 0
    volume_usd: float = 0.0
    volume_in_range_usd: float = 0.0
    n_swaps: int = 0
    seconds_out_of_range: float = 0.0

    def net_usd(self, point: ENV.EnvelopePoint) -> float:
        return (
            self.lp_value_change_usd
            + self.lp_fees_usd
            - self.onchain_cost_usd
            + self.hedge_price_pnl_usd
            + self.funding_usd
            - point.cost(self.rehedge_notional_usd)
        )

    def per_day(self, point: ENV.EnvelopePoint) -> float:
        d = self.hours / 24.0
        return self.net_usd(point) / d if d > 0 else float("nan")


@dataclass
class ArmResult:
    arm: str
    width: int | None
    half_width_ticks: int | None
    width_pct: float | None
    total: Bucket
    months: dict = field(default_factory=dict)
    cycles: list = field(default_factory=list)
    checks: dict = field(default_factory=dict)


# --------------------------------------------------------------------------
def run_arm(width: int, swaps: pd.DataFrame, funding: dict, hour_ts: np.ndarray,
            hour_px: np.ndarray, hour_idx: np.ndarray, detect_lag_hours: int,
            rehedge_hours: int, lp_capital: float, notional_mode: str,
            keep_cycles: bool) -> ArmResult:
    """Simulate one width arm over the whole window.

    Produces the LP path and the rehedge-notional path. It does NOT price the
    hedge execution — the envelope does that afterwards, from
    `rehedge_notional_usd`, so no envelope point can alter behaviour.
    """
    ticks = swaps["v3_tick"].to_numpy(dtype=np.int64)
    prices = swaps["price"].to_numpy(dtype=np.float64)
    ts_epoch = swaps["timestamp"].to_numpy(dtype=np.int64)
    n = len(swaps)
    half = ENV.half_width_ticks(width)

    total = Bucket(label="total")
    months: dict[str, Bucket] = {}

    def bucket_for(epoch: int) -> Bucket:
        lab = pd.Timestamp(epoch, unit="s", tz="UTC").strftime("%Y-%m")
        if lab not in months:
            months[lab] = Bucket(label=lab)
        return months[lab]

    # --- open the first position -------------------------------------------
    i = 0
    p0, t0tick = float(prices[0]), int(ticks[0])
    center = (t0tick // ENV.TICK_SPACING) * ENV.TICK_SPACING
    lo_t, hi_t = center - half, center + half
    pl, pu = H.v3_tick_to_price(lo_t), H.v3_tick_to_price(hi_t)

    # Entry costs a swap from 100% USDC to the range's token mix, exactly as a
    # recenter does. Charged identically to every arm, once.
    L_probe = H.compute_liquidity_from_capital(lp_capital, p0, pl, pu)
    a0_t, _ = il_ledger.position_amounts(p0, pl, pu, L_probe)
    entry_swap_notional = a0_t * p0
    entry_cost = CM.onchain_cost(entry_swap_notional, 1, 0, n_tx=ENV.TX_PER_RECENTER)
    L = H.compute_liquidity_from_capital(lp_capital - entry_cost.total_usd, p0, pl, pu)
    total.onchain_cost_usd += entry_cost.total_usd
    total.swapped_notional_usd += entry_swap_notional
    b0 = bucket_for(int(ts_epoch[0]))
    b0.onchain_cost_usd += entry_cost.total_usd
    b0.swapped_notional_usd += entry_swap_notional

    q, p_mark = il_ledger.position_amounts(p0, pl, pu, L)[0], p0
    total.rehedge_notional_usd += q * p0
    b0.rehedge_notional_usd += q * p0
    total.n_rehedges += 1
    b0.n_rehedges += 1

    mint_epoch, mint_price, mint_tick, mint_idx = int(ts_epoch[0]), p0, int(ticks[0]), 0
    cycles: list[dict] = []
    ruin: dict | None = None
    # Cumulative LP-leg P&L, tracked directly so the decomposition can be
    # checked against it. Starts at minus the entry cost.
    pnl_check = -entry_cost.total_usd

    def mark_to(price: float, bk: Bucket) -> None:
        """Realize the short's price P&L up to `price`. A short gains as ETH falls."""
        nonlocal p_mark
        pnl = q * (p_mark - price)
        total.hedge_price_pnl_usd += pnl
        bk.hedge_price_pnl_usd += pnl
        p_mark = price

    def rehedge(price: float, bk: Bucket, target: float | None = None) -> None:
        """Trade the short to `target` (default: the LP position's ETH delta).

        One trade, not two: a recenter marks to the exit price, replaces the
        position, and then moves the short straight from its old size to the new
        target. Flattening and re-establishing would book roughly twice the
        notional and charge the envelope twice for it.
        """
        nonlocal q
        tgt = (il_ledger.position_amounts(price, pl, pu, L)[0]
               if target is None else target)
        ntl = abs(tgt - q) * price
        total.rehedge_notional_usd += ntl
        bk.rehedge_notional_usd += ntl
        total.n_rehedges += 1
        bk.n_rehedges += 1
        q = tgt

    while i < n - 1:
        # ---- how long does this position live? ----------------------------
        j = first_exit(ticks, i, lo_t, hi_t)
        if j is None:
            j = n - 1
            recenter = False
        else:
            recenter = True

        if recenter and detect_lag_hours > 0:
            # A 1-hour decision loop cannot act on a mid-hour breach. Hold to
            # the next hour boundary; if price came back inside by then, the
            # position simply continues.
            lag_s = detect_lag_hours * 3600
            act_epoch = (int(ts_epoch[j]) // lag_s + 1) * lag_s
            k = int(np.searchsorted(ts_epoch, act_epoch, side="right")) - 1
            if k <= j:
                k = j
            if k >= n - 1:
                k, recenter = n - 1, False
            else:
                oor = int(ts_epoch[k]) - int(ts_epoch[j])
                total.seconds_out_of_range += oor
                bucket_for(int(ts_epoch[k])).seconds_out_of_range += oor
                if lo_t <= int(ticks[k]) <= hi_t:
                    # back inside by the decision point: the position simply
                    # continues, so resume scanning from there.
                    i = max(k, i + 1)
                    continue
            j = k

        exit_epoch = int(ts_epoch[j])
        exit_price = float(prices[j])
        exit_tick = int(ticks[j])
        bk = bucket_for(exit_epoch)

        # ---- walk the cycle hour by hour -----------------------------------
        # Fees, position value, hedge and funding are booked at the hour they
        # occur, not at the cycle's exit. A W160 cycle can run for weeks;
        # booking it whole would hand one month everything and its neighbour
        # nothing, and the decision rule counts monthly sub-windows. Per-swap
        # fee accrual is additive over contiguous slices as long as
        # `prev_price`/`prev_v3_tick` chain, so splitting on hour boundaries
        # gives the same cycle total as one call over the whole cycle.
        def book(bkt: Bucket, dv: float, acc_) -> None:
            for tgt, val in (("lp_fees_usd", acc_.fee_usd),
                             ("lp_value_change_usd", dv),
                             ("volume_usd", acc_.volume_usd),
                             ("volume_in_range_usd", acc_.volume_in_range_usd),
                             ("n_swaps", acc_.n_swaps)):
                setattr(total, tgt, getattr(total, tgt) + val)
                setattr(bkt, tgt, getattr(bkt, tgt) + val)

        seg, prev_p, prev_t = mint_idx, mint_price, mint_tick
        v_prev = H.compute_position_value(mint_price, pl, pu, L)
        cycle_fees = 0.0

        h_lo = int(np.searchsorted(hour_ts, mint_epoch, side="right"))
        h_hi = int(np.searchsorted(hour_ts, exit_epoch, side="right"))
        for hh in range(h_lo, h_hi):
            h_epoch = int(hour_ts[hh])
            k = max(int(hour_idx[hh]), seg)
            hbk = bucket_for(h_epoch)

            acc_h = fee_engine.accrue_fees(
                swaps.iloc[seg + 1: k + 1], L, lo_t, hi_t, pl, pu,
                prev_price=prev_p, prev_v3_tick=prev_t,
                pool_fee=POOL_FEE, liquidity_scale=LIQ_SCALE, track_path=False,
            )
            p_h = float(hour_px[hh])
            v_h = H.compute_position_value(p_h, pl, pu, L)
            book(hbk, v_h - v_prev, acc_h)
            cycle_fees += acc_h.fee_usd
            pnl_check += (v_h - v_prev) + acc_h.fee_usd
            v_prev = v_h
            if k > seg:
                seg, prev_p, prev_t = k, float(prices[k]), int(ticks[k])

            mark_to(p_h, hbk)
            # Funding is charged hourly whatever the rehedge cadence, because
            # the exchange charges it hourly on whatever notional is open.
            if rehedge_hours > 0 and h_epoch % (rehedge_hours * 3600) == 0:
                rehedge(p_h, hbk)
            rate = funding.get(pd.Timestamp(h_epoch, unit="s", tz="UTC"))
            if rate is not None:
                # A positive hourly rate means longs pay shorts, so the short
                # RECEIVES. Same sign convention as gate1/replay_mode_a.
                f = rate * q * p_h
                total.funding_usd += f
                hbk.funding_usd += f

        # ---- tail of the cycle, then close it ------------------------------
        acc = fee_engine.accrue_fees(
            swaps.iloc[seg + 1: j + 1], L, lo_t, hi_t, pl, pu,
            prev_price=prev_p, prev_v3_tick=prev_t,
            pool_fee=POOL_FEE, liquidity_scale=LIQ_SCALE, track_path=False,
        )
        v_exit = H.compute_position_value(exit_price, pl, pu, L)
        book(bk, v_exit - v_prev, acc)
        cycle_fees += acc.fee_usd
        pnl_check += (v_exit - v_prev) + acc.fee_usd

        # IL and basket delta are cycle-level diagnostics, not P&L lines: the
        # identity runs on lp_value_change, which the two of them sum to.
        cyc = il_ledger.cycle_il(
            len(cycles), pd.Timestamp(mint_epoch, unit="s", tz="UTC"),
            pd.Timestamp(exit_epoch, unit="s", tz="UTC"),
            lo_t, hi_t, mint_price, exit_price,
            v0_usd=H.compute_position_value(mint_price, pl, pu, L),
        )
        for tgt, val in (("il_usd", cyc.il_usd),
                         ("basket_delta_usd", cyc.basket_delta_usd)):
            setattr(total, tgt, getattr(total, tgt) + val)
            setattr(bk, tgt, getattr(bk, tgt) + val)

        mark_to(exit_price, bk)

        if keep_cycles:
            cycles.append({
                "cycle": len(cycles),
                "mint_utc": str(pd.Timestamp(mint_epoch, unit="s", tz="UTC")),
                "exit_utc": str(pd.Timestamp(exit_epoch, unit="s", tz="UTC")),
                "hours": (exit_epoch - mint_epoch) / 3600.0,
                "lower_tick": lo_t, "upper_tick": hi_t,
                "price_entry": mint_price, "price_exit": exit_price,
                "L": L, "fees_usd": cycle_fees,
                "il_usd": cyc.il_usd, "basket_delta_usd": cyc.basket_delta_usd,
                "n_swaps_tail": acc.n_swaps,
                "mean_liquidity_share_tail": acc.mean_liquidity_share,
            })

        if not recenter:
            break

        # ---- recenter: burn, swap to the new mix, mint ---------------------
        v_pos = H.compute_position_value(exit_price, pl, pu, L)
        pot = v_pos + cycle_fees
        a0_old = il_ledger.position_amounts(exit_price, pl, pu, L)[0]

        center = (exit_tick // ENV.TICK_SPACING) * ENV.TICK_SPACING
        lo_t, hi_t = center - half, center + half
        pl, pu = H.v3_tick_to_price(lo_t), H.v3_tick_to_price(hi_t)

        # How much goes back in. `constant` re-mints the same $1,015 every time,
        # topping up or withdrawing the cycle's P&L, so $/day is a rate rather
        # than a decay path. `compound` re-mints whatever survived, which is
        # what a bot with no top-up would do — and which lets a losing arm run
        # its stake to zero, at which point a per-day average stops meaning
        # anything. See REPORT.md §"the notional convention".
        mint_capital = lp_capital if notional_mode == "constant" else pot
        if mint_capital <= 0:
            ruin = {"utc": str(pd.Timestamp(exit_epoch, unit="s", tz="UTC")),
                    "n_recenters": total.n_recenters, "pot_usd": pot}
            L = 0.0
            rehedge(exit_price, bk, target=0.0)
            break

        L_probe = H.compute_liquidity_from_capital(mint_capital, exit_price, pl, pu)
        a0_new = il_ledger.position_amounts(exit_price, pl, pu, L_probe)[0]
        swap_ntl = abs(a0_new - a0_old) * exit_price
        oc = CM.onchain_cost(swap_ntl, 1, 0, n_tx=ENV.TX_PER_RECENTER)

        total.onchain_cost_usd += oc.total_usd
        bk.onchain_cost_usd += oc.total_usd
        total.swapped_notional_usd += swap_ntl
        bk.swapped_notional_usd += swap_ntl
        total.n_recenters += 1
        bk.n_recenters += 1
        pnl_check -= oc.total_usd

        net_capital = (mint_capital if notional_mode == "constant"
                       else mint_capital - oc.total_usd)
        if net_capital <= 0:
            ruin = {"utc": str(pd.Timestamp(exit_epoch, unit="s", tz="UTC")),
                    "n_recenters": total.n_recenters, "pot_usd": pot}
            L = 0.0
            rehedge(exit_price, bk, target=0.0)
            break
        L = H.compute_liquidity_from_capital(net_capital, exit_price, pl, pu)
        rehedge(exit_price, bk)   # one trade, straight onto the new position

        mint_epoch, mint_price, mint_tick, mint_idx = (
            exit_epoch, exit_price, exit_tick, j)
        i = j

    # ---- final unwind: close the LP back to USDC and flatten the short -----
    fin_price = float(prices[n - 1])
    fin_epoch = int(ts_epoch[n - 1])
    fbk = bucket_for(fin_epoch)
    a0_fin = il_ledger.position_amounts(fin_price, pl, pu, L)[0]
    unwind_ntl = a0_fin * fin_price
    oc = CM.onchain_cost(unwind_ntl, 0, 1, n_tx=CM.TX_PER_EXIT)
    total.onchain_cost_usd += oc.total_usd
    fbk.onchain_cost_usd += oc.total_usd
    total.swapped_notional_usd += unwind_ntl
    fbk.swapped_notional_usd += unwind_ntl
    pnl_check -= oc.total_usd

    mark_to(fin_price, fbk)
    rehedge(fin_price, fbk, target=0.0)   # flatten the short

    span_h = (int(ts_epoch[n - 1]) - int(ts_epoch[0])) / 3600.0
    total.hours = span_h
    for lab, b in months.items():
        m0 = pd.Timestamp(lab + "-01", tz="UTC")
        m1 = m0 + pd.offsets.MonthBegin(1)
        s = max(m0, pd.Timestamp(int(ts_epoch[0]), unit="s", tz="UTC"))
        e = min(m1, pd.Timestamp(int(ts_epoch[n - 1]), unit="s", tz="UTC"))
        b.hours = max((e - s).total_seconds() / 3600.0, 0.0)

    # The decomposition must equal the directly-tracked LP value. If these ever
    # disagree, a P&L line is being double-counted or dropped.
    decomposed = (total.lp_value_change_usd
                  + total.lp_fees_usd - total.onchain_cost_usd)
    checks = {
        "notional_mode": notional_mode,
        "ruin": ruin,
        "lp_pnl_direct_usd": pnl_check,
        "lp_pnl_decomposed_usd": decomposed,
        "lp_value_abs_gap_usd": abs(pnl_check - decomposed),
        "il_plus_basket_minus_lpchange_usd": abs(
            total.il_usd + total.basket_delta_usd - total.lp_value_change_usd),
        "months_sum_minus_total_hours": abs(
            sum(b.hours for b in months.values()) - span_h),
    }

    return ArmResult(
        arm=f"always_in_w{width}", width=width, half_width_ticks=half,
        width_pct=ENV.width_pct(width), total=total,
        months={k: months[k] for k in sorted(months)},
        cycles=cycles, checks=checks,
    )


def always_cash(hours: float, months_hours: dict) -> ArmResult:
    """The zero line. Holding USDC earns nothing and costs nothing."""
    t = Bucket(label="total", hours=hours)
    return ArmResult(
        arm="always_cash", width=None, half_width_ticks=None, width_pct=None,
        total=t,
        months={k: Bucket(label=k, hours=v) for k, v in sorted(months_hours.items())},
    )


# --------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-05-01")
    ap.add_argument("--end", default="2026-08-28")
    ap.add_argument("--rehedge-hours", type=int, default=1,
                    help="hedge rebalance cadence in hours; 0 = only at "
                         "recenters. Identical across arms either way.")
    ap.add_argument("--detect-lag-hours", type=int, default=0,
                    help="0 = the pre-registered instant-recenter policy; "
                         "1 = sensitivity run on a 1h decision loop")
    ap.add_argument("--lp-capital", type=float, default=ENV.LP_CAPITAL_USD)
    ap.add_argument("--notional-mode", choices=["constant", "compound"],
                    default="constant",
                    help="constant: re-mint the same LP notional every cycle, so $/day is a rate. compound: re-mint what survived, which can run a losing arm to zero.")
    ap.add_argument("--tag", default=None)
    ap.add_argument("--keep-cycles", action="store_true")
    ap.add_argument("--swap-dir", default=None, help="override e003/data/swaps")
    args = ap.parse_args()

    tag = args.tag or (f"lag{args.detect_lag_hours}h_rh{args.rehedge_hours}h"
                       f"_{args.notional_mode}")
    out_dir = E003 / "out" / tag
    out_dir.mkdir(parents=True, exist_ok=True)

    swaps = load_swaps(args.start, args.end,
                       Path(args.swap_dir) if args.swap_dir else None)
    funding = load_funding()
    print(f"swaps: {len(swaps):,}  {swaps['ts'].iloc[0]} -> {swaps['ts'].iloc[-1]}")

    ts_epoch = swaps["timestamp"].to_numpy(dtype=np.int64)
    h0 = (int(ts_epoch[0]) // 3600 + 1) * 3600
    h1 = (int(ts_epoch[-1]) // 3600) * 3600
    hour_ts = np.arange(h0, h1 + 1, 3600, dtype=np.int64)
    hour_idx = np.searchsorted(ts_epoch, hour_ts, side="right") - 1
    hour_px = np.where(hour_idx >= 0,
                       swaps["price"].to_numpy()[np.clip(hour_idx, 0, None)], np.nan)
    n_missing_rate = sum(
        1 for h in hour_ts
        if funding.get(pd.Timestamp(int(h), unit="s", tz="UTC")) is None)
    print(f"hours: {len(hour_ts):,}  funding rates missing: {n_missing_rate}")

    results: list[ArmResult] = []
    for w in ENV.WIDTH_ARMS:
        r = run_arm(w, swaps, funding, hour_ts, hour_px, hour_idx,
                    args.detect_lag_hours, args.rehedge_hours,
                    args.lp_capital, args.notional_mode, args.keep_cycles)
        results.append(r)
        c = r.checks
        print(f"  W{w:<4d} ±{r.width_pct*100:6.3f}%  recenters={r.total.n_recenters:>6,} "
              f"fees=${r.total.lp_fees_usd:>9,.2f} IL=${r.total.il_usd:>10,.2f} "
              f"onchain=${r.total.onchain_cost_usd:>9,.2f} "
              f"central=${r.total.per_day(ENV.ENVELOPE_BY_NAME['central']):>8.3f}/day "
              f"[check {c['lp_value_abs_gap_usd']:.2e}]"
              + (f"  RUIN {c['ruin']['utc'][:10]}" if c.get("ruin") else ""))

    cash = always_cash(results[0].total.hours,
                       {k: b.hours for k, b in results[0].months.items()})
    results.append(cash)

    payload = {
        "experiment": "E003",
        "cost_model_version": CM.COST_MODEL_VERSION,
        "envelope_version": ENV.E003_ENVELOPE_VERSION,
        "window": {"start": args.start, "end": args.end,
                   "hours": results[0].total.hours,
                   "n_swaps": int(len(swaps)),
                   "first_swap_utc": str(swaps["ts"].iloc[0]),
                   "last_swap_utc": str(swaps["ts"].iloc[-1])},
        "policy": {
            "detect_lag_hours": args.detect_lag_hours,
            "rehedge_hours": args.rehedge_hours,
            "rule": "always in position; recenter when the pool tick leaves the "
                    "range; never EXIT; no dwell",
            "hedge": "short the LP position's ETH delta; rehedge on the "
                     "cadence below and at every recenter; the RATIO is "
                     "identical across arms and across envelope points",
            "lp_capital_usd": args.lp_capital,
            "notional_mode": args.notional_mode,
            "hedge_equity_usd": ENV.HEDGE_EQUITY_USD,
            "total_capital_usd": args.lp_capital + ENV.HEDGE_EQUITY_USD,
            "target_usd_per_day": ENV.TARGET_USD_PER_DAY,
            "tx_per_recenter": ENV.TX_PER_RECENTER,
        },
        "envelope": [
            {"name": p.name, "maker_share_notional": p.maker_share_notional,
             "fee_bps": p.fee_bps, "slippage_bps": p.slippage_bps,
             "chase_bps": p.chase_bps, "total_bps": p.total_bps}
            for p in ENV.ENVELOPE
        ],
        "arms": [],
    }
    for r in results:
        payload["arms"].append({
            "arm": r.arm, "width": r.width,
            "half_width_ticks": r.half_width_ticks, "width_pct": r.width_pct,
            "checks": r.checks,
            "total": {**asdict(r.total),
                      **{f"net_usd_{p.name}": r.total.net_usd(p) for p in ENV.ENVELOPE},
                      **{f"per_day_{p.name}": r.total.per_day(p) for p in ENV.ENVELOPE}},
            "months": {k: {**asdict(b),
                           **{f"net_usd_{p.name}": b.net_usd(p) for p in ENV.ENVELOPE},
                           **{f"per_day_{p.name}": b.per_day(p) for p in ENV.ENVELOPE}}
                       for k, b in r.months.items()},
        })
    (out_dir / "results.json").write_text(json.dumps(payload, indent=2))

    rows = []
    for r in results:
        for p in ENV.ENVELOPE:
            rows.append({
                "arm": r.arm, "width": r.width, "width_pct": r.width_pct,
                "envelope": p.name, "envelope_bps": p.total_bps,
                "window": "full", "hours": r.total.hours,
                "net_usd": r.total.net_usd(p), "per_day_usd": r.total.per_day(p),
                **{k: v for k, v in asdict(r.total).items() if k != "label"},
            })
            for lab, b in r.months.items():
                rows.append({
                    "arm": r.arm, "width": r.width, "width_pct": r.width_pct,
                    "envelope": p.name, "envelope_bps": p.total_bps,
                    "window": lab, "hours": b.hours,
                    "net_usd": b.net_usd(p), "per_day_usd": b.per_day(p),
                    **{k: v for k, v in asdict(b).items() if k != "label"},
                })
    pd.DataFrame(rows).to_csv(out_dir / "frontier.csv", index=False)

    if args.keep_cycles:
        for r in results:
            if r.cycles:
                pd.DataFrame(r.cycles).to_csv(out_dir / f"cycles_{r.arm}.csv", index=False)

    print(f"\nwrote {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
