#!/usr/bin/env python3
"""E011 stage 1 — the perfect-foresight timing upper bound on LINK/WETH 0.30%.

    nix develop .#gate1 -c python backtest_model_server/e011/oracle11.py

E006's construction (e006/oracle.py — its docstring carries the bound
argument, which transfers per leg), generalized to this venue's per-leg
two-short hedge and non-USD quote, at the $10k reference under E010's
measured mainnet gas envelope, COUPLED: the DP at envelope point g prices
switch costs with gas point g and HPL point g.

Per hour, as if freshly centered at the hour's start (over-credits, never
under-credits — the E006 bound direction, per leg):

    payoff_h = fees_h + funding_h + gamma_pnl_h

  fees_h      gate1 fee_engine over the hour's swaps, lp_fee_share 5/6,
              share-aware credit at the $7,147.89 LP notional
  funding_h   r_LINK,h × a0 × (p0·u0)  +  r_ETH,h × a1 × u0
              (both legs SHORT; positive rate credits the short)
  gamma_pnl_h [V(p1)·u1 − V(p0)·u0] + a0·(p0u0 − p1u1) + a1·(u0 − u1)
              (the two-leg hedged residual; reduces to E006's formula when
              the quote mark u is constant)

Switch costs per transition (full, frozen):
  enter[h]  = onchain(both-leg swap notional, 4 tx) + HPL(hedge open, 2 legs)
  exit[h+1] = onchain(unwind notional, 2 tx)       + HPL(hedge close)

DP: e006/oracle.py dp_select, unmodified, per coupled point.

Outputs: out/stage1_results.json, out/stage1_hours_<arm>.csv.
"""

from __future__ import annotations

import argparse
import time

import numpy as np
import pandas as pd

import common11 as C
from engine import cost_model as CM
from engine import fee_engine, harness as H, il_ledger


def hourly_payoffs(arm: dict, spec, swaps: pd.DataFrame, funding: dict,
                   marks, hs: np.ndarray, lp_capital: float) -> pd.DataFrame:
    ts = swaps["timestamp"].to_numpy(np.int64)
    prices = swaps["price"].to_numpy(np.float64)
    ticks = swaps["v3_tick"].to_numpy(np.int64)
    half = arm["half_ticks"]
    spacing = spec.tick_spacing
    n_hours = len(hs)

    idx0 = np.searchsorted(ts, hs, side="right") - 1
    idx1 = np.searchsorted(ts, hs + 3600, side="right") - 1

    fund0_map, fund1_map = funding[spec.coin0], funding[spec.coin1]
    cols = {k: np.zeros(n_hours) for k in
            ("p0", "p1", "u0", "u1", "fees_usd", "fund0_usd", "fund1_usd",
             "funding_usd", "gamma_pnl_usd", "payoff_usd",
             "ntl0_usd", "ntl1_usd", "enter_ntl_usd", "exit_ntl_usd")}
    n_missing = 0

    for h in range(n_hours):
        i0, i1 = int(idx0[h]), int(idx1[h])
        e0, e1 = int(hs[h]), int(hs[h]) + 3600
        p0, k0, p1 = float(prices[i0]), int(ticks[i0]), float(prices[i1])
        u0, u1 = R5_mark(marks, e0), R5_mark(marks, e1)
        center = (k0 // spacing) * spacing
        lo_t, hi_t = center - half, center + half
        pl = H.tick_to_price(H.v3_tick_to_human_tick(lo_t, spec.decimals0,
                                                     spec.decimals1))
        pu = H.tick_to_price(H.v3_tick_to_human_tick(hi_t, spec.decimals0,
                                                     spec.decimals1))
        L = H.compute_liquidity_from_capital(lp_capital / u0, p0, pl, pu)
        a0, a1 = il_ledger.position_amounts(p0, pl, pu, L)

        acc = fee_engine.accrue_fees(
            swaps.iloc[i0 + 1: i1 + 1], L, lo_t, hi_t, pl, pu,
            prev_price=p0, prev_v3_tick=k0,
            pool_fee=spec.pool_fee, liquidity_scale=spec.liq_scale,
            lp_fee_share=spec.lp_fee_share, track_path=False)

        v0 = H.compute_position_value(p0, pl, pu, L) * u0
        v1 = H.compute_position_value(p1, pl, pu, L) * u1
        m0, m1 = p0 * u0, u0
        gamma = (v1 - v0) + a0 * (p0 * u0 - p1 * u1) + a1 * (u0 - u1)

        key = pd.Timestamp(e0, unit="s", tz="UTC")
        r0, r1 = fund0_map.get(key), fund1_map.get(key)
        if r0 is None or r1 is None:
            n_missing += 1
        f0 = (r0 or 0.0) * a0 * m0
        f1 = (r1 or 0.0) * a1 * m1

        a0x, a1x = il_ledger.position_amounts(p1, pl, pu, L)
        cols["p0"][h], cols["p1"][h] = p0, p1
        cols["u0"][h], cols["u1"][h] = u0, u1
        cols["fees_usd"][h] = acc.fee_usd
        cols["fund0_usd"][h], cols["fund1_usd"][h] = f0, f1
        cols["funding_usd"][h] = f0 + f1
        cols["gamma_pnl_usd"][h] = gamma
        cols["payoff_usd"][h] = acc.fee_usd + f0 + f1 + gamma
        cols["ntl0_usd"][h], cols["ntl1_usd"][h] = a0 * m0, a1 * m1
        cols["enter_ntl_usd"][h] = a0 * m0 + a1 * m1
        cols["exit_ntl_usd"][h] = a0x * p1 * u1 + a1x * u1

    df = pd.DataFrame({"hour_epoch": hs, **cols})
    df.attrs["n_missing_rate"] = n_missing
    return df


def R5_mark(marks, epoch: int) -> float:
    return C.R5.mark_at(marks, epoch)


def switch_costs(hours: pd.DataFrame, point_name: str):
    """(enter[h], exit[b]) at the COUPLED point: gas at the chain's measured
    point, hedge legs at the same-named HPL point. onchain_cost reads
    CM.GAS_USD_PER_TX at call time, so the chain_gas patch prices the txs."""
    point = C.ENVELOPE_BY_NAME[point_name]
    n = len(hours)
    enter = np.zeros(n)
    exit_ = np.zeros(n + 1)
    en = hours["enter_ntl_usd"].to_numpy()
    ex = hours["exit_ntl_usd"].to_numpy()
    with C.chain_gas(point_name):
        for h in range(n):
            enter[h] = (CM.onchain_cost(en[h], 1, 0,
                                        n_tx=C.R.TX_PER_RECENTER).total_usd
                        + point.cost(en[h]))
            exit_[h + 1] = (CM.onchain_cost(ex[h], 0, 1,
                                            n_tx=CM.TX_PER_EXIT).total_usd
                            + point.cost(ex[h]))
    exit_[0] = float("inf")
    return enter, exit_


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    spec, swaps, funding, marks = C.load_all()
    ts = swaps["timestamp"].to_numpy(np.int64)
    hs = C.E6O.hour_grid(ts)
    days = C.window_days(swaps)
    C.OUT.mkdir(parents=True, exist_ok=True)
    print(f"{spec.slug}: {len(swaps):,} swaps  {len(hs):,} hours  "
          f"{days:.5f} days  lp_capital=${C.LP_CAPITAL:,.2f}")

    payload = {
        "experiment": "E011", "stage": 1,
        "cost_model_version": C.R.COST_MODEL_VERSION,
        "envelope_version": C.R.ENVELOPE_VERSION,
        "gas_source": "e010 measured mainnet envelope, coupled by point name",
        "window": {"start": C.R.WINDOW_START, "end": C.R.WINDOW_END,
                   "days": days, "n_swaps": int(len(swaps)),
                   "n_hours": int(len(hs))},
        "lp_capital_usd": C.LP_CAPITAL,
        "total_capital_usd": C.CAPITAL,
        "target_usd_per_day": C.TARGET_10PCT,
        "arms": {},
    }

    for arm in C.arms():
        label = arm["label"]
        csv = C.OUT / f"stage1_hours_{label}.csv"
        t0 = time.time()
        if csv.exists() and not args.force:
            hours = pd.read_csv(csv)
            n_missing = 0
            print(f"{label}: reusing {csv.name}")
        else:
            hours = hourly_payoffs(arm, spec, swaps, funding, marks, hs,
                                   C.LP_CAPITAL)
            n_missing = hours.attrs["n_missing_rate"]

        rec = {
            "label": label, "half_ticks": arm["half_ticks"],
            "width_pct": arm["actual_pct"],
            "n_missing_funding_rates": int(n_missing),
            "sum_fees_usd": float(hours["fees_usd"].sum()),
            "sum_funding_usd": float(hours["funding_usd"].sum()),
            "sum_gamma_pnl_usd": float(hours["gamma_pnl_usd"].sum()),
            "points": {},
        }
        for pn in C.POINTS:
            enter, exit_ = switch_costs(hours, pn)
            value, held = C.E6O.dp_select(hours["payoff_usd"].to_numpy(),
                                          enter, exit_)
            runs = C.E6O.streaks_of(held)
            alwaysin = float(-enter[0] + hours["payoff_usd"].sum()
                             - exit_[-1])
            lens = [j - i + 1 for i, j in runs]
            rec["points"][pn] = {
                "value_usd": float(value),
                "per_day_usd": float(value / days),
                "held_hours": int(held.sum()),
                "held_frac": float(held.mean()),
                "n_streaks": len(runs),
                "streak_len_median_h": float(np.median(lens)) if lens else 0.0,
                "streak_len_p90_h": float(np.percentile(lens, 90)) if lens else 0.0,
                "alwaysin_stage1_usd": alwaysin,
                "dominates_alwaysin": bool(value >= alwaysin),
                "dominates_alwayscash": bool(value >= 0.0),
                "mean_roundtrip_cost_usd": float(np.mean(
                    [enter[i] + exit_[j + 1] for i, j in runs])) if runs else 0.0,
            }
            hours[f"held_{pn}"] = held
        c = rec["points"]["central"]
        print(f"{label:<26s} UB central ${c['value_usd']:+9.2f} "
              f"(${c['per_day_usd']:+.3f}/d) held {c['held_frac']*100:.1f}% "
              f"in {c['n_streaks']} streaks (med {c['streak_len_median_h']:.0f}h) "
              f"[opt {rec['points']['optimistic']['per_day_usd']:+.3f} "
              f"pess {rec['points']['pessimistic']['per_day_usd']:+.3f}] "
              f"{time.time()-t0:.0f}s", flush=True)
        hours.to_csv(csv, index=False)
        payload["arms"][label] = rec

    best = max(payload["arms"].values(),
               key=lambda a: a["points"]["central"]["per_day_usd"])
    payload["best_arm_central"] = best["label"]
    payload["refuted_clause_fires"] = bool(all(
        a["points"]["central"]["per_day_usd"] < C.TARGET_10PCT
        for a in payload["arms"].values()))
    C.write_json(C.OUT / "stage1_results.json", payload)
    print(f"wrote {C.OUT/'stage1_results.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
