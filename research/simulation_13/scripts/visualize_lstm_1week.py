#!/usr/bin/env python3
"""
LSTM model decision visualization over 1 week for presentation.

Loads training data, slices to a 1-week window, runs the LSTM agent, and saves
a figure: price + LP ranges, action timeline, cumulative reward.

Usage (from repo root):
    .venv/bin/python research/simulation_13/scripts/visualize_lstm_1week.py --start-date 2026-01-15
    .venv/bin/python research/simulation_13/scripts/visualize_lstm_1week.py --data-dir training_data --days 7 --capital 100
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

# Widths for action labels (match env)
WIDTHS = [1, 3, 5, 10, 20, 40]


def slice_hourly_data_window(hourly_data, start_ts: pd.Timestamp, days: int):
    """Slice hourly data to [start_ts, start_ts + days] (inclusive of start, end exclusive of last hour past days)."""
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


def run_lstm_trajectory(data_dir: str, model_path: str, start_date: str, days: int,
                        seq_len: int, device: str, initial_capital: float):
    """Run LSTM over the 1-week window and return trajectory dict."""
    from uniswap_v3_dqn_paper import (
        prepare_hourly_data_extended,
        UniswapV3DQNEnv,
        LSTMDDQNAgent,
        tick_to_price,
    )

    hourly_data = prepare_hourly_data_extended(data_dir)
    start_ts = pd.Timestamp(start_date, tz="UTC")
    hourly_data = slice_hourly_data_window(hourly_data, start_ts, days)
    env = UniswapV3DQNEnv(hourly_data, initial_capital_usd=initial_capital, mode="full")

    agent = LSTMDDQNAgent(
        state_dim=env.state_dim,
        action_dim=env.action_space.n,
        seq_len=seq_len,
        device=device,
    )
    agent.load(model_path)
    agent.epsilon = 0.0

    timestamps = []
    prices = []
    actions = []
    rewards = []
    reward_positives = []
    reward_negatives = []
    cumulative_rewards = []
    position_values = []
    in_range_flags = []
    lp_windows = []

    state, _ = env.reset()
    agent.reset_sequence()
    agent.update_sequence(state)

    done = False
    cum_reward = 0.0
    current_window_start = None
    current_lower = None
    current_upper = None

    while not done:
        t = env.timestamps[env.idx]
        price = env._get_price(t)
        old_center = env.position_center_tick
        old_width = env.position_width

        state_seq = agent.get_current_sequence()
        action = agent.select_action(state_seq, deterministic=True)
        state, reward, terminated, truncated, info = env.step(action)
        done = terminated or truncated
        agent.update_sequence(state)

        timestamps.append(t)
        prices.append(price)
        actions.append(action)
        rewards.append(reward)
        cum_reward += reward
        cumulative_rewards.append(cum_reward)
        reward_positives.append(info.get("reward_positive", max(0, reward)))
        reward_negatives.append(info.get("reward_negative", max(0, -reward)))
        position_values.append(info.get("total_value", env.position_value))
        in_range_flags.append(info.get("in_range", False))

        if env.has_position:
            lower_tick = env.position_center_tick - env.position_width * env.tick_spacing
            upper_tick = env.position_center_tick + env.position_width * env.tick_spacing
            lower_price = tick_to_price(lower_tick)
            upper_price = tick_to_price(upper_tick)
            if current_window_start is None or (env.position_center_tick != old_center or env.position_width != old_width):
                if current_window_start is not None:
                    lp_windows.append((current_window_start, t, current_lower, current_upper))
                current_window_start = t
                current_lower = lower_price
                current_upper = upper_price
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
        "in_range_flags": in_range_flags,
        "lp_windows": lp_windows,
        "initial_capital": initial_capital,
    }


def action_label(a: int) -> str:
    if a == 0:
        return "HOLD"
    k = a - 1
    if 0 <= k < len(WIDTHS):
        return f"W{WIDTHS[k]}"
    return str(a)


def plot_lstm_1week(lstm_data: dict, save_path: str, title_suffix: str = ""):
    """Presentation-ready plot: price + LP ranges, actions, cumulative reward."""
    from matplotlib.patches import Patch
    from matplotlib.lines import Line2D

    timestamps = lstm_data["timestamps"]
    prices = lstm_data["prices"]
    n_holds = sum(1 for a in lstm_data["actions"] if a == 0)
    n_rebalances = sum(1 for a in lstm_data["actions"] if a > 0)

    fig, axes = plt.subplots(4, 1, figsize=(12, 12), height_ratios=[2, 0.8, 1, 1])
    fig.suptitle(f"LSTM DQN – Model decisions over 1 week{title_suffix}", fontsize=14, fontweight="bold", y=1.02)

    # Panel 1: Price + LP windows
    ax1 = axes[0]
    ax1.plot(timestamps, prices, "b-", linewidth=1.5, label="ETH/USDC price", zorder=10)
    for start, end, lower, upper in lstm_data["lp_windows"]:
        ax1.fill_between([start, end], [lower, lower], [upper, upper],
                         alpha=0.35, color="purple", edgecolor="darkviolet", linewidth=1, zorder=5)
    ax1.set_ylabel("Price (USD)", fontsize=11)
    ax1.legend(loc="upper right", fontsize=9)
    ax1.grid(True, alpha=0.3)
    ax1.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d %H:%M"))
    ax1.xaxis.set_major_locator(mdates.DayLocator(interval=1))
    ax1.set_title(f"Price & LP ranges  |  HOLD: {n_holds}  Rebalances: {n_rebalances}  Windows: {len(lstm_data['lp_windows'])}", fontsize=10)

    # Panel 2: Action over time (discrete)
    ax2 = axes[1]
    action_colors = ["gray" if a == 0 else "purple" for a in lstm_data["actions"]]
    ax2.scatter(timestamps, lstm_data["actions"], c=action_colors, s=12, alpha=0.8)
    ax2.set_ylabel("Action", fontsize=11)
    ax2.set_yticks(range(7))
    ax2.set_yticklabels(["HOLD"] + [f"W{w}" for w in WIDTHS])
    ax2.set_ylim(-0.5, 6.5)
    ax2.grid(True, alpha=0.3, axis="x")
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d %H:%M"))
    ax2.set_title("Action each hour (HOLD vs width 1–40 ticks)", fontsize=10)

    # Panel 3: Step reward (positive = green, negative = red, shown separately)
    ax3 = axes[2]
    rewards = lstm_data["rewards"]
    r_pos = lstm_data.get("reward_positives")
    r_neg = lstm_data.get("reward_negatives")
    if r_pos is not None and r_neg is not None:
        # Green above zero (fee + gains), red below zero (costs + losses) — no overlap
        width_bar = 0.03
        ax3.bar(timestamps, r_pos, width=width_bar, color="green", alpha=0.7, align="edge", label="Positive (fee + gains)")
        ax3.bar(timestamps, [-v for v in r_neg], width=width_bar, color="red", alpha=0.7, align="edge", label="Negative (costs + losses)")
        n_pos = sum(1 for r in rewards if r > 0)
        n_neg = sum(1 for r in rewards if r < 0)
        ax3.set_title(f"Hourly reward (green = positive, red = negative)  |  {n_pos} positive, {n_neg} negative hours", fontsize=10)
        ax3.legend(loc="upper right", fontsize=8)
    else:
        colors = ["green" if r >= 0 else "red" for r in rewards]
        ax3.bar(timestamps, rewards, width=0.03, color=colors, alpha=0.7, align="edge")
        n_neg = sum(1 for r in rewards if r < 0)
        ax3.set_title(f"Hourly reward (green = add, red = deduct)  |  {n_neg} hours with deduction", fontsize=10)
    ax3.axhline(y=0, color="k", linestyle="-", linewidth=0.5)
    ax3.set_ylabel("Step reward ($)", fontsize=11)
    ax3.grid(True, alpha=0.3, axis="y")
    ax3.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d %H:%M"))

    # Panel 4: Total money = position value (fees + LVR + costs + IL all in one)
    ax4 = axes[3]
    pv = lstm_data.get("position_values")
    cap = lstm_data.get("initial_capital")
    cum = lstm_data["cumulative_rewards"]
    if pv is not None and cap is not None:
        ax4.plot(timestamps, pv, "darkgreen", linewidth=2, label="Total money (net of costs)")
        ax4.axhline(y=cap, color="gray", linestyle="--", linewidth=1, label=f"Initial capital ${cap:.0f}")
        ax4.plot(timestamps, [cap + r for r in cum], "purple", linewidth=1, alpha=0.7, linestyle="--", label="Initial + cumulative reward")
        ax4.fill_between(timestamps, cap, pv, where=[v <= cap for v in pv], alpha=0.25, color="red")
        ax4.set_ylabel("Value ($)", fontsize=11)
        ax4.set_xlabel("Date", fontsize=11)
        final_pv = pv[-1]
        ax4.set_title(f"Total money (net: position + fees − gas − swap)  |  Final: ${final_pv:.2f}", fontsize=10)
    else:
        cap0 = lstm_data.get("initial_capital", 0)
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
    parser = argparse.ArgumentParser(description="LSTM 1-week decision visualization for presentation")
    parser.add_argument("--data-dir", default=os.path.join(SIM_DIR, "training_data"), help="Path to training_data")
    parser.add_argument("--model-dir", default=os.path.join(SIM_DIR, "run_004", "models"), help="Path to models")
    parser.add_argument("--start-date", default="2026-01-15", help="Start date for 1-week window (YYYY-MM-DD)")
    parser.add_argument("--days", type=int, default=7, help="Number of days to visualize")
    parser.add_argument("--capital", type=float, default=100.0)
    parser.add_argument("--seq-len", type=int, default=24)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--out", default=None, help="Output path (default: run_004/visualizations/lstm_1week_<date>.png)")
    args = parser.parse_args()

    model_dir = args.model_dir
    if not os.path.isabs(model_dir):
        model_dir = os.path.normpath(os.path.join(SIM_DIR, model_dir))
    if not os.path.exists(model_dir):
        model_dir = os.path.join(REPO_ROOT, "kongtrae", "models")
        print(f"Using models from: {model_dir}")
    model_path = os.path.join(model_dir, "comparison_lstm_dqn_best.pth")
    if not os.path.exists(model_path):
        model_path = os.path.join(model_dir, "comparison_lstm_dqn_final.pth")
    if not os.path.exists(model_path):
        print("ERROR: No LSTM model found (comparison_lstm_dqn_best.pth or _final.pth)")
        sys.exit(1)

    data_dir = args.data_dir
    if not os.path.isabs(data_dir):
        data_dir = os.path.normpath(os.path.join(SIM_DIR, data_dir))

    print(f"Data: {data_dir}")
    print(f"Window: {args.start_date} for {args.days} days")
    print(f"Model: {model_path}")

    lstm_data = run_lstm_trajectory(
        data_dir, model_path,
        args.start_date, args.days,
        args.seq_len, args.device, args.capital,
    )

    if args.out:
        save_path = args.out
    else:
        viz_dir = os.path.join(SIM_DIR, "run_004", "visualizations")
        os.makedirs(viz_dir, exist_ok=True)
        save_path = os.path.join(viz_dir, f"lstm_1week_{args.start_date}.png")

    plot_lstm_1week(lstm_data, save_path, title_suffix=f"  |  {args.start_date} (${args.capital:.0f})")
    print("Done.")


if __name__ == "__main__":
    main()
