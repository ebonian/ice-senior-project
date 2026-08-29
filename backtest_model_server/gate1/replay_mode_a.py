#!/usr/bin/env python3
"""Mode A — record-and-replay reproduction of a live trial, per cost line.

    nix develop .#gate1 -c python backtest_model_server/gate1/replay_mode_a.py --trial 5

Nothing here is counterfactual. The trial's recorded positions and actions are
replayed as-is against archived pool data, and each cost line is compared to the
corrected target from bot `analysis/strategy-review/01-loss-attribution.md` §2
under the tolerances pre-registered in `loop/experiments/E002`.

Cost lines and where each comes from:

  LP fees        per-swap V3 replay over the exact mint->burn block range, using
                 the harness's verified fee arithmetic (engine/fee_engine.py)
  Crystallized IL exact V3 range math per cycle, decomposed against the mint
                 basket and never netted with basket delta (engine/il_ledger.py)
  On-chain       5.155 bps x swapped notional + $0.0101/tx (engine/cost_model.py)
  HPL fees       recorded fill notionals x the published schedule
  Funding        recorded hourly rates x the recorded perp notional path.
                 Replayed, never modelled.

Outputs land in gate1/out/T<n>/.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from engine import cost_model as CM  # noqa: E402
from engine import fee_engine, harness as H, il_ledger, trials  # noqa: E402

GATE1 = Path(__file__).resolve().parent

# --- calibration targets ---------------------------------------------------
# Source: bot analysis/strategy-review/01-loss-attribution.md §2 (the single
# calibration source; it supersedes the docs where they differ) plus the
# regenerated bot analysis/trials/<n>/output/data/summary.json. Frozen history.
TARGETS = {
    5: {
        "lp_fees_usd": (7.8210, 0.15, "rel", "summary.json lp_fees_collected_usd"),
        "crystallized_il_usd": (-10.90, 0.10, "rel", "report 01 §5 per-segment table"),
        "basket_delta_usd": (8.52, 0.10, "rel", "report 01 §5"),
        "hpl_fees_usd": (-3.3577, 0.05, "rel", "summary.json hedge_fees_paid_usd"),
        "funding_usd": (0.0702, 0.05, "abs", "summary.json implied_funding_usd"),
        "onchain_cost_usd": (-5.1049, 0.10, "rel", "summary.json / onchain_audit.json"),
        "onchain_swap_volume_usd": (9062.15, 0.10, "rel", "onchain_audit.json"),
        "flat_gap_residual_usd": (-2.4, 0.50, "rel", "report 01 §5 out-of-position drift"),
    },
    4: {
        "lp_fees_usd": (5.5623, 0.15, "rel", "report 01 §2 (sum of executed_exit rows)"),
        "crystallized_il_usd": (-4.51, 0.10, "rel", "report 01 §5"),
        "basket_delta_usd": (1.20, 0.10, "rel", "report 01 §5"),
        "hpl_fees_usd": (-4.4021, 0.05, "rel", "summary.json hedge_fees_paid_usd"),
        "funding_usd": (0.0947, 0.05, "abs", "summary.json implied_funding_usd"),
        "onchain_cost_usd": (-6.4, 0.10, "rel", "report 01 §2 (SCALED ESTIMATE, +-40%)"),
    },
}

POOL_FEE = 0.0005
LIQ_SCALE = H.liquidity_scale(18, 6)


# --------------------------------------------------------------------------
def load_window_swaps(trial: int) -> pd.DataFrame:
    """Swap frame for the trial window, RPC-sourced (B2 has hour gaps)."""
    p = GATE1 / "data" / "rpc" / f"T{trial}" / "swaps.parquet"
    if not p.exists():
        raise FileNotFoundError(
            f"{p} missing — run fetch_rpc_window.py --trial {trial} first"
        )
    df = pd.read_parquet(p)
    df["ts"] = pd.to_datetime(df["timestamp"], unit="s", utc=True)
    sqrt_px96 = df["sqrt_price_x96"].astype("string").map(int).astype(float)
    df["price"] = (sqrt_px96 / (2**96)) ** 2 * 1e12
    df["amount0"] = df["amount0"].astype("string").map(int).astype(float)
    df["amount1"] = df["amount1"].astype("string").map(int).astype(float)
    df["volume_usd"] = df["amount1"].abs() / 1e6
    df["pool_liquidity"] = df["liquidity"].astype("string").map(int).astype(float)
    df["v3_tick"] = df["tick"].astype(np.int64)
    return df.sort_values(["block_number", "log_index"]).reset_index(drop=True)


def price_at_block(swaps: pd.DataFrame, block: int) -> tuple[float, int]:
    """Pool price and tick as of the last swap at or before `block`."""
    prior = swaps[swaps["block_number"] <= block]
    if len(prior) == 0:
        return float(swaps["price"].iloc[0]), int(swaps["v3_tick"].iloc[0])
    r = prior.iloc[-1]
    return float(r["price"]), int(r["v3_tick"])


def block_at_ts(swaps: pd.DataFrame, ts) -> int | None:
    """Last swap block at or before `ts`, for intra-cycle checkpoints."""
    t = pd.Timestamp(ts)
    prior = swaps[swaps["ts"] <= t]
    return int(prior["block_number"].iloc[-1]) if len(prior) else None


# --------------------------------------------------------------------------
def replay_cycles(trial: int, swaps: pd.DataFrame, cycles, aum, bn) -> list[dict]:
    rows = []
    for c in cycles:
        pl = H.v3_tick_to_price(c.lower_v3_tick)
        pu = H.v3_tick_to_price(c.upper_v3_tick)

        # --- liquidity: exact from the Mint event when we have the receipt ---
        mint_ev = (c.onchain or {}).get("mint") or []
        burn_ev = (c.onchain or {}).get("burn") or []
        collect_ev = (c.onchain or {}).get("collect") or []
        L_source = "onchain_mint"
        if mint_ev:
            L_raw = float(mint_ev[0]["liquidity"])
            L_human = L_raw / LIQ_SCALE
            a0_mint = mint_ev[0]["amount0"] / 1e18
            a1_mint = mint_ev[0]["amount1"] / 1e6
        else:
            snap = trials.aum_at(aum, c.mint_ts + pd.Timedelta(minutes=1), "after")
            v0 = float(snap["position_usd"]) if snap is not None else c.mint_row_wallet_usd
            p_entry_tmp, _ = price_at_block(swaps, c.mint_block or 0)
            L_human = H.compute_liquidity_from_capital(v0, p_entry_tmp, pl, pu)
            a0_mint, a1_mint = il_ledger.position_amounts(p_entry_tmp, pl, pu, L_human)
            L_source = "aum_inverted"

        # --- prices at the cycle edges --------------------------------------
        p_entry_chain, t_entry = price_at_block(swaps, c.mint_block)
        p_exit_chain, _ = price_at_block(swaps, c.burn_block)
        p_entry_bn = trials.binance_price_at(bn, c.mint_ts)
        p_exit_bn = trials.binance_price_at(bn, c.burn_ts)

        # --- LP fees: per-swap replay over the exact block range ------------
        sl = swaps[
            (swaps["block_number"] > c.mint_block) & (swaps["block_number"] <= c.burn_block)
        ]
        acc = fee_engine.accrue_fees(
            sl, L_human, c.lower_v3_tick, c.upper_v3_tick, pl, pu,
            prev_price=p_entry_chain, prev_v3_tick=t_entry,
            pool_fee=POOL_FEE, liquidity_scale=LIQ_SCALE,
        )

        # --- exact on-chain fee, from Collect minus Burn principal ----------
        fee_onchain = None
        a0_burn = a1_burn = None
        if burn_ev:
            a0_burn = burn_ev[0]["amount0"] / 1e18
            a1_burn = burn_ev[0]["amount1"] / 1e6
        if collect_ev and burn_ev:
            c0 = collect_ev[0]["amount0"] / 1e18
            c1 = collect_ev[0]["amount1"] / 1e6
            fee0, fee1 = c0 - a0_burn, c1 - a1_burn
            fee_onchain = fee0 * p_exit_chain + fee1

        # --- IL ledger -------------------------------------------------------
        il_chain = il_ledger.cycle_il(
            c.idx, c.mint_ts, c.burn_ts, c.lower_v3_tick, c.upper_v3_tick,
            p_entry_chain, p_exit_chain,
            v0_usd=a0_mint * p_entry_chain + a1_mint,
        )
        il_bn = il_ledger.cycle_il(
            c.idx, c.mint_ts, c.burn_ts, c.lower_v3_tick, c.upper_v3_tick,
            p_entry_bn, p_exit_bn,
            v0_usd=a0_mint * p_entry_bn + a1_mint,
        )
        # Exact IL straight from the Mint/Burn token deltas — no closed form.
        il_exact = basket_exact = None
        if a0_burn is not None:
            v_pos_exit = a0_burn * p_exit_chain + a1_burn
            v_hodl_exit = a0_mint * p_exit_chain + a1_mint
            v_pos_entry = a0_mint * p_entry_chain + a1_mint
            il_exact = v_pos_exit - v_hodl_exit
            basket_exact = v_hodl_exit - v_pos_entry

        # --- intra-cycle accrual shape (04-backtest-design.md §6.2 #2) -------
        # `accumulated_fees_usd` on a non-exit row is a live reading of unclaimed
        # fees on the open position, so each dwell-guard / hold row is an extra
        # fee observation. Reproducing a cycle total while getting the path wrong
        # is a detectable failure that an aggregate match would hide.
        checkpoints = []
        for ir in c.intra_rows:
            b = block_at_ts(swaps, ir["ts"])
            if b is None or b <= c.mint_block:
                continue
            part = swaps[
                (swaps["block_number"] > c.mint_block) & (swaps["block_number"] <= b)
            ]
            acc_p = fee_engine.accrue_fees(
                part, L_human, c.lower_v3_tick, c.upper_v3_tick, pl, pu,
                prev_price=p_entry_chain, prev_v3_tick=t_entry,
                pool_fee=POOL_FEE, liquidity_scale=LIQ_SCALE, track_path=False,
            )
            checkpoints.append({
                "ts": ir["ts"], "status": ir["status"],
                "recorded_fees_usd": ir["accumulated_fees_usd"],
                "modelled_fees_usd": acc_p.fee_usd,
                "err_pct": (
                    (acc_p.fee_usd / ir["accumulated_fees_usd"] - 1) * 100
                    if ir["accumulated_fees_usd"] else float("nan")
                ),
            })

        rows.append(
            {
                "cycle": c.idx,
                "checkpoints": checkpoints,
                "mint_ts": str(c.mint_ts), "burn_ts": str(c.burn_ts),
                "hours": (c.burn_ts - c.mint_ts).total_seconds() / 3600,
                "lower_tick": c.lower_v3_tick, "upper_tick": c.upper_v3_tick,
                "price_lower": pl, "price_upper": pu,
                "L_human": L_human, "L_source": L_source,
                "mint_block": c.mint_block, "burn_block": c.burn_block,
                "p_entry_chain": p_entry_chain, "p_exit_chain": p_exit_chain,
                "p_entry_bn": p_entry_bn, "p_exit_bn": p_exit_bn,
                "amount0_mint_eth": a0_mint, "amount1_mint_usdc": a1_mint,
                "amount0_burn_eth": a0_burn, "amount1_burn_usdc": a1_burn,
                "v0_usd": a0_mint * p_entry_chain + a1_mint,
                # fees
                "fees_modelled_usd": acc.fee_usd,
                "fees_recorded_usd": c.recorded_fees_usd,
                "fees_onchain_usd": fee_onchain,
                "n_swaps": acc.n_swaps, "n_swaps_in_range": acc.n_swaps_in_range,
                "volume_usd": acc.volume_usd,
                "volume_in_range_usd": acc.volume_in_range_usd,
                "mean_liquidity_share": acc.mean_liquidity_share,
                "time_in_range_frac": acc.time_in_range_frac,
                # IL
                "il_chain_usd": il_chain.il_usd,
                "basket_delta_chain_usd": il_chain.basket_delta_usd,
                "il_binance_usd": il_bn.il_usd,
                "basket_delta_binance_usd": il_bn.basket_delta_usd,
                "il_exact_usd": il_exact,
                "basket_delta_exact_usd": basket_exact,
                "exited_range": il_chain.exited_range,
                "frac_eth_entry": il_chain.frac_eth_at_entry,
                "frac_eth_exit": il_chain.frac_eth_at_exit,
                "n_orphan_exits": len(c.orphan_exits),
            }
        )
    return rows


# --------------------------------------------------------------------------
def hedge_lines(trial: int, aum: pd.DataFrame) -> dict:
    """HPL fees from the recorded fills; funding from recorded rates x notional."""
    f = trials.fills_in_window(trial)
    mk = f[f["is_maker"]]
    tk = f[~f["is_maker"]]

    fees_from_schedule = CM.hpl_fees_from_shares(
        float(mk["ntl"].sum()), float(tk["ntl"].sum())
    )
    # Count-weighted maker share applied to total notional — the modelling trap
    # the counterfactuals would otherwise fall into.
    share_count = len(mk) / len(f) if len(f) else 0.0
    fees_count_weighted = CM.hpl_fees_from_shares(
        float(f["ntl"].sum()) * share_count, float(f["ntl"].sum()) * (1 - share_count)
    )

    # --- funding: recorded hourly rate x recorded perp notional -------------
    fund = trials.load_funding()
    w0, w1 = trials.window(trial)
    hours = pd.date_range(w0, w1 - pd.Timedelta(hours=1), freq="h")
    rate_by_hour = dict(zip(fund["ts"], fund["funding_rate_hourly"]))

    total_funding = 0.0
    detail = []
    for h in hours:
        rate = rate_by_hour.get(h)
        if rate is None:
            detail.append({"hour": str(h), "rate": None, "notional": None, "pnl": 0.0})
            continue
        snap = trials.aum_at(aum, h, "nearest")
        if snap is None or pd.isna(snap["perp_position_notional"]):
            detail.append({"hour": str(h), "rate": rate, "notional": None, "pnl": 0.0})
            continue
        ntl = float(snap["perp_position_notional"])
        qty = float(snap["perp_position_qty"])
        # A positive hourly rate means longs pay shorts: a short RECEIVES.
        pnl = rate * ntl * (1.0 if qty < 0 else -1.0)
        total_funding += pnl
        detail.append({"hour": str(h), "rate": rate, "notional": ntl, "qty": qty, "pnl": pnl})

    return {
        "n_fills": len(f),
        "notional_usd": float(f["ntl"].sum()),
        "recorded_fees_usd": float(f["fee"].sum()),
        "modelled_fees_usd": fees_from_schedule,
        "modelled_fees_count_weighted_usd": fees_count_weighted,
        "maker_share_by_count": share_count,
        "maker_share_by_notional": float(mk["ntl"].sum()) / float(f["ntl"].sum()),
        "maker_notional_usd": float(mk["ntl"].sum()),
        "taker_notional_usd": float(tk["ntl"].sum()),
        "n_maker": len(mk), "n_taker": len(tk),
        "oversized_taker_fills": int((tk["sz"] >= 0.05).sum()),
        "oversized_taker_fees_usd": float(tk[tk["sz"] >= 0.05]["fee"].sum()),
        "funding_usd": total_funding,
        "funding_detail": detail,
    }


BOT_WALLET = "0x209eb3db2700de48788e49dd81088267a0e79323"


def our_swaps(swaps: pd.DataFrame, w0, w1) -> pd.DataFrame:
    """Our own swap legs, identified by the Swap event's recipient topic.

    Measured rather than assumed: `onchain_audit.json` counted 23 pool swaps for
    $9,062 in T5, and this is the same quantity read straight off the chain.
    """
    if "recipient" not in swaps.columns:
        return swaps.iloc[0:0]
    m = (
        (swaps["recipient"].str.lower() == BOT_WALLET)
        | (swaps["sender"].str.lower() == BOT_WALLET)
    ) & (swaps["ts"] >= w0) & (swaps["ts"] < w1)
    return swaps[m]


def onchain_lines(trial: int, cyc_rows: list[dict], swaps: pd.DataFrame) -> dict:
    """Two independent readings of the swapped notional, then the cost.

    `predicted` is what the policy implies (this is the term the counterfactuals
    will vary: with `enable_exit_swap_back = true` and `asymmetric_mint_enabled
    = false` every cycle swaps its whole ETH leg out at EXIT and back at
    REBALANCE). `measured` is our actual swap volume through the pool. The gap
    between them is the honest error bar on the on-chain line.
    """
    audit = trials.load_onchain_audit(trial)
    w0, w1 = trials.window(trial)

    predicted = 0.0
    for r in cyc_rows:
        if r["amount0_burn_eth"] is not None:      # EXIT: sell the whole ETH leg
            predicted += r["amount0_burn_eth"] * r["p_exit_chain"]
        predicted += r["amount0_mint_eth"] * r["p_entry_chain"]   # REBALANCE: buy it back

    ours = our_swaps(swaps, w0, w1)
    measured = float((ours["amount1"].abs() / 1e6).sum()) if len(ours) else None

    n_reb = len(cyc_rows)
    n_exit = len(cyc_rows)
    n_tx = (audit or {}).get("tx_count")
    basis = measured if measured else predicted
    modelled = CM.onchain_cost(basis, n_reb, n_exit, n_tx=n_tx)
    from_predicted = CM.onchain_cost(predicted, n_reb, n_exit, n_tx=n_tx)
    return {
        "swapped_notional_predicted_usd": predicted,
        "swapped_notional_measured_usd": measured,
        "n_our_swaps_measured": int(len(ours)),
        "swapped_notional_audited_usd": (audit or {}).get("swap_volume_usd"),
        "n_swaps_audited": (audit or {}).get("swap_count"),
        "n_tx_audited": n_tx,
        "basis_used": "measured" if measured else "predicted",
        "modelled_total_usd": modelled.total_usd,
        "modelled_swap_usd": modelled.swap_cost_usd,
        "modelled_gas_usd": modelled.gas_usd,
        "modelled_failed_usd": modelled.failed_tx_usd,
        "modelled_total_from_predicted_usd": from_predicted.total_usd,
        "audited_total_usd": (audit or {}).get("total_cost_usd"),
    }


def replayed_hedge_pnl(trial: int, aum: pd.DataFrame) -> dict:
    """Hedge trading P&L — replayed from the record, not modelled.

    Report 01 §4's identity: hedge_side_change = -fees + funding
    + realized_closes_gross + delta-uPnL. closedPnl in the export is NET of
    fees, so the gross close is closedPnl + fee.
    """
    f = trials.fills_in_window(trial)
    closes_gross = float((f["closedPnl"] + f["fee"]).sum())
    w0, w1 = trials.window(trial)
    a0 = trials.aum_at(aum, w0, "after")
    a1 = trials.aum_at(aum, w1, "before")
    upnl_delta = float(a1["perp_unrealized_pnl_usd"]) - float(a0["perp_unrealized_pnl_usd"])
    return {
        "realized_closes_gross_usd": closes_gross,
        "upnl_change_usd": upnl_delta,
        "hedge_trading_pnl_usd": closes_gross + upnl_delta,
        "aum_total_start_usd": float(a0["total_usd"]),
        "aum_total_end_usd": float(a1["total_usd"]),
        "aum_total_change_usd": float(a1["total_usd"]) - float(a0["total_usd"]),
    }


# --------------------------------------------------------------------------
def grade(name: str, target: float, tol: float, mode: str, got: float) -> dict:
    delta = got - target
    if mode == "rel":
        band = abs(target) * tol
        pct = (delta / abs(target) * 100) if target else float("nan")
    else:
        band = tol
        pct = float("nan")
    return {
        "line": name, "target": target, "reproduced": got, "delta": delta,
        "tolerance": (f"±{tol*100:.0f}%" if mode == "rel" else f"±${tol:.2f}"),
        "delta_pct": pct, "pass": bool(abs(delta) <= band + 1e-12),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trial", type=int, required=True, choices=[4, 5])
    ap.add_argument(
        "--assume-all-exits-burned", action="store_true",
        help="close a cycle at every executed_exit row, including the ones whose "
             "tx reverted. This is report 01's pairing; the flag exists to test "
             "whether that assumption explains the T4 IL gap.",
    )
    args = ap.parse_args()
    t = args.trial

    out_dir = GATE1 / "out" / (f"T{t}-legacy-pairing" if args.assume_all_exits_burned
                               else f"T{t}")
    out_dir.mkdir(parents=True, exist_ok=True)

    swaps = load_window_swaps(t)
    actions_json = GATE1 / "data" / "rpc" / f"T{t}" / "actions.json"
    cycles = trials.load_cycles(
        t, actions_json, assume_all_exits_burned=args.assume_all_exits_burned
    )
    aum = trials.load_aum(t)
    bn = trials.load_binance_1m(t)

    print(f"=== T{t} mode-A replay ===")
    print(f"swaps in fetched span: {len(swaps):,}")
    print(f"cycles: {len(cycles)}  (orphan exits dropped: "
          f"{sum(len(c.orphan_exits) for c in cycles)})")

    cyc_rows = replay_cycles(t, swaps, cycles, aum, bn)
    cyc = pd.DataFrame(cyc_rows)
    cyc.drop(columns=["checkpoints"]).to_csv(out_dir / "cycles.csv", index=False)
    (out_dir / "checkpoints.json").write_text(
        json.dumps(
            [{"cycle": r["cycle"], **cp} for r in cyc_rows for cp in r["checkpoints"]],
            indent=2, default=str,
        )
    )

    hedge = hedge_lines(t, aum)
    onchain = onchain_lines(t, cyc_rows, swaps)
    hpnl = replayed_hedge_pnl(t, aum)

    # --- aggregate the ledger -------------------------------------------------
    got = {
        "lp_fees_usd": float(cyc["fees_modelled_usd"].sum()),
        # Graded on the POOL price at the exact burn block. A V3 position's
        # composition is set by the pool's own price, not by Binance; report 01
        # used Binance 1m because that is what it had. Both variants, plus the
        # zero-model figure taken straight from the Mint/Burn token deltas, are
        # carried in `il_totals` so the choice is auditable rather than implicit.
        "crystallized_il_usd": float(cyc["il_chain_usd"].sum()),
        "basket_delta_usd": float(cyc["basket_delta_chain_usd"].sum()),
        "hpl_fees_usd": -hedge["modelled_fees_usd"],
        "funding_usd": hedge["funding_usd"],
        "onchain_cost_usd": -onchain["modelled_total_usd"],
        "onchain_swap_volume_usd": (
            onchain["swapped_notional_measured_usd"]
            or onchain["swapped_notional_predicted_usd"]
        ),
    }
    # Net AUM compounds every line above plus the hedge's own trading P&L, which
    # mode A replays rather than models. Decision 0005's two-stage attribution:
    # the residual is reported, never absorbed.
    modelled_sum = (
        got["lp_fees_usd"] + got["crystallized_il_usd"] + got["basket_delta_usd"]
        + got["hpl_fees_usd"] + got["funding_usd"] + got["onchain_cost_usd"]
        + hpnl["hedge_trading_pnl_usd"]
    )
    residual = hpnl["aum_total_change_usd"] - modelled_sum
    got["flat_gap_residual_usd"] = residual
    # Reported, never graded: adding the residual back makes this an identity
    # with the recorded AUM change, so a "pass" here would be meaningless. The
    # meaningful statement is how much the modelled lines explain on their own.
    got["net_aum_explained_usd"] = modelled_sum
    # The engine's own like-for-like fee test: modelled vs what the recorder saw
    # over exactly the cycles replayed.
    got["lp_fees_vs_recorded_usd"] = float(cyc["fees_modelled_usd"].sum())

    table = []
    for line, (target, tol, mode, src) in TARGETS[t].items():
        if line not in got:
            continue
        row = grade(line, target, tol, mode, got[line])
        row["source"] = src
        table.append(row)

    print(f"\n{'line':26s} {'target':>10s} {'reproduced':>12s} {'delta':>10s} "
          f"{'tol':>7s}  verdict")
    for r in table:
        print(f"{r['line']:26s} {r['target']:>10.4f} {r['reproduced']:>12.4f} "
              f"{r['delta']:>10.4f} {r['tolerance']:>7s}  "
              f"{'PASS' if r['pass'] else 'FAIL'}"
              + (f"  ({r['delta_pct']:+.1f}%)" if r['delta_pct'] == r['delta_pct'] else ""))

    print(f"\n{'(informational, not graded)':26s}")
    print(f"{'net_aum_explained_usd':26s} {'':>10s} {got['net_aum_explained_usd']:>12.4f}"
          f"   of recorded {hpnl['aum_total_change_usd']:.4f}")
    print(f"{'  engine fees vs recorded':26s} {float(cyc['fees_recorded_usd'].sum()):>10.4f} "
          f"{float(cyc['fees_modelled_usd'].sum()):>12.4f} "
          f"{float(cyc['fees_modelled_usd'].sum()) - float(cyc['fees_recorded_usd'].sum()):>10.4f}"
          f"   (like-for-like over the {len(cyc)} replayed cycles)")

    print("\n--- per-cycle LP fees ---")
    print(f"{'cyc':>3s} {'window':>13s} {'modelled':>9s} {'recorded':>9s} "
          f"{'onchain':>9s} {'err%':>8s} {'TIR':>6s} {'LS(1e-4)':>9s}")
    for _, r in cyc.iterrows():
        err = (r["fees_modelled_usd"] / r["fees_recorded_usd"] - 1) * 100 if r["fees_recorded_usd"] else float("nan")
        oc = r["fees_onchain_usd"]
        print(f"{int(r['cycle']):>3d} {str(r['mint_ts'])[11:16]}->{str(r['burn_ts'])[11:16]} "
              f"{r['fees_modelled_usd']:>9.4f} {r['fees_recorded_usd']:>9.4f} "
              f"{(oc if oc == oc and oc is not None else float('nan')):>9.4f} {err:>7.1f}% "
              f"{r['time_in_range_frac']:>6.3f} {r['mean_liquidity_share']*1e4:>9.3f}")

    cps = [(int(r["cycle"]), cp) for r in cyc_rows for cp in r["checkpoints"]]
    if cps:
        print(f"\n--- intra-cycle fee checkpoints ({len(cps)} extra observations) ---")
        print(f"{'cyc':>3s} {'checkpoint':>16s} {'status':>20s} "
              f"{'modelled':>9s} {'recorded':>9s} {'err%':>8s}")
        for c_idx, cp in cps:
            print(f"{c_idx:>3d} {str(cp['ts'])[11:16]:>16s} {cp['status']:>20s} "
                  f"{cp['modelled_fees_usd']:>9.4f} {cp['recorded_fees_usd']:>9.4f} "
                  f"{cp['err_pct']:>7.1f}%")
        errs = [abs(cp["err_pct"]) for _, cp in cps if cp["err_pct"] == cp["err_pct"]]
        if errs:
            print(f"    worst |err| {max(errs):.1f}%, mean {sum(errs)/len(errs):.1f}%")

    print("\n--- per-cycle IL / basket delta (pool price at the burn block) ---")
    print(f"{'cyc':>3s} {'range':>13s} {'P in->out':>16s} {'IL':>8s} {'basket':>8s} "
          f"{'IL(exact)':>10s} {'IL(bnc)':>8s} {'OOR':>4s}")
    for _, r in cyc.iterrows():
        ex = r["il_exact_usd"]
        print(f"{int(r['cycle']):>3d} {r['price_lower']:.0f}-{r['price_upper']:.0f}  "
              f"{r['p_entry_chain']:>7.0f}->{r['p_exit_chain']:<7.0f} "
              f"{r['il_chain_usd']:>8.2f} {r['basket_delta_chain_usd']:>8.2f} "
              f"{(ex if ex == ex else float('nan')):>10.2f} {r['il_binance_usd']:>8.2f} "
              f"{'YES' if r['exited_range'] else '':>4s}")
    print("  IL totals — pool price %.4f | exact from Mint/Burn %.4f (%d/%d cycles) | "
          "Binance 1m %.4f" % (
              float(cyc["il_chain_usd"].sum()),
              float(cyc["il_exact_usd"].dropna().sum()),
              int(cyc["il_exact_usd"].notna().sum()), len(cyc),
              float(cyc["il_binance_usd"].sum())))

    print(f"\n--- hedge leg ---")
    print(f"fills {hedge['n_fills']}  notional ${hedge['notional_usd']:,.2f}")
    print(f"maker share: {hedge['maker_share_by_count']*100:.2f}% by count, "
          f"{hedge['maker_share_by_notional']*100:.2f}% by notional")
    print(f"HPL fees: recorded ${hedge['recorded_fees_usd']:.4f}  "
          f"schedule-modelled ${hedge['modelled_fees_usd']:.4f}  "
          f"count-weighted ${hedge['modelled_fees_count_weighted_usd']:.4f}")
    print(f"funding: ${hedge['funding_usd']:+.4f}")
    print(f"\n--- on-chain ---")
    print(json.dumps(onchain, indent=2, default=str))
    print(f"\n--- replayed hedge trading P&L (recorded, not modelled) ---")
    print(json.dumps(hpnl, indent=2, default=str))
    print(f"\nresidual (actual AUM change - every line above): ${residual:+.4f}")

    result = {
        "trial": t,
        "cost_model_version": CM.COST_MODEL_VERSION,
        "table": table,
        "aggregates": got,
        "hedge": {k: v for k, v in hedge.items() if k != "funding_detail"},
        "hedge_trading_pnl": hpnl,
        "onchain": onchain,
        "residual_usd": residual,
        "n_cycles": len(cycles),
        "orphan_exits": [
            {"cycle": c.idx, "dropped": c.orphan_exits} for c in cycles if c.orphan_exits
        ],
        # Exact totals are summed over the cycles that actually burned. A cycle
        # whose exit tx reverted crystallized nothing, so it has no Burn event
        # and cannot contribute to an exact figure.
        "il_totals": {
            "binance": float(cyc["il_binance_usd"].sum()),
            "onchain_price": float(cyc["il_chain_usd"].sum()),
            "exact_from_mint_burn": float(cyc["il_exact_usd"].dropna().sum()),
            "n_cycles_exact": int(cyc["il_exact_usd"].notna().sum()),
            "n_cycles": int(len(cyc)),
        },
        "basket_totals": {
            "binance": float(cyc["basket_delta_binance_usd"].sum()),
            "onchain_price": float(cyc["basket_delta_chain_usd"].sum()),
            "exact_from_mint_burn": float(cyc["basket_delta_exact_usd"].dropna().sum()),
        },
        "lp_fee_totals": {
            "modelled": float(cyc["fees_modelled_usd"].sum()),
            "recorded": float(cyc["fees_recorded_usd"].sum()),
            "onchain_collect": float(cyc["fees_onchain_usd"].dropna().sum()),
            "n_cycles_with_collect": int(cyc["fees_onchain_usd"].notna().sum()),
            "worst_cycle_abs_err_pct": float(
                ((cyc["fees_modelled_usd"] / cyc["fees_recorded_usd"] - 1) * 100).abs().max()
            ),
        },
    }
    (out_dir / "result.json").write_text(json.dumps(result, indent=2, default=str))
    (out_dir / "funding_detail.json").write_text(
        json.dumps(hedge["funding_detail"], indent=2, default=str)
    )
    print(f"\nwrote {out_dir}")

    n_fail = sum(1 for r in table if not r["pass"])
    print(f"\n{len(table)-n_fail}/{len(table)} lines within tolerance")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
