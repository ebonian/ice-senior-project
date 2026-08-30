#!/usr/bin/env python3
"""E005 — the pool screen's race: E003's mode-C simulator, pool-parameterized.

    nix develop .#gate1 -c python backtest_model_server/e005/race.py --slug <slug>

One variable vs E003: the VENUE. The policy, cost model (`gate1-2026-08-29`),
hedge envelope (`e003-2026-08-29`), window, LP notional ($1,015 constant
re-mint) and the primary loop (lag1h_rh1h) are all frozen at E003's values.

What generalizes, and only this:

  UNITS      the V3 math runs in the pool's own quote (token1) units, exactly
             as gate1 verified it; USD conversion happens at booking time on
             the 1 h grid, from committed Binance marks (`data/marks/`).
             For USD-quoted pools the mark is identically 1.0 and every line
             reduces bit-for-bit to E003's arithmetic.
  FEES       `fee_engine.accrue_fees` unmodified, with the pool's own fee tier
             and its measured LP fee share (slot0.feeProtocol + SetFeeProtocol
             scan — issue W). A mid-window fee change would apply piecewise;
             every 2026 candidate turned out constant, and this file refuses
             to run a pool whose schedule is not (fail fast, not degrade).
  HEDGE      per-leg: each non-stable leg's token delta is shorted on its own
             HL perp (ETH/USDC short ETH only — E003's exact case; WBTC/WETH
             shorts BTC and ETH). wstETH/weETH pools use the pre-registered
             ETH-beta exception: a near-static full-notional ETH short, reset
             only at recenters. Funding is replayed per perp from committed
             CSVs. Perp marks are pool-implied USD prices (pool price x quote
             mark), so hedged gamma is exactly the Ito residual of the pool's
             own price process.

The LP path and hedge-notional path are still simulated once per arm and
priced three ways by the envelope afterwards, so no envelope point can change
behaviour. The engine-extension validity gate: run on the control
(--slug weth_usdc_0p05 --swap-dir e003/data/swaps) this must reproduce E003's
lag1h_rh1h row within +-0.05 fees/gamma and +-5% net $/day (tests/).
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path

import numpy as np
import pandas as pd

E005 = Path(__file__).resolve().parent
BMS = E005.parent
GATE1 = BMS / "gate1"
for p in (str(GATE1), str(E005)):
    if p not in sys.path:
        sys.path.insert(0, p)
from engine import cost_model as CM  # noqa: E402
from engine import fee_engine, harness as H, il_ledger  # noqa: E402
import pools as P  # noqa: E402

ENVELOPE = P.ENVELOPE
FUND_DIR = E005 / "data" / "funding"
MARK_DIR = E005 / "data" / "marks"


# --------------------------------------------------------------------------
@dataclass
class PoolSpec:
    slug: str
    family: str
    address: str
    fee: int                  # uint24 (500 = 0.05%)
    tick_spacing: int
    decimals0: int
    decimals1: int
    token0: str
    token1: str
    lp_fee_share: float
    hedge_mode: str           # "per-leg" | "static-beta"
    coin0: str | None         # HL coin for token0 leg (None = unhedged stable)
    coin1: str | None
    quote_is_usd: bool

    @property
    def pool_fee(self) -> float:
        return self.fee / 1e6

    @property
    def liq_scale(self) -> float:
        return H.liquidity_scale(self.decimals0, self.decimals1)


def load_spec(slug: str) -> PoolSpec:
    rows = json.loads((E005 / "out" / "candidates.json").read_text())["candidates"]
    c = next((r for r in rows if r["slug"] == slug), None)
    if c is None or c["status"] != "RESOLVED":
        raise SystemExit(f"{slug} is not a RESOLVED candidate")
    shares = {round(s["lp_fee_share"], 10) for s in c["lp_fee_share_schedule"]}
    if len(shares) != 1:
        raise NotImplementedError(
            f"{slug}: lp_fee_share changed mid-window {c['lp_fee_share_schedule']}"
            " — piecewise accrual required; refusing to run with a scalar")
    legs = c["legs"]
    beta = any(v.get("hedge") == "eth-beta" for v in legs.values())
    coin0 = legs["token0"].get("hl_coin") if legs["token0"]["hedge"] != "stable-unhedged" else None
    coin1 = legs["token1"].get("hl_coin") if legs["token1"]["hedge"] != "stable-unhedged" else None
    return PoolSpec(
        slug=slug, family=c["family"], address=c["address"], fee=c["fee"],
        tick_spacing=c["pool_state"]["tick_spacing"],
        decimals0=c["decimals0"], decimals1=c["decimals1"],
        token0=c["token0_symbol"], token1=c["token1_symbol"],
        lp_fee_share=shares.pop(),
        hedge_mode="static-beta" if beta else "per-leg",
        coin0=coin0, coin1=coin1,
        quote_is_usd=c["token1_symbol"] in P.STABLES,
    )


BINANCE_FOR = {"WETH": "ethusdt", "ARB": "arbusdt", "LINK": "linkusdt",
               "WBTC": "btcusdt"}


def load_marks(token1: str) -> tuple[np.ndarray, np.ndarray] | None:
    """(epoch_s ascending, USD open at that hour) for the quote token."""
    if token1 in P.STABLES:
        return None
    f = MARK_DIR / f"binance_{BINANCE_FOR[token1]}_1h.csv"
    m = pd.read_csv(f)
    return (m["open_time_ms"].to_numpy(np.int64) // 1000,
            m["open"].to_numpy(np.float64))


def mark_at(marks, epoch: int) -> float:
    if marks is None:
        return 1.0
    t, v = marks
    i = int(np.searchsorted(t, epoch, side="right")) - 1
    if i < 0:
        raise ValueError(f"no USD mark at or before epoch {epoch}")
    return float(v[i])


def load_funding_csv(coin: str) -> dict:
    f = pd.read_csv(FUND_DIR / f"hl_funding_{coin.lower()}_hourly.csv")
    ts = pd.to_datetime(f["time_ms"], unit="ms", utc=True).dt.floor("h")
    return dict(zip(ts, pd.to_numeric(f["funding_rate_hourly"])))


def load_funding_bot_eth() -> dict:
    """E003's exact ETH funding loader — used for the control reproduction so
    the control row shares E003's input byte-for-byte (the HL API pull matches
    it exactly; funding.py asserts that)."""
    f = pd.read_csv("/home/poon/developments/llaminet/bot/analysis/strategy-review/"
                    "data/hl_funding_eth_hourly.csv")
    ts = pd.to_datetime(f["iso_utc"], utc=True, format="mixed").dt.floor("h")
    return dict(zip(ts, pd.to_numeric(f["funding_rate_hourly"])))


def load_swaps(spec: PoolSpec, start: str, end: str, marks,
               swap_dir: Path | None) -> pd.DataFrame:
    d = swap_dir or (E005 / "data" / "swaps" / spec.slug)
    files = sorted(d.glob("*.parquet"))
    files = [f for f in files if not f.name.endswith(".raw.parquet")]
    if not files:
        raise FileNotFoundError(f"no swap parquets in {d}")
    df = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
    df = df.sort_values(["block_number", "log_index"]).reset_index(drop=True)
    df["ts"] = pd.to_datetime(df["timestamp"], unit="s", utc=True)
    t0, t1 = pd.Timestamp(start, tz="UTC"), pd.Timestamp(end, tz="UTC")
    df = df[(df["ts"] >= t0) & (df["ts"] < t1)].reset_index(drop=True)
    df["v3_tick"] = df["tick"].astype(np.int64)
    if "vol_token1" in df.columns:
        if marks is None:
            df["volume_usd"] = df["vol_token1"]
        else:
            t, v = marks
            idx = np.searchsorted(t, df["timestamp"].to_numpy(np.int64) // 3600 * 3600,
                                  side="right") - 1
            if (idx < 0).any():
                raise ValueError("swaps before first USD mark")
            df["volume_usd"] = df["vol_token1"].to_numpy() * v[idx]
    elif "volume_usd" not in df.columns:
        raise ValueError("parquet has neither vol_token1 nor volume_usd")
    return df


def first_exit(ticks: np.ndarray, start: int, lo: int, hi: int) -> int | None:
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
    """Every P&L line for one sub-window. All USD. Signs as booked.
    Identical to E003's Bucket, including the envelope pricing."""
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

    def net_usd(self, point) -> float:
        return (self.lp_value_change_usd + self.lp_fees_usd
                - self.onchain_cost_usd + self.hedge_price_pnl_usd
                + self.funding_usd - point.cost(self.rehedge_notional_usd))

    def per_day(self, point) -> float:
        d = self.hours / 24.0
        return self.net_usd(point) / d if d > 0 else float("nan")


@dataclass
class ArmResult:
    arm: str
    half_width_ticks: int | None
    width_pct: float | None
    target_pcts: list | None
    total: Bucket
    months: dict = field(default_factory=dict)
    checks: dict = field(default_factory=dict)


# --------------------------------------------------------------------------
def run_arm(spec: PoolSpec, arm: dict, swaps: pd.DataFrame, funding: dict,
            marks, hour_ts: np.ndarray, hour_px: np.ndarray,
            hour_idx: np.ndarray, detect_lag_hours: int, rehedge_hours: int,
            lp_capital: float) -> ArmResult:
    """One width arm over the whole window. Structure follows e003/race.py
    run_arm line for line; every generalized step is marked."""
    ticks = swaps["v3_tick"].to_numpy(dtype=np.int64)
    prices = swaps["price"].to_numpy(dtype=np.float64)
    ts_epoch = swaps["timestamp"].to_numpy(dtype=np.int64)
    n = len(swaps)
    half = arm["half_ticks"]
    spacing = spec.tick_spacing
    pool_fee = spec.pool_fee
    liq_scale = spec.liq_scale
    lp_share = spec.lp_fee_share

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
    e0 = int(ts_epoch[0])
    u0 = mark_at(marks, e0)                      # quote-token USD mark
    center = (t0tick // spacing) * spacing
    lo_t, hi_t = center - half, center + half
    pl, pu = (H.tick_to_price(H.v3_tick_to_human_tick(lo_t, spec.decimals0, spec.decimals1)),
              H.tick_to_price(H.v3_tick_to_human_tick(hi_t, spec.decimals0, spec.decimals1)))

    # Entry swap: from 100% USD. The token0 leg is always acquired by swap;
    # a volatile quote leg must be too (for USD-quoted pools that term is 0,
    # which is E003's exact arithmetic).
    cap_t1 = lp_capital / u0
    L_probe = H.compute_liquidity_from_capital(cap_t1, p0, pl, pu)
    a0_t, a1_t = il_ledger.position_amounts(p0, pl, pu, L_probe)
    entry_ntl = a0_t * p0 * u0 + (0.0 if spec.quote_is_usd else a1_t * u0)
    entry_cost = CM.onchain_cost(entry_ntl, 1, 0, n_tx=P.TX_PER_RECENTER)
    L = H.compute_liquidity_from_capital((lp_capital - entry_cost.total_usd) / u0,
                                         p0, pl, pu)
    total.onchain_cost_usd += entry_cost.total_usd
    total.swapped_notional_usd += entry_ntl
    b0 = bucket_for(e0)
    b0.onchain_cost_usd += entry_cost.total_usd
    b0.swapped_notional_usd += entry_ntl

    # --- hedge state: up to two legs, each shorted on its own perp ----------
    # leg marks in USD: leg0 = pool price x quote mark, leg1 = quote mark.
    # static-beta: one ETH leg, q = position value in WETH terms (= USD value
    # / ETH price, since the quote IS WETH), reset only at (re)mints.
    def leg_marks(price: float, u: float) -> tuple[float, float]:
        return price * u, u

    def targets(price: float, u: float) -> tuple[float, float]:
        a0, a1 = il_ledger.position_amounts(price, pl, pu, L)
        if spec.hedge_mode == "static-beta":
            return H.compute_position_value(price, pl, pu, L), 0.0
        return (a0 if spec.coin0 else 0.0), (a1 if spec.coin1 else 0.0)

    q0, q1 = targets(p0, u0)
    m0_mark, m1_mark = leg_marks(p0, u0)
    if spec.hedge_mode == "static-beta":
        m0_mark = u0          # the beta leg is marked on ETH USD directly
    ntl0 = abs(q0) * m0_mark + abs(q1) * m1_mark
    total.rehedge_notional_usd += ntl0
    b0.rehedge_notional_usd += ntl0
    total.n_rehedges += 1
    b0.n_rehedges += 1

    mint_epoch, mint_price, mint_tick, mint_idx = e0, p0, t0tick, 0
    ruin = None
    pnl_check = -entry_cost.total_usd

    def mark_to(price: float, u: float, bk: Bucket) -> None:
        nonlocal m0_mark, m1_mark
        n0, n1 = leg_marks(price, u)
        if spec.hedge_mode == "static-beta":
            n0 = u
        pnl = q0 * (m0_mark - n0) + q1 * (m1_mark - n1)
        total.hedge_price_pnl_usd += pnl
        bk.hedge_price_pnl_usd += pnl
        m0_mark, m1_mark = n0, n1

    def rehedge(price: float, u: float, bk: Bucket, flatten: bool = False) -> None:
        nonlocal q0, q1
        t0_, t1_ = (0.0, 0.0) if flatten else targets(price, u)
        ntl = abs(t0_ - q0) * m0_mark + abs(t1_ - q1) * m1_mark
        total.rehedge_notional_usd += ntl
        bk.rehedge_notional_usd += ntl
        total.n_rehedges += 1
        bk.n_rehedges += 1
        q0, q1 = t0_, t1_

    fund0 = funding.get(spec.coin0) if spec.coin0 else None
    fund1 = funding.get(spec.coin1) if spec.coin1 else None
    if spec.hedge_mode == "static-beta":
        fund0, fund1 = funding["ETH"], None

    while i < n - 1:
        j = first_exit(ticks, i, lo_t, hi_t)
        if j is None:
            j = n - 1
            recenter = False
        else:
            recenter = True

        if recenter and detect_lag_hours > 0:
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
                    i = max(k, i + 1)
                    continue
            j = k

        exit_epoch = int(ts_epoch[j])
        exit_price = float(prices[j])
        exit_tick = int(ticks[j])
        bk = bucket_for(exit_epoch)

        def book(bkt: Bucket, dv: float, acc_) -> None:
            for tgt, val in (("lp_fees_usd", acc_.fee_usd),
                             ("lp_value_change_usd", dv),
                             ("volume_usd", acc_.volume_usd),
                             ("volume_in_range_usd", acc_.volume_in_range_usd),
                             ("n_swaps", acc_.n_swaps)):
                setattr(total, tgt, getattr(total, tgt) + val)
                setattr(bkt, tgt, getattr(bkt, tgt) + val)

        seg, prev_p, prev_t = mint_idx, mint_price, mint_tick
        u_prev = mark_at(marks, mint_epoch)
        v_prev = H.compute_position_value(mint_price, pl, pu, L) * u_prev
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
                pool_fee=pool_fee, liquidity_scale=liq_scale,
                lp_fee_share=lp_share, track_path=False)
            p_h = float(hour_px[hh])
            u_h = mark_at(marks, h_epoch)
            v_h = H.compute_position_value(p_h, pl, pu, L) * u_h
            book(hbk, v_h - v_prev, acc_h)
            cycle_fees += acc_h.fee_usd
            pnl_check += (v_h - v_prev) + acc_h.fee_usd
            v_prev = v_h
            if k > seg:
                seg, prev_p, prev_t = k, float(prices[k]), int(ticks[k])

            mark_to(p_h, u_h, hbk)
            if (rehedge_hours > 0 and h_epoch % (rehedge_hours * 3600) == 0
                    and spec.hedge_mode != "static-beta"):
                rehedge(p_h, u_h, hbk)
            for rate_map, q, mk in ((fund0, q0, m0_mark), (fund1, q1, m1_mark)):
                if rate_map is None or q == 0.0:
                    continue
                rate = rate_map.get(pd.Timestamp(h_epoch, unit="s", tz="UTC"))
                if rate is not None:
                    f = rate * q * mk
                    total.funding_usd += f
                    hbk.funding_usd += f

        acc = fee_engine.accrue_fees(
            swaps.iloc[seg + 1: j + 1], L, lo_t, hi_t, pl, pu,
            prev_price=prev_p, prev_v3_tick=prev_t,
            pool_fee=pool_fee, liquidity_scale=liq_scale,
            lp_fee_share=lp_share, track_path=False)
        u_exit = mark_at(marks, exit_epoch)
        v_exit = H.compute_position_value(exit_price, pl, pu, L) * u_exit
        book(bk, v_exit - v_prev, acc)
        cycle_fees += acc.fee_usd
        pnl_check += (v_exit - v_prev) + acc.fee_usd

        # IL / basket-delta diagnostics, in quote units scaled to USD at exit
        cyc = il_ledger.cycle_il(
            0, pd.Timestamp(mint_epoch, unit="s", tz="UTC"),
            pd.Timestamp(exit_epoch, unit="s", tz="UTC"),
            lo_t, hi_t, mint_price, exit_price,
            v0_usd=H.compute_position_value(mint_price, pl, pu, L),
            decimals0=spec.decimals0, decimals1=spec.decimals1)
        for tgt, val in (("il_usd", cyc.il_usd * u_exit),
                         ("basket_delta_usd", cyc.basket_delta_usd * u_exit)):
            setattr(total, tgt, getattr(total, tgt) + val)
            setattr(bk, tgt, getattr(bk, tgt) + val)

        mark_to(exit_price, u_exit, bk)

        if not recenter:
            break

        # ---- recenter: burn, swap to the new mix, mint ---------------------
        v_pos_t1 = H.compute_position_value(exit_price, pl, pu, L)
        a0_old = il_ledger.position_amounts(exit_price, pl, pu, L)[0]

        center = (exit_tick // spacing) * spacing
        lo_t, hi_t = center - half, center + half
        pl = H.tick_to_price(H.v3_tick_to_human_tick(lo_t, spec.decimals0, spec.decimals1))
        pu = H.tick_to_price(H.v3_tick_to_human_tick(hi_t, spec.decimals0, spec.decimals1))

        mint_capital_t1 = lp_capital / u_exit         # constant re-mint
        L_probe = H.compute_liquidity_from_capital(mint_capital_t1, exit_price, pl, pu)
        a0_new = il_ledger.position_amounts(exit_price, pl, pu, L_probe)[0]
        swap_ntl = abs(a0_new - a0_old) * exit_price * u_exit
        oc = CM.onchain_cost(swap_ntl, 1, 0, n_tx=P.TX_PER_RECENTER)

        total.onchain_cost_usd += oc.total_usd
        bk.onchain_cost_usd += oc.total_usd
        total.swapped_notional_usd += swap_ntl
        bk.swapped_notional_usd += swap_ntl
        total.n_recenters += 1
        bk.n_recenters += 1
        pnl_check -= oc.total_usd

        L = H.compute_liquidity_from_capital(mint_capital_t1, exit_price, pl, pu)
        rehedge(exit_price, u_exit, bk)

        mint_epoch, mint_price, mint_tick, mint_idx = (
            exit_epoch, exit_price, exit_tick, j)
        i = j

    # ---- final unwind ------------------------------------------------------
    fin_price = float(prices[n - 1])
    fin_epoch = int(ts_epoch[n - 1])
    u_fin = mark_at(marks, fin_epoch)
    fbk = bucket_for(fin_epoch)
    a0_fin, a1_fin = il_ledger.position_amounts(fin_price, pl, pu, L)
    unwind_ntl = a0_fin * fin_price * u_fin + (0.0 if spec.quote_is_usd
                                               else a1_fin * u_fin)
    oc = CM.onchain_cost(unwind_ntl, 0, 1, n_tx=CM.TX_PER_EXIT)
    total.onchain_cost_usd += oc.total_usd
    fbk.onchain_cost_usd += oc.total_usd
    total.swapped_notional_usd += unwind_ntl
    fbk.swapped_notional_usd += unwind_ntl
    pnl_check -= oc.total_usd

    mark_to(fin_price, u_fin, fbk)
    rehedge(fin_price, u_fin, fbk, flatten=True)

    span_h = (int(ts_epoch[n - 1]) - int(ts_epoch[0])) / 3600.0
    total.hours = span_h
    for lab, b in months.items():
        m0 = pd.Timestamp(lab + "-01", tz="UTC")
        m1 = m0 + pd.offsets.MonthBegin(1)
        s = max(m0, pd.Timestamp(int(ts_epoch[0]), unit="s", tz="UTC"))
        e = min(m1, pd.Timestamp(int(ts_epoch[n - 1]), unit="s", tz="UTC"))
        b.hours = max((e - s).total_seconds() / 3600.0, 0.0)

    decomposed = (total.lp_value_change_usd
                  + total.lp_fees_usd - total.onchain_cost_usd)
    checks = {
        "ruin": ruin,
        "lp_pnl_direct_usd": pnl_check,
        "lp_pnl_decomposed_usd": decomposed,
        "lp_value_abs_gap_usd": abs(pnl_check - decomposed),
        "months_sum_minus_total_hours": abs(
            sum(b.hours for b in months.values()) - span_h),
    }
    return ArmResult(
        arm=arm["label"], half_width_ticks=half, width_pct=arm["actual_pct"],
        target_pcts=arm["target_pcts"], total=total,
        months={k: months[k] for k in sorted(months)}, checks=checks)


def always_cash(hours: float, months_hours: dict) -> ArmResult:
    t = Bucket(label="total", hours=hours)
    return ArmResult(arm="always_cash", half_width_ticks=None, width_pct=None,
                     target_pcts=None, total=t,
                     months={k: Bucket(label=k, hours=v)
                             for k, v in sorted(months_hours.items())})


# --------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", required=True)
    ap.add_argument("--start", default=P.WINDOW_START)
    ap.add_argument("--end", default=P.WINDOW_END)
    ap.add_argument("--detect-lag-hours", type=int, default=1)
    ap.add_argument("--rehedge-hours", type=int, default=1,
                    help="0 = rehedge only at recenters (sensitivity)")
    ap.add_argument("--lp-capital", type=float, default=P.LP_CAPITAL_USD)
    ap.add_argument("--swap-dir", default=None,
                    help="override swap parquet dir (control: e003/data/swaps)")
    ap.add_argument("--funding-source", choices=["e005", "bot-eth"], default="e005",
                    help="bot-eth = E003's exact ETH funding CSV (control repro)")
    ap.add_argument("--tag", default=None)
    args = ap.parse_args()

    spec = load_spec(args.slug)
    marks = load_marks(spec.token1)
    funding: dict = {}
    for coin in {spec.coin0, spec.coin1, "ETH" if spec.hedge_mode == "static-beta" else None}:
        if coin:
            funding[coin] = (load_funding_bot_eth()
                             if (args.funding_source == "bot-eth" and coin == "ETH")
                             else load_funding_csv(coin))

    swaps = load_swaps(spec, args.start, args.end, marks,
                       Path(args.swap_dir) if args.swap_dir else None)
    print(f"{spec.slug}: {len(swaps):,} swaps  {swaps['ts'].iloc[0]} -> "
          f"{swaps['ts'].iloc[-1]}  hedge={spec.hedge_mode} "
          f"coins=({spec.coin0},{spec.coin1}) lp_share={spec.lp_fee_share:.4f}")

    ts_epoch = swaps["timestamp"].to_numpy(dtype=np.int64)
    h0 = (int(ts_epoch[0]) // 3600 + 1) * 3600
    h1 = (int(ts_epoch[-1]) // 3600) * 3600
    hour_ts = np.arange(h0, h1 + 1, 3600, dtype=np.int64)
    hour_idx = np.searchsorted(ts_epoch, hour_ts, side="right") - 1
    hour_px = np.where(hour_idx >= 0,
                       swaps["price"].to_numpy()[np.clip(hour_idx, 0, None)], np.nan)

    tag = args.tag or f"lag{args.detect_lag_hours}h_rh{args.rehedge_hours}h"
    out_dir = E005 / "out" / spec.slug / tag
    out_dir.mkdir(parents=True, exist_ok=True)

    arms = P.arms_for_spacing(spec.tick_spacing)
    results: list[ArmResult] = []
    for arm in arms:
        r = run_arm(spec, arm, swaps, funding, marks, hour_ts, hour_px,
                    hour_idx, args.detect_lag_hours, args.rehedge_hours,
                    args.lp_capital)
        results.append(r)
        t = r.total
        gam = t.lp_value_change_usd + t.hedge_price_pnl_usd
        fg = t.lp_fees_usd / abs(gam) if gam else float("nan")
        print(f"  {r.arm:<24s} +-{r.width_pct*100:5.2f}% rec={t.n_recenters:>5,} "
              f"fees=${t.lp_fees_usd:>9,.2f} gamma=${gam:>10,.2f} f/g={fg:5.3f} "
              f"central=${t.per_day(P.ENVELOPE_BY_NAME['central']):>8.3f}/d "
              f"[chk {r.checks['lp_value_abs_gap_usd']:.1e}]", flush=True)

    cash = always_cash(results[0].total.hours,
                       {k: b.hours for k, b in results[0].months.items()})
    results.append(cash)

    payload = {
        "experiment": "E005",
        "pool": {"slug": spec.slug, "family": spec.family,
                 "address": spec.address, "fee": spec.fee,
                 "tick_spacing": spec.tick_spacing,
                 "token0": spec.token0, "token1": spec.token1,
                 "lp_fee_share": spec.lp_fee_share,
                 "hedge_mode": spec.hedge_mode,
                 "coins": [spec.coin0, spec.coin1],
                 "quote_is_usd": spec.quote_is_usd},
        "cost_model_version": CM.COST_MODEL_VERSION,
        "envelope_version": P.ENVELOPE_VERSION,
        "funding_source": args.funding_source,
        "window": {"start": args.start, "end": args.end,
                   "hours": results[0].total.hours,
                   "n_swaps": int(len(swaps)),
                   "first_swap_utc": str(swaps["ts"].iloc[0]),
                   "last_swap_utc": str(swaps["ts"].iloc[-1])},
        "policy": {
            "detect_lag_hours": args.detect_lag_hours,
            "rehedge_hours": args.rehedge_hours,
            "lp_capital_usd": args.lp_capital,
            "notional_mode": "constant",
            "hedge_equity_usd": P.HEDGE_EQUITY_USD,
            "total_capital_usd": args.lp_capital + P.HEDGE_EQUITY_USD,
            "target_usd_per_day": P.TARGET_USD_PER_DAY,
            "tx_per_recenter": P.TX_PER_RECENTER,
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

    rows = []
    for r in results:
        for p in ENVELOPE:
            for win, b in [("full", r.total)] + list(r.months.items()):
                rows.append({
                    "arm": r.arm, "half_width_ticks": r.half_width_ticks,
                    "width_pct": r.width_pct, "envelope": p.name,
                    "envelope_bps": p.total_bps, "window": win, "hours": b.hours,
                    "net_usd": b.net_usd(p), "per_day_usd": b.per_day(p),
                    **{k: v for k, v in asdict(b).items() if k != "label"}})
    pd.DataFrame(rows).to_csv(out_dir / "frontier.csv", index=False)
    print(f"wrote {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
