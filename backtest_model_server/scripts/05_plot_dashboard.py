"""
Phase 6 — Generate 4-panel dashboard visualisations.

Reads results/ output and writes to plots/:
  plots/serving_health.png       latency, error rate, data staleness
  plots/decision_analysis.png    action distribution, hold streaks
  plots/portfolio_performance.png equity curve, drawdown, position timeline
  plots/market_context.png       OHLCV candles, volatility, LP range bands

Usage (from backtest_model_server/):
    python scripts/05_plot_dashboard.py
    python scripts/05_plot_dashboard.py --config config/backtest_config.yaml
    python scripts/05_plot_dashboard.py --show   # open popup windows
"""

import sys
import json
import math
import logging
import argparse
from pathlib import Path

import yaml
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")   # non-interactive backend; overridden below if --show
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.dates as mdates
from matplotlib.ticker import FuncFormatter

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
BASE_DIR   = SCRIPT_DIR.parent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


def load_config(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# Plot helpers
# ---------------------------------------------------------------------------

USD_FMT  = FuncFormatter(lambda x, _: f"${x:,.0f}")
PCT_FMT  = FuncFormatter(lambda x, _: f"{x:.1f}%")
MS_FMT   = FuncFormatter(lambda x, _: f"{x:.0f}ms")


def _save(fig, path: Path, show: bool):
    fig.tight_layout()
    fig.savefig(path, dpi=150, bbox_inches="tight")
    log.info("Saved %s", path)
    if show:
        plt.show()
    plt.close(fig)


# ---------------------------------------------------------------------------
# Panel 1 — Serving health
# ---------------------------------------------------------------------------

def plot_serving_health(log_df: pd.DataFrame, out_path: Path, show: bool):
    fig, axes = plt.subplots(2, 2, figsize=(14, 8))
    fig.suptitle("Serving Health", fontsize=14, fontweight="bold")

    ts = pd.to_datetime(log_df["timestamp"], errors="coerce")

    # 1a — Latency distribution
    ax = axes[0, 0]
    ok_latency = log_df.loc[log_df["status_code"] == 200, "latency_ms"].dropna()
    if not ok_latency.empty:
        ax.hist(ok_latency, bins=40, color="#4C72B0", edgecolor="white", linewidth=0.5)
        for pct, color in [(50, "orange"), (95, "red"), (99, "darkred")]:
            val = np.percentile(ok_latency, pct)
            ax.axvline(val, color=color, linestyle="--", linewidth=1.2,
                       label=f"p{pct}: {val:.0f}ms")
    ax.set_title("Latency Distribution (200 OK)")
    ax.set_xlabel("Latency (ms)")
    ax.set_ylabel("Count")
    ax.legend(fontsize=8)
    ax.xaxis.set_major_formatter(MS_FMT)

    # 1b — Latency over time
    ax = axes[0, 1]
    ok_mask = log_df["status_code"] == 200
    ax.plot(ts[ok_mask], log_df.loc[ok_mask, "latency_ms"], color="#4C72B0", linewidth=0.6, alpha=0.8)
    # Rolling p95
    if ok_mask.sum() > 10:
        rolling_p95 = (
            pd.Series(log_df.loc[ok_mask, "latency_ms"].values)
            .rolling(24, min_periods=1)
            .quantile(0.95)
        )
        ax.plot(ts[ok_mask].values, rolling_p95.values, color="red", linewidth=1.2,
                linestyle="--", label="rolling p95 (24h)")
    ax.set_title("Latency Over Time")
    ax.set_xlabel("")
    ax.set_ylabel("Latency (ms)")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))
    ax.yaxis.set_major_formatter(MS_FMT)
    ax.legend(fontsize=8)

    # 1c — Error rate by status code
    ax = axes[1, 0]
    status_counts = log_df["status_code"].value_counts().sort_index()
    colors = {200: "#55A868", 401: "#DD8452", 404: "#C44E52", 422: "#DA8BC3",
              503: "#8172B2", None: "#937860"}
    bar_colors = [colors.get(s, "#8C8C8C") for s in status_counts.index]
    bars = ax.bar([str(s) for s in status_counts.index], status_counts.values, color=bar_colors)
    for bar, count in zip(bars, status_counts.values):
        pct = count / len(log_df) * 100
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.3,
                f"{pct:.1f}%", ha="center", va="bottom", fontsize=8)
    ax.set_title("Response Status Codes")
    ax.set_xlabel("HTTP Status")
    ax.set_ylabel("Count")

    # 1d — Data staleness over time
    ax = axes[1, 1]
    if "data_age_seconds" in log_df.columns:
        age = pd.to_numeric(log_df["data_age_seconds"], errors="coerce")
        ax.plot(ts, age, color="#C44E52", linewidth=0.7, alpha=0.8, label="data_age_seconds")
        ax.axhline(300, color="orange", linestyle="--", linewidth=1.2, label="5 min threshold")
        ax.set_ylabel("Age (seconds)")
    ax.set_title("Data Staleness")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))
    ax.legend(fontsize=8)

    _save(fig, out_path, show)


# ---------------------------------------------------------------------------
# Panel 2 — Decision analysis
# ---------------------------------------------------------------------------

def plot_decision_analysis(trace_df: pd.DataFrame, out_path: Path, show: bool):
    fig, axes = plt.subplots(1, 3, figsize=(16, 5))
    fig.suptitle("Decision Analysis", fontsize=14, fontweight="bold")

    ts = pd.to_datetime(trace_df["timestamp"], errors="coerce")

    # 2a — Stacked action distribution over time (daily bins)
    ax = axes[0]
    daily = trace_df.copy()
    daily["action_label"] = daily["action_label"].fillna("HOLD")
    daily["date"] = pd.to_datetime(daily["timestamp"]).dt.date
    action_daily = daily.groupby(["date", "action_label"]).size().unstack(fill_value=0)
    ACTION_COLORS = {
        "HOLD": "#8C8C8C",
        "WIDTH-4": "#C44E52",
        "WIDTH-6": "#DD8452",
        "WIDTH-10": "#55A868",
        "WIDTH-20": "#4C72B0",
    }
    action_daily.plot(
        kind="bar", stacked=True, ax=ax, width=0.85,
        color=[ACTION_COLORS.get(c, "#BBBBBB") for c in action_daily.columns],
    )
    ax.set_title("Daily Action Distribution")
    ax.set_xlabel("")
    ax.set_ylabel("Hours")
    ax.tick_params(axis="x", rotation=45, labelsize=6)
    ax.legend(fontsize=8, loc="upper right")

    # 2b — Cumulative action counts
    ax = axes[1]
    cumulative = daily.groupby("date")["action_label"].value_counts().unstack(fill_value=0).cumsum()
    for col in cumulative.columns:
        ax.plot(cumulative.index, cumulative[col],
                label=col, color=ACTION_COLORS.get(col, "#BBBBBB"), linewidth=1.5)
    ax.set_title("Cumulative Action Counts")
    ax.set_xlabel("")
    ax.set_ylabel("Cumulative Count")
    ax.legend(fontsize=8)
    ax.tick_params(axis="x", rotation=30, labelsize=7)

    # 2c — Hold streak distribution
    ax = axes[2]
    streaks = []
    current_streak = 0
    for action in trace_df["action_label"].fillna("HOLD"):
        if action == "HOLD":
            current_streak += 1
        else:
            if current_streak > 0:
                streaks.append(current_streak)
            current_streak = 0
    if current_streak > 0:
        streaks.append(current_streak)

    if streaks:
        ax.hist(streaks, bins=min(40, max(streaks)), color="#4C72B0", edgecolor="white")
        ax.axvline(np.median(streaks), color="orange", linestyle="--",
                   label=f"Median: {np.median(streaks):.0f}h")
        ax.set_title("Hold Streak Distribution")
        ax.set_xlabel("Consecutive HOLD hours")
        ax.set_ylabel("Count")
        ax.legend(fontsize=8)
    else:
        ax.text(0.5, 0.5, "No hold streaks", ha="center", va="center", transform=ax.transAxes)
        ax.set_title("Hold Streak Distribution")

    _save(fig, out_path, show)


# ---------------------------------------------------------------------------
# Panel 3 — Portfolio performance
# ---------------------------------------------------------------------------

def plot_portfolio_performance(
    trace_df: pd.DataFrame,
    metrics: dict,
    initial_cap: float,
    out_path: Path,
    show: bool,
):
    fig, axes = plt.subplots(3, 1, figsize=(14, 12), sharex=True)
    fig.suptitle("Portfolio Performance", fontsize=14, fontweight="bold")

    ts = pd.to_datetime(trace_df["timestamp"], errors="coerce")
    pv = trace_df["portfolio_value"]

    # 3a — Equity curves
    ax = axes[0]
    ax.plot(ts, pv, color="#4C72B0", linewidth=1.5, label="Model Server", zorder=3)
    ax.axhline(initial_cap, color="#8C8C8C", linestyle="--", linewidth=1, label=f"Initial ${initial_cap:,.0f}")

    # HODL line (from metrics or approximate)
    hodl_m = metrics.get("hodl", {})
    if hodl_m.get("final_pv"):
        # Linear approximation if we don't have the trace
        hodl_vals = np.linspace(initial_cap, hodl_m["final_pv"], len(ts))
        ax.plot(ts, hodl_vals, color="#C44E52", linewidth=1.2, linestyle="--",
                label=f"HODL ${hodl_m['final_pv']:,.1f}", alpha=0.7)

    ax.fill_between(ts, pv, initial_cap,
                    where=(pv >= initial_cap), alpha=0.15, color="green", label="Profit")
    ax.fill_between(ts, pv, initial_cap,
                    where=(pv < initial_cap), alpha=0.15, color="red", label="Loss")
    ax.set_ylabel("Portfolio Value (USD)")
    ax.yaxis.set_major_formatter(USD_FMT)
    ax.legend(fontsize=9, loc="upper left")

    model_m = metrics.get("model_server", {})
    pnl = model_m.get("pnl", 0.0) or 0.0
    sharpe = model_m.get("sharpe_ratio", 0.0) or 0.0
    mdd = model_m.get("max_drawdown_pct", 0.0) or 0.0
    ax.annotate(
        f"PnL: ${pnl:+.2f}  Sharpe: {sharpe:.3f}  MaxDD: {mdd:.1f}%",
        xy=(0.01, 0.02), xycoords="axes fraction",
        fontsize=9, color="#333333",
        bbox=dict(boxstyle="round,pad=0.3", facecolor="lightyellow", edgecolor="#AAAAAA"),
    )

    # 3b — Drawdown
    ax = axes[1]
    roll_max = pv.cummax()
    drawdown = (pv - roll_max) / roll_max * 100.0
    ax.fill_between(ts, drawdown, 0, color="#C44E52", alpha=0.6)
    ax.plot(ts, drawdown, color="#C44E52", linewidth=0.8)
    ax.set_ylabel("Drawdown (%)")
    ax.yaxis.set_major_formatter(PCT_FMT)

    # 3c — Position state timeline
    ax = axes[2]
    STATE_COLORS = {"cash": "#AAAAAA", "lp_in_range": "#55A868", "lp_oor": "#C44E52"}
    for state, color in STATE_COLORS.items():
        mask = trace_df["position_state"] == state
        if mask.any():
            ax.bar(
                ts[mask].values, np.ones(mask.sum()),
                width=pd.Timedelta(hours=1), color=color, label=state.replace("_", " "), alpha=0.85,
            )
    ax.set_ylabel("Position State")
    ax.set_yticks([])
    ax.legend(fontsize=8, loc="upper right")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))

    _save(fig, out_path, show)


# ---------------------------------------------------------------------------
# Panel 4 — Market context
# ---------------------------------------------------------------------------

def plot_market_context(trace_df: pd.DataFrame, out_path: Path, show: bool):
    fig, axes = plt.subplots(2, 1, figsize=(14, 9), sharex=True)
    fig.suptitle("Market Context", fontsize=14, fontweight="bold")

    ts = pd.to_datetime(trace_df["timestamp"], errors="coerce")
    price = trace_df["current_price"]

    # 4a — Price with LP range bands
    ax = axes[0]

    # Shade LP range bands — merge contiguous position blocks into single rectangles
    WIDTH_COLORS = {
        "enter_w4":   "#C44E52", "recenter_w4":   "#C44E52",
        "enter_w6":   "#DD8452", "recenter_w6":   "#DD8452",
        "enter_w10":  "#55A868", "recenter_w10":  "#55A868",
        "enter_w20":  "#4C72B0", "recenter_w20":  "#4C72B0",
    }
    ts_arr = ts.reset_index(drop=True)
    tdf = trace_df.reset_index(drop=True)
    has_pos = tdf.get("has_position", pd.Series(False, index=tdf.index)).astype(bool)

    # Build contiguous position blocks — carry the width color through HOLDs
    blocks = []  # list of (t_start, t_end, color, price_lower, price_upper)
    i = 0
    active_color = None  # track last enter/recenter color
    while i < len(tdf):
        if has_pos.iloc[i]:
            ea = tdf.iloc[i].get("effective_action", "hold")
            # Only update color when we see an actual enter/recenter action
            if ea in WIDTH_COLORS:
                active_color = WIDTH_COLORS[ea]
            color = active_color or "#AAAAAA"
            pl = tdf.iloc[i].get("price_lower")
            pu = tdf.iloc[i].get("price_upper")
            start_i = i
            # Extend block while position continues with same bounds
            while i < len(tdf) and has_pos.iloc[i]:
                row = tdf.iloc[i]
                row_ea = row.get("effective_action", "hold")
                # Update active color on new enter/recenter
                if row_ea in WIDTH_COLORS:
                    new_color = WIDTH_COLORS[row_ea]
                    if new_color != color:
                        break  # new width action → start a new block
                row_pl = row.get("price_lower")
                row_pu = row.get("price_upper")
                if row_pl != pl or row_pu != pu:
                    break  # bounds changed → start a new block
                i += 1
            end_i = i - 1
            if pd.notna(pl) and pd.notna(pu):
                t_start = ts_arr.iloc[start_i]
                t_end = ts_arr.iloc[end_i] + pd.Timedelta(hours=1) if end_i + 1 >= len(tdf) else ts_arr.iloc[end_i + 1]
                blocks.append((t_start, t_end, color, float(pl), float(pu)))
        else:
            active_color = None  # reset when out of position
            i += 1

    for t_start, t_end, color, pl, pu in blocks:
        ax.fill_between([t_start, t_end], [pl, pl], [pu, pu],
                        color=color, alpha=0.2, linewidth=0)

    # Price line — 3 colors by position state
    #   lp_in_range → green (thin)
    #   cash        → yellow (bold)
    #   lp_oor      → red (bolder)
    pos_state = tdf.get("position_state", pd.Series("cash", index=tdf.index)).fillna("cash")
    LINE_STYLE = {
        "lp_in_range": {"color": "#2CA02C", "linewidth": 1.0, "zorder": 5},
        "cash":        {"color": "#DAA520", "linewidth": 2.0, "zorder": 6},
        "lp_oor":      {"color": "#C44E52", "linewidth": 2.8, "zorder": 7},
    }
    for j in range(len(ts_arr) - 1):
        style = LINE_STYLE.get(pos_state.iloc[j], LINE_STYLE["cash"])
        ax.plot(
            [ts_arr.iloc[j], ts_arr.iloc[j + 1]],
            [price.iloc[j], price.iloc[j + 1]],
            **style,
        )
    # Dummy entries for legend
    ax.plot([], [], color="#2CA02C", linewidth=1.0, label="In Range")
    ax.plot([], [], color="#DAA520", linewidth=2.0, label="No Position")
    ax.plot([], [], color="#C44E52", linewidth=2.8, label="Out of Range")

    # Entry markers
    enter_mask = trace_df["effective_action"].fillna("hold").str.startswith("enter_w")
    if enter_mask.any():
        ax.scatter(ts[enter_mask].values, price[enter_mask].values,
                   marker="^", color="green", s=40, zorder=6, label="Enter", alpha=0.8)

    recenter_mask = trace_df["effective_action"].fillna("hold").str.startswith("recenter_w")
    if recenter_mask.any():
        ax.scatter(ts[recenter_mask].values, price[recenter_mask].values,
                   marker="o", color="orange", s=25, zorder=6, label="Recenter", alpha=0.8)

    ax.set_ylabel("Price (USD)")
    ax.yaxis.set_major_formatter(USD_FMT)
    ax.legend(fontsize=8, loc="upper left")

    # Legend patches for range width colors
    patches = [
        mpatches.Patch(color="#C44E52", alpha=0.3, label="W4"),
        mpatches.Patch(color="#DD8452", alpha=0.3, label="W6"),
        mpatches.Patch(color="#55A868", alpha=0.3, label="W10"),
        mpatches.Patch(color="#4C72B0", alpha=0.3, label="W20"),
    ]
    handles, labels = ax.get_legend_handles_labels()
    ax.legend(handles=handles + patches,
              labels=labels + ["W4", "W6", "W10", "W20"],
              fontsize=7, loc="upper left", ncol=2)

    # 4b — Rolling realised volatility (hourly returns, 24h window)
    ax = axes[1]
    returns = price.pct_change()
    vol = returns.rolling(24, min_periods=4).std() * math.sqrt(8760) * 100.0  # annualised %
    ax.fill_between(ts, vol, 0, color="#8172B2", alpha=0.5, label="Vol (24h, ann.%)")
    ax.plot(ts, vol, color="#8172B2", linewidth=0.8)
    ax.set_ylabel("Realised Volatility (ann. %)")
    ax.yaxis.set_major_formatter(PCT_FMT)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))
    ax.legend(fontsize=8)

    _save(fig, out_path, show)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Plot backtest dashboard")
    parser.add_argument("--config", default=str(BASE_DIR / "config" / "backtest_config.yaml"))
    parser.add_argument("--show", action="store_true", help="Show matplotlib popup windows")
    args = parser.parse_args()

    if args.show:
        try:
            plt.switch_backend("TkAgg")
        except Exception as e:
            log.warning("Could not switch to TkAgg backend; continuing headless: %s", e)

    cfg         = load_config(Path(args.config))
    initial_cap = cfg.get("initial_capital_usd", 1000.0)
    results_dir = BASE_DIR / cfg.get("output_dir", "results")
    plots_dir   = BASE_DIR / cfg.get("plots_dir", "plots")
    plots_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Load data
    # ------------------------------------------------------------------
    trace_path = results_dir / "trace_df.parquet"
    log_path   = results_dir / "inference_log.csv"
    metrics_path = results_dir / "metrics.json"

    if not trace_path.exists():
        log.error("trace_df.parquet not found — run 03_run_infer_backtest.py first")
        sys.exit(1)

    trace_df = pd.read_parquet(trace_path)
    log.info("Loaded trace_df: %d rows", len(trace_df))

    log_df = pd.read_csv(log_path) if log_path.exists() else pd.DataFrame()
    log.info("Loaded inference_log: %d rows", len(log_df))

    metrics = {}
    if metrics_path.exists():
        with open(metrics_path) as f:
            metrics = json.load(f)

    # ------------------------------------------------------------------
    # Generate panels
    # ------------------------------------------------------------------
    if not log_df.empty:
        plot_serving_health(log_df, plots_dir / "serving_health.png", args.show)
    else:
        log.warning("No inference_log data — skipping serving_health.png")

    plot_decision_analysis(trace_df, plots_dir / "decision_analysis.png", args.show)
    plot_portfolio_performance(trace_df, metrics, initial_cap,
                               plots_dir / "portfolio_performance.png", args.show)
    plot_market_context(trace_df, plots_dir / "market_context.png", args.show)

    log.info("All plots saved to %s", plots_dir)


if __name__ == "__main__":
    main()
