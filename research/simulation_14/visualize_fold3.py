"""
Visualize Fold 3 DQN model on its test period (Nov 9 - Dec 9, 2025).
Panel 1: Price + LP width bands (accurate tick-based ranges)
Panel 2: Portfolio value over time
"""
import os
import sys
import math
import pickle

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.patches import Patch

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PACKAGE_ROOT = SCRIPT_DIR
PACKAGE_PARENT = os.path.dirname(PACKAGE_ROOT)
if PACKAGE_PARENT not in sys.path:
    sys.path.insert(0, PACKAGE_PARENT)

from kongtrae.training.uniswap_v3_ppo_paper import prepare_hourly_data, FEATURE_COLS
from kongtrae.training.uniswap_v3_hedged_fee_env import HEDGE_ACCOUNTING_CONTINUOUS
from kongtrae.training.uniswap_v3_hedged_hierarchical_env import UniswapV3HedgedThreeHeadEnv
from kongtrae.training.hedged_hierarchical_policy import (
    run_three_head_policy_episode,
    trace_metrics,
)
from kongtrae.training.train_hedged_three_head_v2_dqn import _v2_env_kwargs

# ── Load data ──
DATA_DIR = os.path.join(PACKAGE_PARENT, "training_data")
data = prepare_hourly_data(DATA_DIR)
timestamps = data.timestamps

# ── Fold 3 test range ──
test_start_str = "2025-11-09 12:00"
test_end_str = "2025-12-09 21:00"
test_start_idx = next(i for i, t in enumerate(timestamps) if str(t)[:16] >= test_start_str)
test_end_idx = next(i for i, t in enumerate(timestamps) if str(t)[:16] >= test_end_str)

print(f"Test range: {timestamps[test_start_idx]} -> {timestamps[test_end_idx - 1]}")
print(f"Hours: {test_end_idx - test_start_idx}")

# ── Load fold 3 v3 model ──
from kongtrae.training.three_head_dueling_dqn import ThreeHeadDoubleDuelingDQN

model_path = os.path.join(SCRIPT_DIR, "models", "dqn_three_head_v3_1h.zip")
vec_path = os.path.join(SCRIPT_DIR, "models", "dqn_three_head_v3_1h_vecnormalize.pkl")

model = ThreeHeadDoubleDuelingDQN.load(model_path, device="cpu")
with open(vec_path, "rb") as f:
    vec_normalize = pickle.load(f)

# ── Build policy wrapper ──
from dataclasses import dataclass

@dataclass
class Prediction:
    value: int
    q_gap: float = 0.0

class DQNPolicyWrapper:
    def __init__(self, model, vec_normalize):
        self.model = model
        self.vec_normalize = vec_normalize

    def predict(self, obs, return_q=False):
        obs_batch = np.array([obs], dtype=np.float32)
        obs_norm = self.vec_normalize.normalize_obs(obs_batch)
        action, _ = self.model.predict(obs_norm, deterministic=True)
        action_int = int(action[0]) if hasattr(action, '__len__') else int(action)
        return Prediction(value=action_int, q_gap=0.0)

policy = DQNPolicyWrapper(model, vec_normalize)
action_widths = (4, 6, 10, 20)

# ── Run episode ──
trace_df = run_three_head_policy_episode(
    data=data,
    three_head_policy=policy,
    capital=1000.0,
    mode="all",
    seed=42,
    hedge_accounting_mode=HEDGE_ACCOUNTING_CONTINUOUS,
    action_widths=action_widths,
    start_idx=test_start_idx,
    end_idx=test_end_idx,
    env_kwargs=_v2_env_kwargs(action_widths),
)

metrics = trace_metrics(trace_df)
print(f"PnL: ${metrics['pnl']:+.2f}, Cash: {metrics['cash_pct']:.0f}%, OOR: {metrics['oor_pct']:.0f}%")

# ── Prepare plot data ──
trace_df["timestamp"] = pd.to_datetime(trace_df["timestamp"])
trace_df["price"] = [data.prices[t] for t in [pd.Timestamp(ts) for ts in trace_df["timestamp"]]]

# Compute LP bounds from effective_action and price
TICK_SPACING = 10

def get_lp_bounds(row):
    """Get LP lower/upper price from the current position state."""
    state_after = row["next_position_state"]
    if state_after == "cash":
        return None, None, None
    # Parse width from effective_action
    ea = row["effective_action"]
    sw = row.get("selected_width", 0)
    if sw and sw > 0:
        return sw, None, None  # width known, bounds computed below
    return None, None, None

# Track LP position through time
lp_lower = []
lp_upper = []
lp_width_label = []
current_width = None
current_center = None

for _, row in trace_df.iterrows():
    ea = row["effective_action"]
    state_after = row["next_position_state"]
    price = row["price"]

    if ea.startswith("enter_w") or ea.startswith("recenter_w"):
        w = int(row["selected_width"])
        current_width = w
        # Compute bounds: center tick aligned to spacing, then +/- width*spacing
        tick = math.floor(math.log(price) / math.log(1.0001))
        center = (tick // TICK_SPACING) * TICK_SPACING
        lt = center - w * TICK_SPACING
        ut = center + w * TICK_SPACING
        lp_lower.append(1.0001 ** lt)
        lp_upper.append(1.0001 ** ut)
        lp_width_label.append(f"W{w}")
    elif ea == "exit_to_cash" or state_after == "cash":
        current_width = None
        lp_lower.append(None)
        lp_upper.append(None)
        lp_width_label.append("Cash")
    else:
        # hold - keep previous bounds
        if current_width is not None:
            lp_lower.append(lp_lower[-1] if lp_lower else None)
            lp_upper.append(lp_upper[-1] if lp_upper else None)
            lp_width_label.append(lp_width_label[-1] if lp_width_label else "Cash")
        else:
            lp_lower.append(None)
            lp_upper.append(None)
            lp_width_label.append("Cash")

trace_df["lp_lower"] = lp_lower
trace_df["lp_upper"] = lp_upper
trace_df["lp_width_label"] = lp_width_label

# ── Color map for widths ──
WIDTH_COLORS = {
    "W4": "#e74c3c",   # red
    "W6": "#f39c12",   # orange
    "W10": "#2ecc71",  # green
    "W20": "#3498db",  # blue
    "Cash": "#bdc3c7", # gray
}

# ── Plot ──
fig = plt.figure(figsize=(16, 10))
gs = fig.add_gridspec(2, 1, height_ratios=[1.3, 1], hspace=0.08,
                       left=0.08, right=0.96, top=0.94, bottom=0.08)
ax1 = fig.add_subplot(gs[0])
ax2 = fig.add_subplot(gs[1], sharex=ax1)

ts = trace_df["timestamp"].values
prices = trace_df["price"].values

# Panel 1: Price + LP width bands
ax1.plot(ts, prices, color="black", linewidth=1.2, label="ETH Price", zorder=5)

# Draw LP range bands as shaded regions, colored by width
prev_label = None
band_start = 0
for i in range(len(trace_df)):
    label = trace_df["lp_width_label"].iloc[i]
    # Draw band when label changes or at end
    if label != prev_label or i == len(trace_df) - 1:
        if prev_label is not None and prev_label != "Cash" and band_start < i:
            end_i = i if label != prev_label else i + 1
            band_ts = ts[band_start:end_i]
            band_lo = trace_df["lp_lower"].iloc[band_start:end_i].values.astype(float)
            band_hi = trace_df["lp_upper"].iloc[band_start:end_i].values.astype(float)
            color = WIDTH_COLORS.get(prev_label, "#bdc3c7")
            ax1.fill_between(band_ts, band_lo, band_hi, alpha=0.25, color=color, zorder=2)
            ax1.plot(band_ts, band_lo, color=color, linewidth=0.5, alpha=0.6, zorder=3)
            ax1.plot(band_ts, band_hi, color=color, linewidth=0.5, alpha=0.6, zorder=3)
        band_start = i
    prev_label = label

# Handle last band
if prev_label is not None and prev_label != "Cash":
    band_ts = ts[band_start:]
    band_lo = trace_df["lp_lower"].iloc[band_start:].values.astype(float)
    band_hi = trace_df["lp_upper"].iloc[band_start:].values.astype(float)
    color = WIDTH_COLORS.get(prev_label, "#bdc3c7")
    ax1.fill_between(band_ts, band_lo, band_hi, alpha=0.25, color=color, zorder=2)
    ax1.plot(band_ts, band_lo, color=color, linewidth=0.5, alpha=0.6, zorder=3)
    ax1.plot(band_ts, band_hi, color=color, linewidth=0.5, alpha=0.6, zorder=3)

# Legend
used_widths = sorted(set(trace_df["lp_width_label"]) - {"Cash"}, key=lambda x: int(x[1:]))
legend_patches = [Patch(facecolor=WIDTH_COLORS[w], alpha=0.4, label=w) for w in used_widths]
legend_patches.append(Patch(facecolor=WIDTH_COLORS["Cash"], alpha=0.4, label="Cash"))
ax1.legend(handles=legend_patches, loc="upper left", fontsize=9)
ax1.set_ylabel("ETH Price (USD)", fontsize=11)
ax1.set_title("Fold 3 Test Period: Price + LP Width Ranges", fontsize=13, fontweight="bold")
ax1.grid(True, alpha=0.3)

# Panel 2: Portfolio value
ax2.plot(ts, trace_df["portfolio_value"].values, color="#2c3e50", linewidth=1.5)
ax2.axhline(y=1000, color="gray", linestyle="--", linewidth=0.8, alpha=0.6, label="Initial $1,000")
ax2.fill_between(ts, 1000, trace_df["portfolio_value"].values,
                  where=trace_df["portfolio_value"].values >= 1000,
                  alpha=0.15, color="green")
ax2.fill_between(ts, 1000, trace_df["portfolio_value"].values,
                  where=trace_df["portfolio_value"].values < 1000,
                  alpha=0.15, color="red")
final_pv = trace_df["portfolio_value"].iloc[-1]
ax2.annotate(f"${final_pv:,.0f} (+${final_pv - 1000:,.0f})",
             xy=(ts[-1], final_pv), fontsize=11, fontweight="bold",
             xytext=(-80, 15), textcoords="offset points",
             arrowprops=dict(arrowstyle="->", color="black"))
ax2.set_ylabel("Portfolio Value (USD)", fontsize=11)
ax2.set_title("Portfolio Value", fontsize=13, fontweight="bold")
ax2.legend(loc="upper left", fontsize=9)
ax2.grid(True, alpha=0.3)

ax2.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
ax2.xaxis.set_major_locator(mdates.WeekdayLocator(interval=1))
plt.xticks(rotation=30, ha="right")

plt.setp(ax1.get_xticklabels(), visible=False)
save_path = os.path.join(SCRIPT_DIR, "fold3_test_viz.png")
plt.savefig(save_path, dpi=150, bbox_inches="tight")
print(f"\nSaved: {save_path}")
plt.close()
