#!/usr/bin/env python3
"""
Compute real Uniswap V3 PnL (fees + LVR − gas − swap fee cost) for simulation_13.

Uses downloaded_data_csv swap data and run_004 model decisions (sim13 or kongtrae fallback).
Same logic as repo-root compute_fees_from_downloaded_data.py, scoped to simulation_13.

Formula compliance (GitHub env + real-world quant): see simulation_13/PNL_FORMULAS.md.

Usage (from repo root or research/simulation_13):
    python research/simulation_13/scripts/compute_pnl.py --model dqn --capital 100
    python scripts/compute_pnl.py --model ppo --model-dir run_004/models --gas-cost 0.02
"""

import os
import sys
import math
import glob
import argparse
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import torch

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SIM_DIR = os.path.normpath(os.path.join(SCRIPT_DIR, ".."))
REPO_ROOT = os.path.normpath(os.path.join(SCRIPT_DIR, "..", "..", ".."))
sys.path.insert(0, SIM_DIR)

from uniswap_v3_dqn_paper import (
    UniswapV3DQNEnv,
    DuelingDDQNAgent,
    LSTMDDQNAgent,
    SequenceStateWrapper,
    compute_technical_indicators,
    compute_L_onchain,
    sqrt_price_x96_to_price,
)

# ─── Pool Config (ETH/USDC 0.05%) ────────────────────────────────────────────
POOL_FEE = 500  # 1/1_000_000
DEC0, DEC1 = 18, 6
TICK_SPACING = 10
Q96 = 2**96


def sqrt_price_x96_to_price_simple(sqrt_price_x96) -> float:
    """Convert sqrtPriceX96 to USD price (ETH/USDC)."""
    p = float(sqrt_price_x96) / Q96
    return (p * p) * (10 ** (DEC0 - DEC1))


def compute_agent_L_sim(capital_usd: float, price_usd: float,
                       center_tick_sim: int, width: int) -> float:
    """Compute agent's L in simulation units (for LVR)."""
    p_lower = 1.0001 ** (center_tick_sim - width * TICK_SPACING)
    p_upper = 1.0001 ** (center_tick_sim + width * TICK_SPACING)
    sqrt_p = math.sqrt(price_usd)
    sqrt_pl = math.sqrt(p_lower)
    sqrt_pu = math.sqrt(p_upper)
    if price_usd <= p_lower:
        value_per_L = (1.0 / sqrt_pl - 1.0 / sqrt_pu) * price_usd
    elif price_usd >= p_upper:
        value_per_L = sqrt_pu - sqrt_pl
    else:
        value_per_L = 2.0 * sqrt_p - price_usd / sqrt_pu - sqrt_pl
    if value_per_L <= 0:
        return 0.0
    return capital_usd / value_per_L


def position_value_at(price: float, L: float, p_lower: float, p_upper: float) -> float:
    """Position value at price (simulation units, USD)."""
    if L <= 0:
        return 0.0
    sqrt_p = math.sqrt(price)
    sqrt_pl = math.sqrt(p_lower)
    sqrt_pu = math.sqrt(p_upper)
    if price <= p_lower:
        x = L * (1.0 / sqrt_pl - 1.0 / sqrt_pu)
        return x * price
    elif price >= p_upper:
        return L * (sqrt_pu - sqrt_pl)
    else:
        return L * (2.0 * sqrt_p - price / sqrt_pu - sqrt_pl)


def x_at_price(price: float, L: float, p_lower: float, p_upper: float) -> float:
    """Amount of token0 (ETH) at price."""
    if L <= 0:
        return 0.0
    sqrt_pl = math.sqrt(p_lower)
    sqrt_pu = math.sqrt(p_upper)
    if price <= p_lower:
        return L * (1.0 / sqrt_pl - 1.0 / sqrt_pu)
    elif price >= p_upper:
        return 0.0
    else:
        return L * (1.0 / math.sqrt(price) - 1.0 / sqrt_pu)


def compute_agent_L_onchain(capital_usd: float, price_usd: float,
                            center_tick: int, width: int) -> float:
    """Compute agent's liquidity L in on-chain units (delegates to shared compute_L_onchain)."""
    return compute_L_onchain(
        capital_usd, price_usd, DEC0, DEC1, center_tick, width, TICK_SPACING
    )


def load_swaps_from_downloaded(swaps_dir: str) -> pd.DataFrame:
    """Load all swap CSVs from downloaded_data_csv/daily/swaps."""
    pattern = os.path.join(swaps_dir, "*.csv")
    files = sorted(glob.glob(pattern))
    if not files:
        raise FileNotFoundError(f"No swap CSVs in {swaps_dir}")
    dfs = []
    for f in files:
        df = pd.read_csv(f, low_memory=False)
        dfs.append(df)
    swaps = pd.concat(dfs, ignore_index=True)
    swaps.columns = [c.strip().lower().replace("-", "_") for c in swaps.columns]
    if "sqrt_price_x96" in swaps.columns:
        swaps["sqrtpricex96"] = swaps["sqrt_price_x96"]
    elif "sqrtpricex96" not in swaps.columns:
        raise ValueError("Swap CSV must have sqrt_price_x96 or sqrtPriceX96 column")
    if "timestamp" in swaps.columns:
        swaps["evt_block_time"] = pd.to_datetime(swaps["timestamp"], unit="s", utc=True)
    else:
        raise ValueError("Swap CSV must have 'timestamp' column")
    swaps = swaps.sort_values("evt_block_time").reset_index(drop=True)
    return swaps


def prepare_hourly_from_swaps(swaps: pd.DataFrame) -> "HourlyDataExtended":
    """Build HourlyDataExtended from swap DataFrame (downloaded_data_csv format)."""
    from uniswap_v3_dqn_paper import HourlyDataExtended

    decimals0, decimals1 = DEC0, DEC1
    pool_fee = POOL_FEE / 1_000_000
    tick_spacing = TICK_SPACING

    swaps = swaps.copy()
    swaps["price"] = swaps["sqrtpricex96"].apply(
        lambda x: sqrt_price_x96_to_price(int(x), DEC0, DEC1)
    )
    swaps["volume_usd"] = swaps["amount1"].abs() / (10 ** decimals1)

    swap_prices_per_hour_raw = {}
    swaps_idx = swaps.set_index("evt_block_time")
    for hour, group in swaps_idx.groupby(pd.Grouper(freq="1h")):
        if len(group) >= 1:
            swap_prices_per_hour_raw[hour] = group["price"].values.astype(np.float64)

    hourly = swaps.set_index("evt_block_time").resample("1h").agg({
        "price": ["first", "last", "max", "min"],
        "volume_usd": "sum",
    })
    hourly.columns = ["open", "close", "high", "low", "volume"]
    hourly = hourly.dropna(subset=["close"])

    full_range = pd.date_range(start=hourly.index.min(), end=hourly.index.max(), freq="1h", tz="UTC")
    hourly = hourly.reindex(full_range)
    hourly["close"] = hourly["close"].ffill()
    hourly["open"] = hourly["open"].ffill()
    hourly["high"] = hourly["high"].ffill()
    hourly["low"] = hourly["low"].ffill()
    hourly["volume"] = hourly["volume"].fillna(0)

    hourly = compute_technical_indicators(hourly)
    feature_cols = [
        "high_open_ratio", "low_open_ratio", "close_open_ratio",
        "dema_ratio", "momentum_12", "roc_12", "atr_14", "natr_14",
        "adx_14", "plus_di", "minus_di", "cci_20", "rsi_14",
        "macd", "macd_signal", "macd_hist",
        "bb_upper", "bb_lower", "bb_width",
        "stoch_k", "stoch_d", "volume_sma_ratio",
        "return_1h", "return_24h", "return_7d",
        "price_vs_ma50", "price_vs_ma200", "ma50_vs_ma200",
        "market_regime", "trend_strength_24h", "trend_strength_7d",
    ]
    for col in feature_cols:
        if col not in hourly.columns:
            hourly[col] = 0.0

    timestamps = list(hourly.index)
    prices = hourly["close"].to_dict()
    volumes = hourly["volume"].to_dict()
    volatilities = hourly["natr_14"].to_dict() if "natr_14" in hourly.columns else {t: 0.0 for t in timestamps}
    swap_prices_per_hour = {ts: swap_prices_per_hour_raw.get(ts) for ts in timestamps}
    features = {}
    for ts in timestamps:
        feat_vec = hourly.loc[ts, feature_cols].values.astype(np.float32)
        feat_vec = np.clip(feat_vec, -10, 10)
        features[ts] = feat_vec

    return HourlyDataExtended(
        timestamps=timestamps,
        prices=prices,
        features=features,
        volumes=volumes,
        volatilities=volatilities,
        decimals0=decimals0,
        decimals1=decimals1,
        pool_fee=pool_fee,
        tick_spacing=tick_spacing,
        swap_prices_per_hour=swap_prices_per_hour,
    )


def slice_hourly_data_from(hourly_data: "HourlyDataExtended", test_start_ts: pd.Timestamp) -> "HourlyDataExtended":
    """Slice hourly data to timestamps >= test_start_ts (for evaluation on a specific period)."""
    from uniswap_v3_dqn_paper import HourlyDataExtended
    timestamps = [t for t in hourly_data.timestamps if t >= test_start_ts]
    if not timestamps:
        raise ValueError(f"No timestamps >= {test_start_ts}")
    return HourlyDataExtended(
        timestamps=timestamps,
        prices={t: hourly_data.prices[t] for t in timestamps},
        features={t: hourly_data.features[t] for t in timestamps},
        volumes={t: hourly_data.volumes[t] for t in timestamps},
        volatilities={t: hourly_data.volatilities[t] for t in timestamps},
        decimals0=hourly_data.decimals0,
        decimals1=hourly_data.decimals1,
        pool_fee=hourly_data.pool_fee,
        tick_spacing=hourly_data.tick_spacing,
        swap_prices_per_hour={t: hourly_data.swap_prices_per_hour.get(t) for t in timestamps} if hourly_data.swap_prices_per_hour else None,
    )


def run_fee_calculation(
    downloaded_dir: str,
    model_name: str,
    capital: float,
    model_dir: str,
    device: str = "cpu",
    mode: str = "test",
    gas_cost: float = 0.02,
    test_start: Optional[str] = "2026-01-01",
    rebalance_total_cost: Optional[float] = None,
    slippage_per_rebalance: float = 0.0,
    out_of_range_opportunity_apy: float = 0.0,
):
    """Replay model on test period and compute real fees + net PnL.
    If rebalance_total_cost is set (e.g. 0.044 from Llaminet eval), use that $ per rebalance instead of gas + swap fee.
    If test_start is set (e.g. '2026-01-01'), evaluation uses only data from that date onward.
    """
    swaps_dir = os.path.join(downloaded_dir, "daily", "swaps")
    print(f"📊 Loading swaps from {swaps_dir}...")
    swaps = load_swaps_from_downloaded(swaps_dir)
    swaps["liquidity"] = pd.to_numeric(swaps["liquidity"], errors="coerce")
    swaps["amount0"] = pd.to_numeric(swaps["amount0"], errors="coerce")
    swaps["amount1"] = pd.to_numeric(swaps["amount1"], errors="coerce")
    swaps["tick"] = pd.to_numeric(swaps["tick"], errors="coerce")
    swaps["sqrtpricex96"] = pd.to_numeric(swaps["sqrtpricex96"], errors="coerce")
    print(f"   Loaded {len(swaps):,} swaps")

    print("📊 Building hourly data...")
    hourly_data = prepare_hourly_from_swaps(swaps)
    if test_start:
        test_start_ts = pd.Timestamp(test_start, tz="UTC")
        hourly_data = slice_hourly_data_from(hourly_data, test_start_ts)
        mode = "full"  # use all timestamps in sliced data
        print(f"   Evaluation period: from {test_start} onward")
    env = UniswapV3DQNEnv(hourly_data, initial_capital_usd=capital, mode=mode)
    print(f"   Test period: {env.timestamps[0]} → {env.timestamps[-1]} ({len(env.timestamps)} hours)")

    state_dim = env.state_dim
    action_dim = env.action_space.n
    models_path = os.path.normpath(model_dir)

    if model_name == "ppo":
        from stable_baselines3 import PPO
        from uniswap_v3_ppo_paper import make_env_fn
        from stable_baselines3.common.vec_env import DummyVecEnv, VecNormalize
        ppo_path = os.path.join(models_path, "comparison_ppo.zip")
        if not os.path.exists(ppo_path):
            ppo_path = os.path.join(REPO_ROOT, "kongtrae", "models", "comparison_ppo.zip")
        ppo = PPO.load(ppo_path, device=device)
        eval_fn = make_env_fn(hourly_data, initial_capital_usd=capital, mode=mode)
        vec_env = DummyVecEnv([eval_fn])
        vec_norm_path = ppo_path.replace(".zip", "_vec_normalize.pkl")
        if os.path.exists(vec_norm_path):
            vec_env = VecNormalize.load(vec_norm_path, vec_env)
        else:
            vec_env = VecNormalize(vec_env, norm_obs=True, norm_reward=False)
        vec_env.training = False
        vec_env.norm_reward = False
    elif model_name == "dqn":
        agent = DuelingDDQNAgent(state_dim=state_dim, action_dim=action_dim, device=device)
        for name in ["comparison_dqn_best.pth", "comparison_dqn_final.pth"]:
            p = os.path.join(models_path, name)
            if os.path.exists(p):
                agent.load(p)
                break
        else:
            agent.load(os.path.join(REPO_ROOT, "kongtrae", "models", "comparison_dqn_best.pth"))
    elif model_name == "lstm":
        seq_len = 24
        agent = LSTMDDQNAgent(state_dim=state_dim, action_dim=action_dim, seq_len=seq_len, device=device)
        history = SequenceStateWrapper(seq_len=seq_len, state_dim=state_dim)
        for name in ["comparison_lstm_dqn_best.pth", "comparison_lstm_dqn_final.pth"]:
            p = os.path.join(models_path, name)
            if os.path.exists(p):
                agent.load(p)
                break
        else:
            agent.load(os.path.join(REPO_ROOT, "kongtrae", "models", "comparison_lstm_dqn_best.pth"))
    else:
        raise ValueError(f"Unknown model: {model_name}")

    TICK_OFFSET = int(round((DEC0 - DEC1) * math.log(10) / math.log(1.0001)))

    print(f"🤖 Replaying {model_name.upper()} model...")
    obs, _ = env.reset()
    if model_name == "ppo":
        vec_obs = vec_env.reset()
    if model_name == "lstm":
        history.reset()
        for _ in range(seq_len - 1):
            history.push(obs)

    hourly_decisions = []
    done = False
    while not done:
        ts = env.timestamps[env.idx]
        price = env.hourly_data.prices.get(ts, 0.0)

        if model_name == "ppo":
            action, _ = ppo.predict(vec_obs, deterministic=True)
            action_int = int(action[0]) if hasattr(action, "__len__") else int(action)
        elif model_name == "dqn":
            action_int = agent.select_action(obs, deterministic=True)
        else:
            history.push(obs)
            seq = history.get_sequence()
            action_int = agent.select_action(seq, deterministic=True)

        obs, reward, done, trunc, _ = env.step(action_int)
        if model_name == "ppo":
            vec_obs, _, _, _ = vec_env.step(np.array([action_int]))

        agent_center_sim = env.position_center_tick
        agent_width = env.position_width
        if env.has_position and agent_width > 0:
            agent_center_onchain = agent_center_sim - TICK_OFFSET
            lower_onchain = agent_center_onchain - agent_width * TICK_SPACING
            upper_onchain = agent_center_onchain + agent_width * TICK_SPACING
        else:
            agent_center_onchain = lower_onchain = upper_onchain = 0

        hourly_decisions.append({
            "timestamp": ts,
            "price": price,
            "action": action_int,
            "has_position": env.has_position,
            "position_width": agent_width,
            "center_tick_sim": agent_center_sim,
            "center_tick_onchain": agent_center_onchain,
            "lower_tick_onchain": lower_onchain,
            "upper_tick_onchain": upper_onchain,
        })
        done = done or trunc

    hourly_index = {d["timestamp"]: d for d in hourly_decisions}
    test_start = hourly_decisions[0]["timestamp"]
    test_end = hourly_decisions[-1]["timestamp"] + pd.Timedelta(hours=1)
    test_swaps = swaps[(swaps["evt_block_time"] >= test_start) &
                      (swaps["evt_block_time"] < test_end)].copy()
    print(f"   Swaps in test period: {len(test_swaps):,}")

    total_agent_fee = 0.0
    total_pool_fee = 0.0
    swaps_in_range = 0

    for _, swap in test_swaps.iterrows():
        swap_hour = swap["evt_block_time"].floor("h")
        decision = hourly_index.get(swap_hour)
        if decision is None or not decision["has_position"]:
            continue

        width = decision["position_width"]
        center_onchain = decision["center_tick_onchain"]
        lower_onchain = decision["lower_tick_onchain"]
        upper_onchain = decision["upper_tick_onchain"]
        swap_tick = int(swap["tick"])
        pool_L = float(swap["liquidity"])

        if pool_L <= 0:
            continue
        if swap_tick < lower_onchain or swap_tick > upper_onchain:
            continue

        swaps_in_range += 1
        sqrt_x96 = int(swap["sqrtpricex96"])
        price_usd = sqrt_price_x96_to_price_simple(sqrt_x96)

        amount0 = float(swap["amount0"])
        amount1 = float(swap["amount1"])
        if amount0 > 0:
            fee_raw = abs(amount0) * POOL_FEE / (1_000_000 - POOL_FEE)
            fee_usd = fee_raw / (10**DEC0) * price_usd
        else:
            fee_raw = abs(amount1) * POOL_FEE / (1_000_000 - POOL_FEE)
            fee_usd = fee_raw / (10**DEC1)

        total_pool_fee += fee_usd
        agent_L = compute_agent_L_onchain(capital, price_usd, center_onchain, width)
        if agent_L <= 0:
            continue
        agent_fee = fee_usd * (agent_L / pool_L)
        total_agent_fee += agent_fee

    test_swaps["price"] = test_swaps["sqrtpricex96"].apply(
        lambda x: sqrt_price_x96_to_price_simple(int(x))
    )
    swap_prices_by_hour = {}
    for hour, grp in test_swaps.groupby(test_swaps["evt_block_time"].dt.floor("h")):
        swap_prices_by_hour[hour] = grp["price"].values.astype(np.float64)

    pool_fee_rate = POOL_FEE / 1_000_000
    total_lvr = 0.0
    for d in hourly_decisions:
        if not d["has_position"] or d["position_width"] <= 0:
            continue
        ts = d["timestamp"]
        swap_prices = swap_prices_by_hour.get(ts)
        if swap_prices is None or len(swap_prices) < 2:
            continue
        L_sim = compute_agent_L_sim(capital, d["price"], d["center_tick_sim"], d["position_width"])
        if L_sim <= 0:
            continue
        p_lower = 1.0001 ** (d["center_tick_sim"] - d["position_width"] * TICK_SPACING)
        p_upper = 1.0001 ** (d["center_tick_sim"] + d["position_width"] * TICK_SPACING)
        for i in range(len(swap_prices) - 1):
            pi, pi1 = swap_prices[i], swap_prices[i + 1]
            if (pi < p_lower and pi1 < p_lower) or (pi > p_upper and pi1 > p_upper):
                continue
            pi_c = max(p_lower, min(p_upper, pi))
            pi1_c = max(p_lower, min(p_upper, pi1))
            V_i = position_value_at(pi_c, L_sim, p_lower, p_upper)
            V_i1 = position_value_at(pi1_c, L_sim, p_lower, p_upper)
            x_i = x_at_price(pi_c, L_sim, p_lower, p_upper)
            total_lvr += (V_i1 - V_i) - x_i * (pi1_c - pi_c)

    rebalance_count = sum(1 for d in hourly_decisions if d["action"] != 0)
    if rebalance_total_cost is not None:
        total_gas_cost = 0.0
        swap_fee_cost = 0.0
        total_rebalance_cost = rebalance_count * rebalance_total_cost
    else:
        total_gas_cost = rebalance_count * gas_cost
        swap_fee_cost = 0.5 * pool_fee_rate * capital * rebalance_count
        total_rebalance_cost = total_gas_cost + swap_fee_cost
    # Slippage / price impact on rebalance swap (money you lose in practice)
    slippage_cost = rebalance_count * slippage_per_rebalance
    total_rebalance_cost += slippage_cost

    # Hours in range and out-of-range opportunity cost (IL when stuck in one asset)
    hours_with_position = 0
    hours_in_range = 0
    out_of_range_cost = 0.0
    for d in hourly_decisions:
        if not d["has_position"] or d["position_width"] <= 0:
            continue
        hours_with_position += 1
        p_lo = 1.0001 ** (d["center_tick_sim"] - d["position_width"] * TICK_SPACING)
        p_hi = 1.0001 ** (d["center_tick_sim"] + d["position_width"] * TICK_SPACING)
        in_range = p_lo <= d["price"] <= p_hi
        if in_range:
            hours_in_range += 1
        elif out_of_range_opportunity_apy > 0:
            L_sim = compute_agent_L_sim(capital, d["price"], d["center_tick_sim"], d["position_width"])
            if L_sim > 0:
                pos_val = position_value_at(d["price"], L_sim, p_lo, p_hi)
                out_of_range_cost += pos_val * (out_of_range_opportunity_apy / 8760.0)
    pct_in_range = (hours_in_range / hours_with_position * 100) if hours_with_position else 0.0

    net_pnl = total_agent_fee + total_lvr - total_rebalance_cost - out_of_range_cost
    test_hours = len(hourly_decisions)
    test_days = test_hours / 24
    period_start = hourly_decisions[0]["timestamp"]
    period_end = hourly_decisions[-1]["timestamp"] + pd.Timedelta(hours=1)

    print(f"\n{'=' * 60}")
    print(f"  RESULTS – {model_name.upper()} | ${capital} capital (sim13)")
    print(f"{'=' * 60}")
    print(f"  Eval period:      {period_start.date()} → {period_end.date()}")
    print(f"  Swaps in range:   {swaps_in_range:,}")
    print(f"  Hours in range:   {hours_in_range} / {hours_with_position} ({pct_in_range:.1f}%)")
    print(f"  Rebalances:       {rebalance_count}")
    print(f"  ")
    print(f"  Gross fees:       ${total_agent_fee:.4f}")
    print(f"  LVR (cost):       ${total_lvr:.4f}")
    if rebalance_total_cost is not None:
        print(f"  Rebalance cost:   ${total_rebalance_cost:.2f} (${rebalance_total_cost}/rebalance, from e.g. Llaminet eval)")
    else:
        print(f"  Gas cost:         ${total_gas_cost:.2f} ({gas_cost}/rebalance)")
        print(f"  Swap fee cost:    ${swap_fee_cost:.4f}")
    if slippage_cost > 0:
        print(f"  Slippage cost:    ${slippage_cost:.4f} (${slippage_per_rebalance}/rebalance)")
    if out_of_range_cost > 0:
        print(f"  Out-of-range IL:  ${out_of_range_cost:.4f} (opportunity cost, {out_of_range_opportunity_apy*100:.1f}% APY)")
    print(f"  ")
    print(f"  NET PnL:          ${net_pnl:.4f}")
    print(f"  Net PnL/day:      ${net_pnl/test_days:.4f}")
    print(f"  Net APR:          {net_pnl/test_days*365/capital*100:.2f}%")
    print(f"{'=' * 60}")
    return {
        "period_start": period_start,
        "period_end": period_end,
        "test_days": test_days,
        "agent_fees": total_agent_fee,
        "lvr": total_lvr,
        "gas_cost": total_gas_cost,
        "swap_fee_cost": swap_fee_cost,
        "net_pnl": net_pnl,
        "rebalance_count": rebalance_count,
        "swaps_in_range": swaps_in_range,
        "hours_in_range": hours_in_range,
        "hours_with_position": hours_with_position,
        "pct_in_range": pct_in_range,
        "out_of_range_cost": out_of_range_cost,
    }


def main():
    default_downloaded = os.path.join(REPO_ROOT, "downloaded_data_csv")
    default_models = os.path.join(SIM_DIR, "run_004", "models")

    parser = argparse.ArgumentParser(description="Compute PnL from downloaded data + run_004 (sim13)")
    parser.add_argument("--downloaded-dir", default=default_downloaded,
                        help="Path to downloaded_data_csv")
    parser.add_argument("--model", default="dqn", choices=["ppo", "dqn", "lstm"])
    parser.add_argument("--model-dir", default=default_models,
                        help="Path to model files (sim13/run_004/models or kongtrae/models)")
    parser.add_argument("--capital", type=float, default=100.0)
    parser.add_argument("--gas-cost", type=float, default=0.02,
                        help="Gas cost per rebalance (Arbitrum L2 ~0.02, Mainnet ~0.50)")
    parser.add_argument("--rebalance-total-cost", type=float, default=None,
                        help="If set, use this $ per rebalance instead of gas+swap fee (e.g. 0.044 from Llaminet Arbitrum eval for $100)")
    parser.add_argument("--slippage-per-rebalance", type=float, default=0.0,
                        help="Extra $ per rebalance for slippage/price impact (money you lose on the rebalance swap). e.g. 0.005 for small size.")
    parser.add_argument("--out-of-range-opportunity-apy", type=float, default=0.0,
                        help="APY (decimal, e.g. 0.05 for 5%%) as opportunity cost when position is out of range (IL). Applied per hour to position value. Env uses ~5%%.")
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--mode", default="test", choices=["test", "full"])
    parser.add_argument("--test-start", default="2026-01-01",
                        help="Evaluate PnL from this date onward (e.g. 2026-01-01 for 2026 data). Set to empty to use default test split.")
    args = parser.parse_args()

    test_start = args.test_start.strip() or None

    model_dir = args.model_dir
    if not os.path.isabs(model_dir):
        model_dir = os.path.normpath(os.path.join(SIM_DIR, model_dir))
    if not os.path.exists(model_dir):
        model_dir = os.path.join(REPO_ROOT, "kongtrae", "models")
        print(f"⚠️  run_004 models not found, using kongtrae/models")

    run_fee_calculation(
        args.downloaded_dir,
        args.model,
        args.capital,
        model_dir,
        args.device,
        args.mode,
        gas_cost=args.gas_cost,
        test_start=test_start,
        rebalance_total_cost=args.rebalance_total_cost,
        slippage_per_rebalance=args.slippage_per_rebalance,
        out_of_range_opportunity_apy=args.out_of_range_opportunity_apy,
    )


if __name__ == "__main__":
    main()
