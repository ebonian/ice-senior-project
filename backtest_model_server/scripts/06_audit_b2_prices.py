"""
Audit B2 price data quality over a date range.

Downloads the latest rolling price snapshot for each day from B2,
compares it against the on-chain swap-derived OHLCV, and visualises
where stale/flat-price gaps occur.

Usage (from backtest_model_server/):
    python scripts/06_audit_b2_prices.py
    python scripts/06_audit_b2_prices.py --months 3
    python scripts/06_audit_b2_prices.py --start 2026-02-01 --end 2026-04-17

Requires: B2_ACCOUNT_ID, B2_ACCOUNT_KEY, B2_BUCKET_NAME env vars.
Output:   plots/b2_price_audit.png
          results/b2_price_audit.csv
"""

import sys
import os
import argparse
import logging
import math
import io
from pathlib import Path
from datetime import datetime, timedelta, date
from collections import defaultdict

import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.colors import LinearSegmentedColormap

# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
BASE_DIR = SCRIPT_DIR.parent
LLAMINET = BASE_DIR.parent.parent
PIPELINE = LLAMINET / "pipeline" / "scripts"
sys.path.insert(0, str(PIPELINE))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

POOL_PREFIX = "eth_usdc_0p05"


# ---------------------------------------------------------------------------
# B2 helpers
# ---------------------------------------------------------------------------

def connect_b2():
    from fetch_b2_data import load_b2_credentials, create_b2_client
    account_id, account_key, bucket_name = load_b2_credentials()
    b2 = create_b2_client(account_id, account_key)
    bucket = b2.get_bucket_by_name(bucket_name)
    log.info("Connected to B2 bucket: %s", bucket_name)
    return bucket


def list_price_files(bucket, start: date, end: date) -> dict[date, list[str]]:
    """List all raw price files grouped by date, filtered to [start, end]."""
    prefix = f"{POOL_PREFIX}/raw/prices/"
    files_by_date: dict[date, list[str]] = defaultdict(list)

    log.info("Listing B2 price files...")
    for file_version, _ in bucket.ls(prefix, recursive=True):
        name = file_version.file_name
        if not name.endswith(".parquet"):
            continue
        parts = name.split("/")
        if len(parts) < 7:
            continue
        try:
            d = date(int(parts[3]), int(parts[4]), int(parts[5]))
        except (ValueError, IndexError):
            continue
        if start <= d <= end:
            files_by_date[d].append(name)

    log.info("Found price files for %d days in [%s, %s]", len(files_by_date), start, end)
    return files_by_date


def download_parquet(bucket, key: str) -> pd.DataFrame:
    """Download a single parquet file from B2 into a DataFrame."""
    dl = bucket.download_file_by_name(key)
    buf = io.BytesIO()
    dl.save(buf)
    buf.seek(0)
    return pd.read_parquet(buf)


def get_best_candles_per_day(
    bucket, files_by_date: dict[date, list[str]]
) -> pd.DataFrame:
    """For each day, reconstruct the best available hourly candles.

    Each B2 file is a rolling 24h snapshot written at a specific time.
    For each hour of a given day, we prefer the *latest written* file
    that contains that hour — giving us the most up-to-date candle.
    """
    all_rows = []
    sorted_dates = sorted(files_by_date.keys())

    for i, d in enumerate(sorted_dates):
        day_files = sorted(files_by_date[d])  # sorted by HH-MM filename

        log.info(
            "[%d/%d] %s -- %d files",
            i + 1, len(sorted_dates), d.isoformat(), len(day_files),
        )

        # Build a dict: hour -> best candle row (later files overwrite earlier)
        best: dict[int, dict] = {}

        for fpath in day_files:
            try:
                df = download_parquet(bucket, fpath)
            except Exception as exc:
                log.warning("  Failed %s: %s", fpath.split("/")[-1], exc)
                continue

            if "open_time" not in df.columns:
                continue

            df["datetime"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
            for col in ("open", "high", "low", "close"):
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors="coerce")

            mask = df["datetime"].dt.date == d
            for _, row in df.loc[mask].iterrows():
                h = row["datetime"].hour
                best[h] = {
                    "datetime": row["datetime"],
                    "open": row["open"],
                    "high": row["high"],
                    "low": row["low"],
                    "close": row["close"],
                    "source_file": fpath.split("/")[-1],
                }

        if best:
            day_df = pd.DataFrame(list(best.values()))
            all_rows.append(day_df)
            n_flat = sum(
                1 for r in best.values()
                if r["open"] == r["close"] == r["high"] == r["low"]
            )
            log.info("  -> %d hours covered, %d flat", len(best), n_flat)

    if not all_rows:
        return pd.DataFrame()

    result = pd.concat(all_rows, ignore_index=True)
    result = result.sort_values("datetime").reset_index(drop=True)
    return result


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

def analyse(df: pd.DataFrame) -> pd.DataFrame:
    """Add staleness / flatness flags to each hourly row."""
    df = df.copy()
    df = df.sort_values("datetime").reset_index(drop=True)

    # Flag: OHLC all equal (flat candle = no real data)
    df["is_flat"] = (
        (df["open"] == df["close"]) &
        (df["high"] == df["close"]) &
        (df["low"] == df["close"])
    )

    # Flag: close unchanged from previous candle
    df["close_unchanged"] = df["close"].diff().abs() < 1e-6
    df.loc[0, "close_unchanged"] = False

    # Streak of unchanged closes
    streak = 0
    streaks = []
    for unchanged in df["close_unchanged"]:
        if unchanged:
            streak += 1
        else:
            streak = 0
        streaks.append(streak)
    df["unchanged_streak"] = streaks

    # Flag stale: flat candle AND close unchanged (pipeline forwarded last price)
    df["is_stale"] = df["is_flat"] & df["close_unchanged"]

    df["date"] = df["datetime"].dt.date
    df["hour"] = df["datetime"].dt.hour

    return df


def summarise_daily(df: pd.DataFrame) -> pd.DataFrame:
    """Per-day summary statistics."""
    grouped = df.groupby("date").agg(
        total_candles=("datetime", "count"),
        flat_candles=("is_flat", "sum"),
        stale_candles=("is_stale", "sum"),
        max_streak=("unchanged_streak", "max"),
        price_min=("close", "min"),
        price_max=("close", "max"),
    ).reset_index()

    grouped["flat_pct"] = (grouped["flat_candles"] / grouped["total_candles"] * 100).round(1)
    grouped["stale_pct"] = (grouped["stale_candles"] / grouped["total_candles"] * 100).round(1)
    grouped["price_range_pct"] = (
        (grouped["price_max"] / grouped["price_min"] - 1) * 100
    ).round(2)

    return grouped


# ---------------------------------------------------------------------------
# Visualisation
# ---------------------------------------------------------------------------

def plot_audit(df: pd.DataFrame, daily: pd.DataFrame, out_path: Path):
    """Create a multi-panel audit dashboard."""
    fig, axes = plt.subplots(4, 1, figsize=(18, 16), height_ratios=[2, 1.2, 1.2, 1.5])
    fig.suptitle("B2 Price Data Quality Audit", fontsize=16, fontweight="bold", y=0.98)

    dates = pd.to_datetime(df["datetime"])

    # --- Panel 1: Price with stale regions highlighted ---
    ax = axes[0]
    ax.plot(dates, df["close"], linewidth=0.7, color="#2196F3", label="B2 close price", zorder=2)

    # Highlight stale regions
    stale_mask = df["is_stale"].values
    if stale_mask.any():
        stale_starts = []
        stale_ends = []
        in_stale = False
        for i, s in enumerate(stale_mask):
            if s and not in_stale:
                stale_starts.append(dates.iloc[i])
                in_stale = True
            elif not s and in_stale:
                stale_ends.append(dates.iloc[i])
                in_stale = False
        if in_stale:
            stale_ends.append(dates.iloc[-1])

        for s, e in zip(stale_starts, stale_ends):
            ax.axvspan(s, e, alpha=0.25, color="#F44336", zorder=1)

        # Dummy for legend
        ax.axvspan(dates.iloc[0], dates.iloc[0], alpha=0.25, color="#F44336", label="Stale data")

    ax.set_ylabel("ETH/USDC Price ($)")
    ax.legend(loc="upper left", fontsize=9)
    ax.set_title("Price Timeline with Stale Regions", fontsize=12)
    ax.grid(True, alpha=0.3)

    # --- Panel 2: Daily stale % bar chart ---
    ax = axes[1]
    daily_dates = pd.to_datetime(daily["date"])
    colors = ["#F44336" if s > 50 else "#FF9800" if s > 20 else "#4CAF50" for s in daily["stale_pct"]]
    ax.bar(daily_dates, daily["stale_pct"], color=colors, width=0.8, edgecolor="none")
    ax.set_ylabel("Stale Candles (%)")
    ax.set_title("Daily Stale Candle Percentage", fontsize=12)
    ax.set_ylim(0, 105)
    ax.axhline(50, color="#F44336", linestyle="--", linewidth=0.8, alpha=0.5, label=">50% threshold")
    ax.legend(fontsize=9)
    ax.grid(True, alpha=0.3, axis="y")

    # --- Panel 3: Max unchanged streak per day ---
    ax = axes[2]
    colors_streak = ["#F44336" if s >= 12 else "#FF9800" if s >= 6 else "#4CAF50" for s in daily["max_streak"]]
    ax.bar(daily_dates, daily["max_streak"], color=colors_streak, width=0.8, edgecolor="none")
    ax.set_ylabel("Max Streak (hours)")
    ax.set_title("Longest Unchanged-Price Streak per Day", fontsize=12)
    ax.axhline(12, color="#F44336", linestyle="--", linewidth=0.8, alpha=0.5, label="12h threshold")
    ax.legend(fontsize=9)
    ax.grid(True, alpha=0.3, axis="y")

    # --- Panel 4: Hour-of-day × date heatmap of staleness ---
    ax = axes[3]
    pivot = df.pivot_table(
        index="hour", columns="date", values="is_stale",
        aggfunc="mean", fill_value=0,
    )
    # Custom colormap: green → yellow → red
    cmap = LinearSegmentedColormap.from_list("stale", ["#E8F5E9", "#FFEB3B", "#F44336"])
    im = ax.imshow(
        pivot.values, aspect="auto", cmap=cmap, vmin=0, vmax=1,
        interpolation="nearest",
    )
    ax.set_yticks(range(24))
    ax.set_ylabel("Hour (UTC)")
    ax.set_title("Staleness Heatmap (hour × date)", fontsize=12)

    # X-axis: show date labels
    n_cols = len(pivot.columns)
    if n_cols <= 30:
        ax.set_xticks(range(n_cols))
        ax.set_xticklabels([str(d) for d in pivot.columns], rotation=45, ha="right", fontsize=7)
    else:
        step = max(1, n_cols // 20)
        ticks = list(range(0, n_cols, step))
        ax.set_xticks(ticks)
        ax.set_xticklabels([str(pivot.columns[t]) for t in ticks], rotation=45, ha="right", fontsize=7)

    fig.colorbar(im, ax=ax, label="Stale fraction", shrink=0.6, pad=0.02)

    # --- Shared x-axis formatting for panels 0-2 ---
    for a in axes[:3]:
        a.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))
        a.xaxis.set_major_locator(mdates.WeekdayLocator(interval=1))
        a.tick_params(axis="x", rotation=30)

    fig.tight_layout(rect=[0, 0, 1, 0.96])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    log.info("Dashboard saved to %s", out_path)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Audit B2 price data quality")
    parser.add_argument("--months", type=int, default=2, help="Lookback months (default: 2)")
    parser.add_argument("--start", type=str, help="Override start date (YYYY-MM-DD)")
    parser.add_argument("--end", type=str, help="Override end date (YYYY-MM-DD)")
    args = parser.parse_args()

    today = date.today()
    if args.start and args.end:
        start = date.fromisoformat(args.start)
        end = date.fromisoformat(args.end)
    else:
        end = today
        start = date(today.year, today.month - args.months, today.day) if today.month > args.months else \
                date(today.year - 1, today.month - args.months + 12, today.day)

    log.info("Audit range: %s to %s (%d days)", start, end, (end - start).days)

    # 1. Connect & list files
    bucket = connect_b2()
    files_by_date = list_price_files(bucket, start, end)

    if not files_by_date:
        log.error("No price files found in B2 for the given range.")
        sys.exit(1)

    # 2. Download and reconstruct best candles per day
    df = get_best_candles_per_day(bucket, files_by_date)
    if df.empty:
        log.error("No data could be downloaded.")
        sys.exit(1)

    log.info("Downloaded %d hourly candles across %d days", len(df), df["datetime"].dt.date.nunique())

    # 3. Analyse
    df = analyse(df)
    daily = summarise_daily(df)

    # 4. Print summary
    total_stale = df["is_stale"].sum()
    total_candles = len(df)
    stale_pct = total_stale / total_candles * 100

    print("\n" + "=" * 70)
    print("B2 PRICE DATA AUDIT SUMMARY")
    print("=" * 70)
    print(f"  Date range       : {start} to {end}")
    print(f"  Total candles     : {total_candles}")
    print(f"  Stale candles     : {total_stale} ({stale_pct:.1f}%)")
    print(f"  Days with >50%   : {(daily['stale_pct'] > 50).sum()}")
    print(f"  Worst day streak  : {daily['max_streak'].max()}h")
    print()

    # Show worst days
    worst = daily.nlargest(10, "stale_pct")
    print("  Top 10 worst days:")
    print("  " + "-" * 60)
    for _, row in worst.iterrows():
        print(f"  {row['date']}  stale={row['stale_pct']:5.1f}%  "
              f"flat={row['flat_candles']:2.0f}/{row['total_candles']:.0f}  "
              f"max_streak={row['max_streak']:.0f}h")
    print()

    # 5. Save CSV
    results_dir = BASE_DIR / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    csv_path = results_dir / "b2_price_audit.csv"
    daily.to_csv(csv_path, index=False)
    log.info("Daily summary saved to %s", csv_path)

    # 6. Plot
    plots_dir = BASE_DIR / "plots"
    plot_audit(df, daily, plots_dir / "b2_price_audit.png")

    # Also save raw hourly data for further analysis
    hourly_path = results_dir / "b2_price_audit_hourly.csv"
    df.to_csv(hourly_path, index=False)
    log.info("Hourly detail saved to %s", hourly_path)


if __name__ == "__main__":
    main()
