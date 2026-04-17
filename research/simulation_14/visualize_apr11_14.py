"""
Run the shipped kongtrae v3_1h DQN model on 2026-04-11 00:00 → 2026-04-14 23:00 UTC.
Prints metrics (PnL, HODL, decision histogram, state occupancy) and saves a 2-panel PNG
(price + LP width bands; portfolio value vs HODL).
"""
import os
import sys
import glob
import math
import pickle
from collections import Counter
from dataclasses import dataclass

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

from kongtrae.training.uniswap_v3_ppo_paper import prepare_hourly_data, FEATURE_COLS  # noqa: F401
from kongtrae.training.uniswap_v3_hedged_fee_env import HEDGE_ACCOUNTING_CONTINUOUS
from kongtrae.training.hedged_hierarchical_policy import (
    run_three_head_policy_episode,
    trace_metrics,
)
from kongtrae.training.train_hedged_three_head_v2_dqn import _v2_env_kwargs
from kongtrae.training.three_head_dueling_dqn import ThreeHeadDoubleDuelingDQN

# ── Verify which swap CSV the loader will pick ──
DATA_DIR = os.path.join(PACKAGE_PARENT, "training_data")
swap_files = glob.glob(os.path.join(DATA_DIR, "swaps_*_eth_usdt_0p3.csv"))
print("Swap CSVs found (loader uses [0]):")
for sf in swap_files:
    print(f"  {sf}")
print()

data = prepare_hourly_data(DATA_DIR)
timestamps = data.timestamps
print(f"Data range: {timestamps[0]} → {timestamps[-1]}  ({len(timestamps)} bars)")

# ── Window: 2026-04-11 00:00 UTC → 2026-04-14 23:00 UTC (inclusive, 96 hours) ──
win_start = "2026-04-11 00:00"
win_end_inclusive = "2026-04-14 23:00"

test_start_idx = next(i for i, t in enumerate(timestamps) if str(t)[:16] >= win_start)
# end_idx is exclusive in run_three_head_policy_episode, so advance past the last inclusive hour.
test_end_idx = next(i for i, t in enumerate(timestamps) if str(t)[:16] > win_end_inclusive)

print(f"Window ask: {win_start} → {win_end_inclusive} UTC")
print(f"Actual:     {timestamps[test_start_idx]} → {timestamps[test_end_idx - 1]}")
print(f"Hours: {test_end_idx - test_start_idx}")

# ── Load v3_1h model ──
model_path = os.path.join(SCRIPT_DIR, "models", "dqn_three_head_v3_1h.zip")
vec_path = os.path.join(SCRIPT_DIR, "models", "dqn_three_head_v3_1h_vecnormalize.pkl")
model = ThreeHeadDoubleDuelingDQN.load(model_path, device="cpu")
with open(vec_path, "rb") as f:
    vec_normalize = pickle.load(f)

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
        action_int = int(action[0]) if hasattr(action, "__len__") else int(action)
        return Prediction(value=action_int, q_gap=0.0)

policy = DQNPolicyWrapper(model, vec_normalize)
action_widths = (4, 6, 10, 20)
CAPITAL = 1000.0

# ── Run episode ──
trace_df = run_three_head_policy_episode(
    data=data,
    three_head_policy=policy,
    capital=CAPITAL,
    mode="all",
    seed=42,
    hedge_accounting_mode=HEDGE_ACCOUNTING_CONTINUOUS,
    action_widths=action_widths,
    start_idx=test_start_idx,
    end_idx=test_end_idx,
    env_kwargs=_v2_env_kwargs(action_widths),
)

metrics = trace_metrics(trace_df)

# ── HODL benchmark: buy ETH at hour 0, hold ──
p0 = float(data.prices[pd.Timestamp(timestamps[test_start_idx])])
eth_held = CAPITAL / p0
hodl_series = []
for ts in trace_df["timestamp"].values:
    px = float(data.prices[pd.Timestamp(ts)])
    hodl_series.append(eth_held * px)
trace_df["hodl_value"] = hodl_series
hodl_final = hodl_series[-1]

# ── Decision histogram (effective_action) ──
action_counts = Counter(trace_df["effective_action"].tolist())
print()
print("=" * 60)
print(f"  v3_1h DQN on {win_start} → {win_end_inclusive} UTC ($1K)")
print("=" * 60)
print(f"  Final PV:    ${metrics['final_pv']:,.2f}  (PnL {metrics['pnl']:+.2f})")
print(f"  HODL PV:     ${hodl_final:,.2f}  (PnL {hodl_final - CAPITAL:+.2f})")
print(f"  Alpha:       {metrics['final_pv'] - hodl_final:+.2f}")
print(f"  Cash %:      {metrics['cash_pct']:.0f}%")
print(f"  OOR %:       {metrics['oor_pct']:.0f}%")
print(f"  Trades:      {metrics['trade_count']}")
print(f"  Gross carry: ${metrics['gross_fee_carry_usd']:+.2f}")
print(f"  Raw swing:   ${metrics['raw_swing_pnl_usd']:+.2f}")
print()
print("  Effective-action histogram:")
for action, count in sorted(action_counts.items(), key=lambda x: -x[1]):
    print(f"    {action:<22} {count:>3}  ({100*count/len(trace_df):.0f}%)")
print("=" * 60)

# ── Prepare plot data ──
trace_df["timestamp"] = pd.to_datetime(trace_df["timestamp"])
trace_df["price"] = [float(data.prices[pd.Timestamp(ts)]) for ts in trace_df["timestamp"]]

TICK_SPACING = 10
lp_lower, lp_upper, lp_width_label = [], [], []
current_width = None

for _, row in trace_df.iterrows():
    ea = row["effective_action"]
    state_after = row["next_position_state"]
    price = row["price"]

    if ea.startswith("enter_w") or ea.startswith("recenter_w"):
        w = int(row["selected_width"])
        current_width = w
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
        if current_width is not None and lp_lower:
            lp_lower.append(lp_lower[-1])
            lp_upper.append(lp_upper[-1])
            lp_width_label.append(lp_width_label[-1])
        else:
            lp_lower.append(None)
            lp_upper.append(None)
            lp_width_label.append("Cash")

trace_df["lp_lower"] = lp_lower
trace_df["lp_upper"] = lp_upper
trace_df["lp_width_label"] = lp_width_label

WIDTH_COLORS = {
    "W4":  "#e74c3c",
    "W6":  "#f39c12",
    "W10": "#2ecc71",
    "W20": "#3498db",
    "Cash":"#bdc3c7",
}

# ── Plot ──
fig = plt.figure(figsize=(15, 9))
gs = fig.add_gridspec(2, 1, height_ratios=[1.3, 1], hspace=0.1,
                     left=0.08, right=0.96, top=0.94, bottom=0.08)
ax1 = fig.add_subplot(gs[0])
ax2 = fig.add_subplot(gs[1], sharex=ax1)

ts = trace_df["timestamp"].values
prices = trace_df["price"].values

ax1.plot(ts, prices, color="black", linewidth=1.3, label="ETH Price", zorder=5)

prev_label = None
band_start = 0
for i in range(len(trace_df)):
    label = trace_df["lp_width_label"].iloc[i]
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

if prev_label is not None and prev_label != "Cash":
    band_ts = ts[band_start:]
    band_lo = trace_df["lp_lower"].iloc[band_start:].values.astype(float)
    band_hi = trace_df["lp_upper"].iloc[band_start:].values.astype(float)
    color = WIDTH_COLORS.get(prev_label, "#bdc3c7")
    ax1.fill_between(band_ts, band_lo, band_hi, alpha=0.25, color=color, zorder=2)
    ax1.plot(band_ts, band_lo, color=color, linewidth=0.5, alpha=0.6, zorder=3)
    ax1.plot(band_ts, band_hi, color=color, linewidth=0.5, alpha=0.6, zorder=3)

used_widths = sorted(set(trace_df["lp_width_label"]) - {"Cash"}, key=lambda x: int(x[1:]))
legend_patches = [Patch(facecolor=WIDTH_COLORS[w], alpha=0.4, label=w) for w in used_widths]
legend_patches.append(Patch(facecolor=WIDTH_COLORS["Cash"], alpha=0.4, label="Cash"))
legend_patches.insert(0, plt.Line2D([0], [0], color="black", lw=1.3, label="ETH Price"))
ax1.legend(handles=legend_patches, loc="upper left", fontsize=9)
ax1.set_ylabel("ETH Price (USD)", fontsize=11)
ax1.set_title(f"v3_1h DQN: {win_start} → {win_end_inclusive} UTC  (price + LP width)",
              fontsize=13, fontweight="bold")
ax1.grid(True, alpha=0.3)

# Panel 2: PV vs HODL
pv_series = trace_df["portfolio_value"].values
ax2.plot(ts, pv_series, color="#2c3e50", linewidth=1.8, label="DQN Portfolio")
ax2.plot(ts, trace_df["hodl_value"].values, color="#d35400", linewidth=1.5,
         linestyle="--", label="HODL ETH")
ax2.axhline(y=CAPITAL, color="gray", linestyle=":", linewidth=0.8, alpha=0.6,
            label=f"Initial ${CAPITAL:,.0f}")
ax2.fill_between(ts, CAPITAL, pv_series,
                 where=pv_series >= CAPITAL, alpha=0.15, color="green")
ax2.fill_between(ts, CAPITAL, pv_series,
                 where=pv_series < CAPITAL, alpha=0.15, color="red")

final_pv = pv_series[-1]
ax2.annotate(f"DQN ${final_pv:,.2f}  ({final_pv - CAPITAL:+.2f})",
             xy=(ts[-1], final_pv), fontsize=10, fontweight="bold",
             xytext=(-160, 12), textcoords="offset points",
             arrowprops=dict(arrowstyle="->", color="#2c3e50"))
ax2.annotate(f"HODL ${hodl_final:,.2f}  ({hodl_final - CAPITAL:+.2f})",
             xy=(ts[-1], hodl_final), fontsize=10, fontweight="bold",
             xytext=(-160, -28), textcoords="offset points",
             arrowprops=dict(arrowstyle="->", color="#d35400"))
ax2.set_ylabel("Portfolio Value (USD)", fontsize=11)
ax2.set_title("Portfolio: DQN vs HODL", fontsize=13, fontweight="bold")
ax2.legend(loc="upper left", fontsize=9)
ax2.grid(True, alpha=0.3)

ax2.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d %Hh"))
ax2.xaxis.set_major_locator(mdates.HourLocator(interval=12))
plt.xticks(rotation=30, ha="right")
plt.setp(ax1.get_xticklabels(), visible=False)

save_path = os.path.join(SCRIPT_DIR, "v3_1h_apr11_14_viz.png")
plt.savefig(save_path, dpi=150, bbox_inches="tight")
print(f"\nSaved: {save_path}")
plt.close()

trace_path = os.path.join(SCRIPT_DIR, "v3_1h_apr11_14_trace.csv")
trace_df.to_csv(trace_path, index=False)
print(f"Saved: {trace_path}")
