#!/usr/bin/env python3
"""
DQN and PPO 1-week decision visualization (same style as LSTM 1-week).

Run this after PPO and DQN finish training (e.g. while LSTM is still running).
Uses the same 1-week window and 4-panel plot: price + LP ranges, actions,
step reward, total money.

Usage (from repo root):
    .venv/bin/python research/simulation_13/scripts/visualize_dqn_ppo_1week.py \
      --data-dir research/simulation_13/training_data \
      --run-dir research/simulation_13/run_005 \
      --start-date 2026-01-15 --days 7 --capital 100
"""

import os
import sys
import argparse
from datetime import timedelta

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SIM_DIR = os.path.normpath(os.path.join(SCRIPT_DIR, ".."))
REPO_ROOT = os.path.normpath(os.path.join(SCRIPT_DIR, "..", "..", ".."))
sys.path.insert(0, SIM_DIR)

WIDTHS = [1, 3, 5, 10, 20, 40]


def slice_hourly_data_window(hourly_data, start_ts: pd.Timestamp, days: int):
    """Slice hourly data to [start_ts, start_ts + days)."""
    from uniswap_v3_dqn_paper import HourlyDataExtended
    end_ts = start_ts + timedelta(days=days)
    timestamps = [t for t in hourly_data.timestamps if start_ts <= t < end_ts]
    if not timestamps:
        raise ValueError(f"No data in range {start_ts.date()} to {end_ts.date()}")
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


def run_dqn_1week(data_dir: str, model_path: str, start_date: str, days: int, device: str, initial_capital: float):
    """Run DQN on 1-week window; return trajectory dict (same shape as LSTM 1-week)."""
    from uniswap_v3_dqn_paper import (
        prepare_hourly_data_extended,
        UniswapV3DQNEnv,
        DuelingDDQNAgent,
        tick_to_price,
    )
    hourly_data = prepare_hourly_data_extended(data_dir)
    start_ts = pd.Timestamp(start_date, tz="UTC")
    hourly_data = slice_hourly_data_window(hourly_data, start_ts, days)
    env = UniswapV3DQNEnv(hourly_data, initial_capital_usd=initial_capital, mode="full")
    agent = DuelingDDQNAgent(state_dim=env.state_dim, action_dim=env.action_space.n, device=device)
    agent.load(model_path)
    agent.epsilon = 0.0

    timestamps, prices, actions, rewards, cumulative_rewards = [], [], [], [], []
    reward_positives, reward_negatives = [], []
    position_values, lp_windows = [], []
    state, _ = env.reset()
    done = False
    cum_reward = 0.0
    current_window_start, current_lower, current_upper = None, None, None

    while not done:
        t = env.timestamps[env.idx]
        price = env._get_price(t)
        old_center, old_width = env.position_center_tick, env.position_width
        action = agent.select_action(state, deterministic=True)
        state, reward, terminated, truncated, info = env.step(action)
        done = terminated or truncated

        timestamps.append(t)
        prices.append(price)
        actions.append(action)
        rewards.append(reward)
        cum_reward += reward
        cumulative_rewards.append(cum_reward)
        reward_positives.append(info.get("reward_positive", max(0, reward)))
        reward_negatives.append(info.get("reward_negative", max(0, -reward)))
        position_values.append(info.get("total_value", env.position_value))

        if env.has_position:
            lower_tick = env.position_center_tick - env.position_width * env.tick_spacing
            upper_tick = env.position_center_tick + env.position_width * env.tick_spacing
            lower_price, upper_price = tick_to_price(lower_tick), tick_to_price(upper_tick)
            if current_window_start is None or (env.position_center_tick != old_center or env.position_width != old_width):
                if current_window_start is not None:
                    lp_windows.append((current_window_start, t, current_lower, current_upper))
                current_window_start, current_lower, current_upper = t, lower_price, upper_price
        else:
            if current_window_start is not None:
                lp_windows.append((current_window_start, t, current_lower, current_upper))
                current_window_start = None
    if current_window_start is not None:
        lp_windows.append((current_window_start, timestamps[-1], current_lower, current_upper))

    return {
        "timestamps": timestamps,
        "prices": prices,
        "actions": actions,
        "rewards": rewards,
        "reward_positives": reward_positives,
        "reward_negatives": reward_negatives,
        "cumulative_rewards": cumulative_rewards,
        "position_values": position_values,
        "lp_windows": lp_windows,
        "initial_capital": initial_capital,
        "accumulated_costs": info.get("accumulated_costs", 0.0),
    }


def run_ppo_1week(data_dir: str, model_path: str, start_date: str, days: int, initial_capital: float):
    """Run PPO on 1-week window; return trajectory dict."""
    from uniswap_v3_ppo_paper import UniswapV3PaperEnv, tick_to_price, make_env_fn
    from uniswap_v3_dqn_paper import prepare_hourly_data_extended
    from stable_baselines3 import PPO
    from stable_baselines3.common.vec_env import DummyVecEnv, VecNormalize

    hourly_data = prepare_hourly_data_extended(data_dir)
    start_ts = pd.Timestamp(start_date, tz="UTC")
    hourly_data = slice_hourly_data_window(hourly_data, start_ts, days)

    # Use mode="full" so env uses all timestamps (we already sliced to 1 week).
    # mode="test" would use only last 15% -> ~1 day when data is 7 days.
    eval_fn = make_env_fn(hourly_data, initial_capital_usd=initial_capital, mode="full")
    vec_env = DummyVecEnv([eval_fn])
    vec_env = VecNormalize(vec_env, norm_obs=True, norm_reward=False, clip_obs=10.0)
    vec_normalize_path = model_path.replace(".zip", "_vec_normalize.pkl")
    if os.path.exists(vec_normalize_path):
        vec_env = VecNormalize.load(vec_normalize_path, vec_env)
    vec_env.training = False
    vec_env.norm_reward = False

    raw_env = UniswapV3PaperEnv(hourly_data, initial_capital_usd=initial_capital, mode="full")
    model = PPO.load(model_path, env=vec_env)

    timestamps, prices, actions, rewards, cumulative_rewards = [], [], [], [], []
    reward_positives, reward_negatives = [], []
    position_values, lp_windows = [], []
    obs = vec_env.reset()
    raw_env.reset()
    done = False
    cum_reward = 0.0
    current_window_start, current_lower, current_upper = None, None, None

    while not done:
        t = raw_env.timestamps[raw_env.idx]
        price = raw_env._get_price(t)
        old_lower, old_upper = raw_env.lp_lower_tick, raw_env.lp_upper_tick
        action, _ = model.predict(obs, deterministic=True)
        obs, reward, dones, _ = vec_env.step(action)[:4]  # SB3 VecEnv returns (obs, rewards, dones, infos)
        _, r, _, _, step_info = raw_env.step(int(action[0]))
        done = bool(dones[0]) if hasattr(dones, "__len__") else bool(dones)

        # Use reward from raw_env (same source as total_value) so Initial + cum_reward = Total money - opportunity_cost
        r = float(r)
        timestamps.append(t)
        prices.append(price)
        actions.append(int(action[0]))
        rewards.append(r)
        cum_reward += r
        cumulative_rewards.append(cum_reward)
        reward_positives.append(step_info.get("reward_positive", max(0, r)))
        reward_negatives.append(step_info.get("reward_negative", max(0, -r)))

        # Total money = position + fee income (cash-out value); fallback to position value if no total_value in info
        pv = step_info.get("total_value")
        if pv is None:
            if raw_env.has_lp and raw_env.liquidity > 0:
                lp_lower = tick_to_price(raw_env.lp_lower_tick)
                lp_upper = tick_to_price(raw_env.lp_upper_tick)
                pv = raw_env._compute_position_value(price, lp_lower, lp_upper, raw_env.liquidity)
            else:
                pv = initial_capital
        position_values.append(pv)

        if raw_env.has_lp:
            lower_price = tick_to_price(raw_env.lp_lower_tick)
            upper_price = tick_to_price(raw_env.lp_upper_tick)
            if current_window_start is None or (raw_env.lp_lower_tick != old_lower or raw_env.lp_upper_tick != old_upper):
                if current_window_start is not None:
                    lp_windows.append((current_window_start, t, current_lower, current_upper))
                current_window_start, current_lower, current_upper = t, lower_price, upper_price
        else:
            if current_window_start is not None:
                lp_windows.append((current_window_start, t, current_lower, current_upper))
                current_window_start = None
    if current_window_start is not None:
        lp_windows.append((current_window_start, timestamps[-1], current_lower, current_upper))

    return {
        "timestamps": timestamps,
        "prices": prices,
        "actions": actions,
        "rewards": rewards,
        "reward_positives": reward_positives,
        "reward_negatives": reward_negatives,
        "cumulative_rewards": cumulative_rewards,
        "position_values": position_values,
        "lp_windows": lp_windows,
        "initial_capital": initial_capital,
        "accumulated_costs": step_info.get("accumulated_costs", 0.0),
    }


def plot_1week(data: dict, save_path: str, model_name: str, title_suffix: str = ""):
    """Same 4-panel plot as LSTM 1-week (price+ranges, actions, step reward, total money)."""
    timestamps = data["timestamps"]
    prices = data["prices"]
    n_holds = sum(1 for a in data["actions"] if a == 0)
    n_rebalances = sum(1 for a in data["actions"] if a > 0)

    fig, axes = plt.subplots(4, 1, figsize=(12, 12), height_ratios=[2, 0.8, 1, 1])
    fig.suptitle(f"{model_name} – Model decisions over 1 week{title_suffix}", fontsize=14, fontweight="bold", y=1.02)

    ax1 = axes[0]
    ax1.plot(timestamps, prices, "b-", linewidth=1.5, label="ETH/USDT price", zorder=10)
    for start, end, lower, upper in data["lp_windows"]:
        ax1.fill_between([start, end], [lower, lower], [upper, upper],
                         alpha=0.35, color="purple", edgecolor="darkviolet", linewidth=1, zorder=5)
    ax1.set_ylabel("Price (USD)", fontsize=11)
    ax1.legend(loc="upper right", fontsize=9)
    ax1.grid(True, alpha=0.3)
    ax1.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d %H:%M"))
    ax1.xaxis.set_major_locator(mdates.DayLocator(interval=1))
    ax1.set_title(f"Price & LP ranges  |  HOLD: {n_holds}  Rebalances: {n_rebalances}  Windows: {len(data['lp_windows'])}", fontsize=10)

    ax2 = axes[1]
    action_colors = ["gray" if a == 0 else "purple" for a in data["actions"]]
    ax2.scatter(timestamps, data["actions"], c=action_colors, s=12, alpha=0.8)
    ax2.set_ylabel("Action", fontsize=11)
    ax2.set_yticks(range(7))
    ax2.set_yticklabels(["HOLD"] + [f"W{w}" for w in WIDTHS])
    ax2.set_ylim(-0.5, 6.5)
    ax2.grid(True, alpha=0.3, axis="x")
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d %H:%M"))
    ax2.set_title("Action each hour (HOLD vs width 1–40 ticks)", fontsize=10)

    ax3 = axes[2]
    rewards = data["rewards"]
    r_pos = data.get("reward_positives")
    r_neg = data.get("reward_negatives")
    if r_pos is not None and r_neg is not None:
        # Green above zero (fee + gains), red below zero (costs + losses) — no overlap
        # Red = rebalance cost (gas+swap) + OOR opportunity cost + position value losses
        width_bar = 0.03
        ax3.bar(timestamps, r_pos, width=width_bar, color="green", alpha=0.7, align="edge", label="Positive (value gain incl. fee)")
        ax3.bar(timestamps, [-v for v in r_neg], width=width_bar, color="red", alpha=0.7, align="edge", label="Negative (value loss + OOR penalty)")
        n_pos = sum(1 for r in rewards if r > 0)
        n_neg = sum(1 for r in rewards if r < 0)
        acc_costs = data.get("accumulated_costs", 0.0)
        ax3.set_title(f"Hourly reward  |  {n_pos} pos, {n_neg} neg hours  |  Rebalance cost (gas+swap): ${acc_costs:.2f}", fontsize=10)
    else:
        colors = ["green" if r >= 0 else "red" for r in rewards]
        ax3.bar(timestamps, rewards, width=0.03, color=colors, alpha=0.7, align="edge")
        n_neg = sum(1 for r in rewards if r < 0)
        ax3.set_title(f"Hourly reward (green = add, red = deduct)  |  {n_neg} hours with deduction", fontsize=10)
    ax3.axhline(y=0, color="k", linestyle="-", linewidth=0.5)
    ax3.set_ylabel("Step reward ($)", fontsize=11)
    if r_pos is not None and r_neg is not None:
        ax3.legend(loc="upper right", fontsize=8)
    ax3.grid(True, alpha=0.3, axis="y")
    ax3.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d %H:%M"))

    ax4 = axes[3]
    pv = data.get("position_values")
    cap = data.get("initial_capital")
    cum = data["cumulative_rewards"]
    if pv is not None and cap is not None:
        ax4.plot(timestamps, pv, "darkgreen", linewidth=2, label="Total money (position + fees − costs)")
        ax4.axhline(y=cap, color="gray", linestyle="--", linewidth=1, label=f"Initial capital ${cap:.0f}")
        # Cumulative reward = fee + (position value change) − costs − opportunity; so Initial + cum = Total money − opportunity cost
        ax4.plot(timestamps, [cap + r for r in cum], "purple", linewidth=1, alpha=0.7, linestyle="--", label="Initial + cumulative reward")
        ax4.fill_between(timestamps, cap, pv, where=[v <= cap for v in pv], alpha=0.25, color="red")
        ax4.set_ylabel("Value ($)", fontsize=11)
        ax4.set_xlabel("Date", fontsize=11)
        acc_costs = data.get("accumulated_costs", 0.0)
        ax4.set_title(f"Total money = position + fees − costs (rebal: ${acc_costs:.2f}).  Final: ${pv[-1]:.2f}", fontsize=9)
    else:
        cap0 = data.get("initial_capital", 0)
        ax4.plot(timestamps, [cap0 + r for r in cum], "purple", linewidth=2, label="Cumulative reward")
        ax4.axhline(y=0, color="k", linestyle="--", alpha=0.5)
        ax4.set_ylabel("Value ($)", fontsize=11)
        ax4.set_xlabel("Date", fontsize=11)
        ax4.set_title(f"Cumulative reward  |  Final: ${cap0 + cum[-1]:.2f}", fontsize=10)
    ax4.legend(loc="upper right", fontsize=8)
    ax4.grid(True, alpha=0.3)
    ax4.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d %H:%M"))

    for ax in axes:
        plt.setp(ax.xaxis.get_majorticklabels(), rotation=20, ha="right")
    plt.tight_layout()
    plt.savefig(save_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  Saved: {save_path}")
    return save_path


def main():
    parser = argparse.ArgumentParser(description="DQN and PPO 1-week decision visualization (run after PPO/DQN train, e.g. while LSTM runs)")
    parser.add_argument("--data-dir", default=os.path.join(SIM_DIR, "training_data"), help="Path to training_data")
    parser.add_argument("--run-dir", default=os.path.join(SIM_DIR, "run_005"), help="Run dir containing models/")
    parser.add_argument("--start-date", default="2026-01-15", help="Start date for 1-week window (YYYY-MM-DD)")
    parser.add_argument("--days", type=int, default=7, help="Number of days")
    parser.add_argument("--capital", type=float, default=100.0)
    parser.add_argument("--device", default="cpu")
    args = parser.parse_args()

    models_dir = os.path.join(args.run_dir, "models")
    viz_dir = os.path.join(args.run_dir, "visualizations")
    os.makedirs(viz_dir, exist_ok=True)
    title_suffix = f"  |  {args.start_date} (${args.capital:.0f})"

    # DQN
    dqn_path = os.path.join(models_dir, "comparison_dqn_best.pth")
    if not os.path.exists(dqn_path):
        dqn_path = os.path.join(models_dir, "comparison_dqn_final.pth")
    if os.path.exists(dqn_path):
        print("Running DQN on 1-week window...", flush=True)
        dqn_data = run_dqn_1week(args.data_dir, dqn_path, args.start_date, args.days, args.device, args.capital)
        plot_1week(dqn_data, os.path.join(viz_dir, f"dqn_1week_{args.start_date}.png"), "DQN", title_suffix)
    else:
        print(f"  Skip DQN: no model at {dqn_path}", flush=True)

    # PPO
    ppo_path = os.path.join(models_dir, "comparison_ppo.zip")
    if os.path.exists(ppo_path):
        print("Running PPO on 1-week window...", flush=True)
        ppo_data = run_ppo_1week(args.data_dir, ppo_path, args.start_date, args.days, args.capital)
        plot_1week(ppo_data, os.path.join(viz_dir, f"ppo_1week_{args.start_date}.png"), "PPO", title_suffix)
    else:
        print(f"  Skip PPO: no model at {ppo_path}", flush=True)

    print("Done.")


if __name__ == "__main__":
    main()
