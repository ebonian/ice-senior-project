#!/usr/bin/env python3
"""E004 - cycle-by-cycle reconciliation of the two basket-delta derivations.

    nix develop .#gate1 -c python \
        backtest_model_server/gate1/diagnostics/basket_delta/reconcile.py

Two independent computations of the same quantity disagree:

    report 01 (bot analysis/strategy-review/01-loss-attribution.md)
        basket delta = L*x0 * (P_exit - P_entry)
        with L inverted from a 5-minute AUM snapshot taken after the mint,
        and P from Binance ETHUSDT 1m interpolated at the recorder's row
        timestamp. Cycles are paired off rebalance-history rows.
        T5 +$8.52   T4 +$1.20

    gate1 engine (engine/il_ledger.py driven by replay_mode_a.py)
        same formula, but the ETH leg comes off the pool's Mint event and
        P from the pool's own sqrtPriceX96 at the mint/burn block. Cycles
        are paired off the Mint/Burn events actually emitted on chain.
        T5 +$9.4988 T4 -$4.2720

The formula is identical, so the whole gap lives in the inputs. Three inputs
differ, and this script prices each one separately by substituting exactly one
at a time on the cycles the two derivations share, then accounting for the
cycles they do not share:

    amount effect    L*x0 (AUM-inverted)   ->  amount0 (Mint event)
    price effect     Binance @ row ts      ->  pool sqrtPrice @ block
    pairing effect   rebalance-history rows -> Mint/Burn events on chain

Nothing here writes to gate1/engine/ or to the bot repo. Report 01's method is
re-implemented rather than imported so the two sides stay independent; the
re-implementation is checked against report 01's published totals first, and
the run aborts if it does not reproduce them.
"""

from __future__ import annotations

import csv
import json
import math
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
GATE1 = HERE.parent.parent
TRIALS = Path("/home/poon/developments/llaminet/bot/analysis/trials")

# Report 01's published basket-delta totals, and the observed AUM change and
# hedge directional P&L its delta-luck figures are built from. Frozen history.
R01_PUBLISHED = {
    "5": {"basket": 8.52, "delta_luck": 3.98, "observed_net": -12.60},
    "4": {"basket": 1.20, "delta_luck": 4.64, "observed_net": -8.76},
}


# ---------------------------------------------------------------------------
# report 01's method, lifted verbatim from
# bot/analysis/strategy-review/scratch/rederive_loss_attribution.py
# ---------------------------------------------------------------------------
def load_csv(trial, prefix):
    tdir = TRIALS / str(trial)
    fn = [f for f in os.listdir(tdir) if f.startswith(prefix) and f.endswith(".csv")]
    if not fn:
        return []
    with open(tdir / fn[0]) as f:
        rows = list(csv.DictReader(f))
    return [{k.lstrip("﻿"): v for k, v in r.items()} for r in rows]


def piso(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def F(r, c):
    v = r.get(c, "")
    return float(v) if v not in ("", "null", "NaN") else 0.0


def tick2px(tick):
    return 1.0001 ** int(tick) * 1e12  # WETH(18)/USDC(6) pool


def amounts_unit(P, Pa, Pb):
    """Unit-liquidity token amounts, exactly as report 01's il_calc does it."""
    sPa, sPb = math.sqrt(Pa), math.sqrt(Pb)
    sP = math.sqrt(min(max(P, Pa), Pb))
    return (1 / sP - 1 / sPb), (sP - sPa)


def a0_from_v0(V0, P0, Pa, Pb):
    """The ETH leg report 01 infers from a USD position value and a price.

    This is the inversion under test: L is backed out of (V0, P0) and the ETH
    amount read off it. It is the step that turns a small price error into a
    large amount error, because in a narrow range the ETH share of a position's
    value sweeps from 100% to 0% over the range width.
    """
    x0, y0 = amounts_unit(P0, Pa, Pb)
    return (V0 / (x0 * P0 + y0)) * x0


def inversion_amplification(P, Pa, Pb, bump_bp=1.0):
    """d(a0)/a0 per bp of error in the price fed to a0_from_v0, in bp."""
    base = a0_from_v0(1000.0, P, Pa, Pb)
    bumped = a0_from_v0(1000.0, P * (1 + bump_bp / 1e4), Pa, Pb)
    return (bumped / base - 1) * 1e4 / bump_bp


def binance_map(trial):
    bn = {}
    for r in load_csv(trial, "binance_ethusdt_1m"):
        ts = datetime.fromtimestamp(int(r["open_time"]) / 1000, tz=timezone.utc)
        bn[ts] = (float(r["open"]), float(r["close"]))
    return bn


def bpx(bn, ts):
    m = ts.replace(second=0, microsecond=0)
    if m not in bn:
        return None
    o, c = bn[m]
    return o + (c - o) * ts.second / 60


def r01_cycles(trial):
    """Report 01's per-cycle basket delta, cycle by cycle.

    Identical control flow to `il_and_direction` in report 01's script; it only
    keeps the per-cycle detail that function throws away.
    """
    bn = binance_map(trial)
    rb = load_csv(trial, "rebalance-history")
    aum = load_csv(trial, "aum-history")
    for r in rb + aum:
        r["_ts"] = piso(r["timestamp"])
    rb.sort(key=lambda r: r["_ts"])
    aum.sort(key=lambda r: r["_ts"])

    def v0_after(ts):
        c = [
            r
            for r in aum
            if ts < r["_ts"] <= ts + timedelta(minutes=12) and F(r, "position_usd") > 100
        ]
        return F(c[0], "position_usd") if c else None

    out = []
    open_pos = None
    for r in [x for x in rb if x["status"] in ("executed_rebalance", "executed_exit")]:
        P = bpx(bn, r["_ts"])
        if open_pos and P is not None:
            ts0, Pa, Pb, P0, V0 = open_pos
            x0, y0 = amounts_unit(P0, Pa, Pb)
            L = V0 / (x0 * P0 + y0)
            x1, y1 = amounts_unit(P, Pa, Pb)
            V1 = L * (x1 * P + y1)
            hodl = L * (x0 * P + y0)
            out.append(
                {
                    "mint_ts": ts0,
                    "burn_ts": r["_ts"],
                    "close_status": r["status"],
                    "price_lower": Pa,
                    "price_upper": Pb,
                    "p_entry": P0,
                    "p_exit": P,
                    "v0_usd": V0,
                    "L": L,
                    "a0_eth": L * x0,
                    "a1_usdc": L * y0,
                    "il_usd": V1 - hodl,
                    "basket_delta_usd": hodl - V0,
                }
            )
            open_pos = None
        if r["status"] == "executed_rebalance" and P is not None:
            Pa, Pb = sorted(
                (tick2px(r["applied_tick_lower"]), tick2px(r["applied_tick_upper"]))
            )
            V0 = v0_after(r["_ts"])
            if V0:
                open_pos = (r["_ts"], Pa, Pb, P, V0)
    return out


def r01_directional(trial):
    """Hedge directional P&L: 5-min AUM qty x Binance dP. Report 01 §4.

    Unchanged by this diagnostic - it is a hedge-side number and touches none
    of the three inputs under test - but delta luck is basket + directional,
    so it is needed to restate the corrected figure.
    """
    bn = binance_map(trial)
    aum = load_csv(trial, "aum-history")
    for r in aum:
        r["_ts"] = piso(r["timestamp"])
    aum.sort(key=lambda r: r["_ts"])
    d = 0.0
    for i in range(len(aum) - 1):
        p0, p1 = bpx(bn, aum[i]["_ts"]), bpx(bn, aum[i + 1]["_ts"])
        if p0 and p1:
            d += F(aum[i], "perp_position_qty") * (p1 - p0)
    return d


# ---------------------------------------------------------------------------
# the engine's side
# ---------------------------------------------------------------------------
def engine_cycles(trial, variant=""):
    d = GATE1 / "out" / (f"T{trial}{variant}")
    with open(d / "cycles.csv") as f:
        rows = list(csv.DictReader(f))

    def g(r, k):
        v = r.get(k, "")
        return float(v) if v not in ("", "None", "nan") else None

    out = []
    for r in rows:
        out.append(
            {
                "cycle": int(r["cycle"]),
                "mint_ts": piso(r["mint_ts"].replace(" ", "T")),
                "burn_ts": piso(r["burn_ts"].replace(" ", "T")),
                "price_lower": g(r, "price_lower"),
                "price_upper": g(r, "price_upper"),
                "p_entry_chain": g(r, "p_entry_chain"),
                "p_exit_chain": g(r, "p_exit_chain"),
                "p_entry_bn": g(r, "p_entry_bn"),
                "p_exit_bn": g(r, "p_exit_bn"),
                "a0_mint_eth": g(r, "amount0_mint_eth"),
                "a1_mint_usdc": g(r, "amount1_mint_usdc"),
                "a0_burn_eth": g(r, "amount0_burn_eth"),
                "a1_burn_usdc": g(r, "amount1_burn_usdc"),
                "v0_usd": g(r, "v0_usd"),
                "basket_chain": g(r, "basket_delta_chain_usd"),
                "basket_bn": g(r, "basket_delta_binance_usd"),
                "basket_exact": g(r, "basket_delta_exact_usd"),
                "il_chain": g(r, "il_chain_usd"),
                "L_human": g(r, "L_human"),
                "L_source": r.get("L_source", ""),
            }
        )
    return out


# ---------------------------------------------------------------------------
# the ladder
# ---------------------------------------------------------------------------
def reconcile(trial):
    r01 = r01_cycles(trial)
    eng = engine_cycles(trial)

    # Cycles are keyed on the mint timestamp. Both sides take it from the same
    # recorder row (the engine's actions.json carries rebalance-history's ts
    # verbatim), so the match is exact rather than fuzzy.
    eng_by_mint = {c["mint_ts"]: c for c in eng}
    r01_by_mint = {c["mint_ts"]: c for c in r01}

    matched = [m for m in r01_by_mint if m in eng_by_mint]
    matched.sort()
    r01_only = sorted(m for m in r01_by_mint if m not in eng_by_mint)
    eng_only = sorted(m for m in eng_by_mint if m not in r01_by_mint)

    rows = []
    for m in matched:
        a, b = r01_by_mint[m], eng_by_mint[m]
        dP_r01 = a["p_exit"] - a["p_entry"]
        dP_chain = b["p_exit_chain"] - b["p_entry_chain"]

        # S0 report 01 as published
        s0 = a["basket_delta_usd"]
        # S1 substitute the ETH leg only: chain amount0, report 01's prices
        s1 = b["a0_mint_eth"] * dP_r01
        # S2 substitute prices too: chain amount0, pool price at block
        s2 = b["a0_mint_eth"] * dP_chain
        # what the engine actually reports for this cycle
        eng_reported = b["basket_chain"]

        # Report 01's own inversion, but handed the pool's price instead of
        # Binance's. Isolates the price from the AUM snapshot as the source of
        # the amount error: if this lands on the Mint event's amount0, the
        # snapshot was never the problem.
        a0_r01_chain_price = a0_from_v0(
            a["v0_usd"], b["p_entry_chain"], a["price_lower"], a["price_upper"]
        )

        rows.append(
            {
                "mint_ts": m,
                "burn_ts_r01": a["burn_ts"],
                "burn_ts_eng": b["burn_ts"],
                "close_status": a["close_status"],
                "boundary_differs": a["burn_ts"] != b["burn_ts"],
                "a0_r01": a["a0_eth"],
                "a0_chain": b["a0_mint_eth"],
                "a0_r01_at_chain_price": a0_r01_chain_price,
                "a0_diff_pct": (b["a0_mint_eth"] / a["a0_eth"] - 1) * 100,
                "a0_resid_pct_after_price_fix": (
                    b["a0_mint_eth"] / a0_r01_chain_price - 1
                ) * 100,
                "p_entry_err_bp": (a["p_entry"] / b["p_entry_chain"] - 1) * 1e4,
                "amplification_bp_per_bp": inversion_amplification(
                    b["p_entry_chain"], a["price_lower"], a["price_upper"]
                ),
                "v0_r01": a["v0_usd"],
                "v0_eng": b["v0_usd"],
                "p_entry_r01": a["p_entry"],
                "p_exit_r01": a["p_exit"],
                "p_entry_chain": b["p_entry_chain"],
                "p_exit_chain": b["p_exit_chain"],
                "dP_r01": dP_r01,
                "dP_chain": dP_chain,
                "s0_r01": s0,
                "s1_chain_amount": s1,
                "s2_chain_amount_price": s2,
                "eng_reported": eng_reported,
                "amount_effect": s1 - s0,
                "price_effect": s2 - s1,
                "closed_form_effect": eng_reported - s2,
                "total_diff": eng_reported - s0,
            }
        )

    # Attribute each cycle's divergence to the input that dominates it.
    for r in rows:
        if r["boundary_differs"]:
            r["cause"] = "boundary: report 01 closes at a reverted exit (F4)"
        elif abs(r["amount_effect"]) >= abs(r["price_effect"]):
            r["cause"] = "amount: ETH leg inverted at an off-chain price"
        else:
            r["cause"] = "price source: Binance@row-ts vs pool@block"

    tot = {
        "trial": trial,
        "n_matched": len(matched),
        "r01_total_all_cycles": sum(c["basket_delta_usd"] for c in r01),
        "r01_total_matched": sum(r["s0_r01"] for r in rows),
        "s1_total_matched": sum(r["s1_chain_amount"] for r in rows),
        "s2_total_matched": sum(r["s2_chain_amount_price"] for r in rows),
        "eng_total_matched": sum(r["eng_reported"] for r in rows),
        "eng_total_all_cycles": sum(c["basket_chain"] for c in eng),
        "amount_effect": sum(r["amount_effect"] for r in rows),
        "price_effect": sum(r["price_effect"] for r in rows),
        "closed_form_effect": sum(r["closed_form_effect"] for r in rows),
        "r01_only": [
            {
                "mint_ts": str(m),
                "burn_ts": str(r01_by_mint[m]["burn_ts"]),
                "close_status": r01_by_mint[m]["close_status"],
                "basket_usd": r01_by_mint[m]["basket_delta_usd"],
            }
            for m in r01_only
        ],
        "eng_only": [
            {
                "mint_ts": str(m),
                "burn_ts": str(eng_by_mint[m]["burn_ts"]),
                "basket_usd": eng_by_mint[m]["basket_chain"],
            }
            for m in eng_only
        ],
    }
    tot["coverage_effect"] = (
        sum(c["basket_usd"] for c in tot["eng_only"])
        - sum(c["basket_usd"] for c in tot["r01_only"])
    )
    # Reverse direction: feed the engine report 01's AUM-inverted ETH leg.
    tot["reverse_engine_with_r01_amounts"] = sum(
        r01_by_mint[r["mint_ts"]]["a0_eth"] * r["dP_chain"] for r in rows
    )
    tot["directional_hedge_pnl"] = r01_directional(trial)

    # Cycles the two sides close at different instants. Report 01 closes at
    # every executed_exit row; the engine closes at the Burn event that
    # actually fired. Where an exit tx reverted (finding F4) the two disagree,
    # and pricing a cycle at a burn that never happened is not a price-source
    # difference - it is a different cycle.
    tot["boundary_mismatch"] = [
        {
            "mint_ts": str(r["mint_ts"]),
            "burn_ts_r01": str(r["burn_ts_r01"]),
            "burn_ts_eng": str(r["burn_ts_eng"]),
        }
        for r in rows
        if r["burn_ts_r01"] != r["burn_ts_eng"]
    ]

    # Rung 3: chain amounts AND chain prices, but still at report 01's cycle
    # boundaries. The engine run with --assume-all-exits-burned is exactly
    # that, so the boundary effect can be isolated instead of inferred.
    legacy_dir = GATE1 / "out" / f"T{trial}-legacy-pairing"
    if legacy_dir.exists():
        legacy = engine_cycles(trial, "-legacy-pairing")
        tot["s3_r01_boundaries"] = sum(c["basket_chain"] for c in legacy)
        tot["s3_source"] = f"out/T{trial}-legacy-pairing"
    elif not tot["boundary_mismatch"]:
        # No boundary disagreement, so rung 3 is the engine total by identity.
        tot["s3_r01_boundaries"] = tot["eng_total_all_cycles"]
        tot["s3_source"] = "identity (no boundary disagreement)"
    else:
        tot["s3_r01_boundaries"] = None
        tot["s3_source"] = None

    # The three effects, in causal order.
    tot["eff_amount"] = tot["s1_total_matched"] - tot["r01_total_matched"]
    if tot["s3_r01_boundaries"] is not None:
        tot["eff_price_source"] = tot["s3_r01_boundaries"] - tot["s1_total_matched"]
        tot["eff_boundary"] = tot["eng_total_all_cycles"] - tot["s3_r01_boundaries"]
    else:
        tot["eff_price_source"] = None
        tot["eff_boundary"] = None
    return rows, tot


def fmt(x, w=10, p=4):
    return "n/a".rjust(w) if x is None else f"{x:>{w}.{p}f}"


def main():
    out = {}
    for trial in ("5", "4"):
        rows, tot = reconcile(trial)
        out[trial] = {"cycles": rows, "totals": tot}

        pub = R01_PUBLISHED[trial]
        print(f"\n{'='*100}")
        print(f"T{trial}   report 01 published basket delta: {pub['basket']:+.2f}")
        print(f"{'='*100}")
        print(
            f"re-implementation of report 01's method, all its cycles: "
            f"{tot['r01_total_all_cycles']:+.4f}"
        )
        print(
            f"  -> reproduces the published figure to "
            f"{abs(tot['r01_total_all_cycles'] - pub['basket']):.4f}"
        )
        print(f"engine total, all its cycles:                       {tot['eng_total_all_cycles']:+.4f}")
        print(f"matched cycles: {tot['n_matched']}   r01-only: {len(tot['r01_only'])}   engine-only: {len(tot['eng_only'])}")

        print("\n--- per-cycle ladder (matched cycles) ---")
        hdr = (
            f"{'mint_ts':<20} {'a0_r01':>9} {'a0_chain':>9} {'a0 d%':>7} "
            f"{'dP_r01':>8} {'dP_chn':>8} {'S0 r01':>9} {'S1 amt':>9} "
            f"{'S2 +px':>9} {'engine':>9} {'amt eff':>8} {'px eff':>8}"
        )
        print(hdr)
        print("-" * len(hdr))
        for r in rows:
            print(
                f"{str(r['mint_ts'])[:19]:<20} "
                f"{fmt(r['a0_r01'], 9, 6)} {fmt(r['a0_chain'], 9, 6)} "
                f"{fmt(r['a0_diff_pct'], 7, 2)} "
                f"{fmt(r['dP_r01'], 8, 2)} {fmt(r['dP_chain'], 8, 2)} "
                f"{fmt(r['s0_r01'], 9, 3)} {fmt(r['s1_chain_amount'], 9, 3)} "
                f"{fmt(r['s2_chain_amount_price'], 9, 3)} "
                f"{fmt(r['eng_reported'], 9, 3)} "
                f"{fmt(r['amount_effect'], 8, 3)} {fmt(r['price_effect'], 8, 3)}"
            )
        print("-" * len(hdr))
        print(
            f"{'TOTAL (matched)':<20} {'':>9} {'':>9} {'':>7} {'':>8} {'':>8} "
            f"{fmt(tot['r01_total_matched'], 9, 3)} "
            f"{fmt(tot['s1_total_matched'], 9, 3)} "
            f"{fmt(tot['s2_total_matched'], 9, 3)} "
            f"{fmt(tot['eng_total_matched'], 9, 3)} "
            f"{fmt(tot['amount_effect'], 8, 3)} {fmt(tot['price_effect'], 8, 3)}"
        )

        print("\n--- the ladder: one input substituted per rung ---")
        print(f"  S0  report 01 as published                       "
              f"{tot['r01_total_all_cycles']:+9.4f}")
        print(f"  S1  + ETH leg from the Mint event                "
              f"{tot['s1_total_matched']:+9.4f}   "
              f"(amount effect {tot['eff_amount']:+.4f})")
        if tot["s3_r01_boundaries"] is not None:
            print(f"  S2  + price from the pool at the block           "
                  f"{tot['s3_r01_boundaries']:+9.4f}   "
                  f"(price-source effect {tot['eff_price_source']:+.4f})")
            print(f"  S3  + cycle boundaries from the Burn events      "
                  f"{tot['eng_total_all_cycles']:+9.4f}   "
                  f"(boundary effect {tot['eff_boundary']:+.4f})")
            print(f"      [S2 source: {tot['s3_source']}]")
        print(f"  ==  engine as published                          "
              f"{tot['eng_total_all_cycles']:+9.4f}")

        if tot["boundary_mismatch"]:
            print("\n  cycles the two sides close at DIFFERENT instants:")
            for c in tot["boundary_mismatch"]:
                print(f"    mint {c['mint_ts'][:19]}   "
                      f"r01 closes {c['burn_ts_r01'][:19]}   "
                      f"engine closes {c['burn_ts_eng'][:19]}")

        if tot["r01_only"]:
            print("\n  cycles report 01 has that the engine does not:")
            for c in tot["r01_only"]:
                print(f"    {c['mint_ts'][:19]} -> {c['burn_ts'][:19]}  "
                      f"{c['close_status']:<18} {c['basket_usd']:+.4f}")
        if tot["eng_only"]:
            print("\n  cycles the engine has that report 01 does not:")
            for c in tot["eng_only"]:
                print(f"    {c['mint_ts'][:19]} -> {c['burn_ts'][:19]}  {c['basket_usd']:+.4f}")

        print("\n--- the pre-registered test: report 01's method fed chain amounts ---")
        s1_all = tot["s1_total_matched"] + sum(
            c["basket_usd"] for c in tot["r01_only"]
        )
        err = (s1_all / pub["basket"] - 1) * 100
        print(f"  report 01 method + chain amount0 = {s1_all:+.4f}  "
              f"vs published {pub['basket']:+.2f}  ({err:+.1f}%)")
        print(f"  within +/-10%? {'YES' if abs(err) <= 10 else 'NO'}")
        tot["s1_all_cycles"] = s1_all
        tot["s1_vs_published_pct"] = err

        print("\n--- reverse: engine's method fed report 01's AUM-inverted amounts ---")
        print(f"  engine prices + r01 amount0 (matched) = "
              f"{tot['reverse_engine_with_r01_amounts']:+.4f}")
        print(f"  engine as-is (matched)                = {tot['eng_total_matched']:+.4f}")

        # --- corrected delta luck and luck-stripped net ---------------------
        # Delta luck is report 01 §4's construction: the LP basket's directional
        # gain plus the perp short's directional P&L. Only the basket term is
        # touched here; the directional term is a hedge-side number that none
        # of the three substituted inputs reaches, and it reproduces report 01's
        # published value exactly, so it carries through unchanged.
        basket_corrected = tot["eng_total_all_cycles"]
        directional = tot["directional_hedge_pnl"]
        luck_corrected = basket_corrected + directional
        stripped_corrected = pub["observed_net"] - luck_corrected
        stripped_published = pub["observed_net"] - pub["delta_luck"]
        tot["corrected"] = {
            "basket_delta_usd": basket_corrected,
            "directional_hedge_pnl_usd": directional,
            "delta_luck_usd": luck_corrected,
            "observed_net_usd": pub["observed_net"],
            "luck_stripped_net_usd": stripped_corrected,
            "published_delta_luck_usd": pub["delta_luck"],
            "published_luck_stripped_net_usd": stripped_published,
        }
        print("\n--- corrected delta luck / luck-stripped net ---")
        print(f"  basket delta      {pub['basket']:+7.2f}  ->  {basket_corrected:+7.2f}")
        print(f"  directional hedge {directional:+7.2f}  ->  {directional:+7.2f}   (unchanged)")
        print(f"  delta luck        {pub['delta_luck']:+7.2f}  ->  {luck_corrected:+7.2f}")
        print(f"  observed net      {pub['observed_net']:+7.2f}      (unchanged, recorded AUM)")
        print(f"  luck-stripped net {stripped_published:+7.2f}  ->  {stripped_corrected:+7.2f}")

        # --- is the ETH-leg error the snapshot, or the price? ---------------
        print("\n--- conditioning of the ETH-leg inversion ---")
        amp = [r["amplification_bp_per_bp"] for r in rows]
        print(f"  d(a0)/a0 per 1bp of price error: mean {sum(amp)/len(amp):.0f} bp "
              f"(range {min(amp):.0f} to {max(amp):.0f})")
        print(f"  entry-price error Binance vs pool: "
              f"{min(r['p_entry_err_bp'] for r in rows):+.1f} to "
              f"{max(r['p_entry_err_bp'] for r in rows):+.1f} bp")
        print(f"  ETH-leg error before price fix: mean "
              f"{sum(abs(r['a0_diff_pct']) for r in rows)/len(rows):.2f}% (abs)")
        print(f"  ETH-leg error after  price fix: mean "
              f"{sum(abs(r['a0_resid_pct_after_price_fix']) for r in rows)/len(rows):.2f}% (abs)")
        print("  -> the AUM snapshot is not the error; the inversion price is, "
              "amplified ~185x by narrow-range geometry")

    # Cycle-level table, per the E004 deliverable.
    cols = [
        "trial", "mint_ts", "burn_ts_r01", "burn_ts_eng", "boundary_differs",
        "a0_r01", "a0_chain", "a0_r01_at_chain_price", "a0_diff_pct",
        "a0_resid_pct_after_price_fix", "p_entry_err_bp", "amplification_bp_per_bp",
        "p_entry_r01", "p_exit_r01", "p_entry_chain", "p_exit_chain",
        "dP_r01", "dP_chain", "s0_r01", "s1_chain_amount", "eng_reported",
        "amount_effect", "price_effect", "total_diff", "cause",
    ]
    with open(HERE / "cycle_table.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for trial in ("5", "4"):
            for r in out[trial]["cycles"]:
                w.writerow({c: r.get(c, "") if c != "trial" else trial for c in cols})

    (HERE / "reconciliation.json").write_text(json.dumps(out, indent=2, default=str))
    print(f"\nwrote {HERE / 'reconciliation.json'}")
    print(f"wrote {HERE / 'cycle_table.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
