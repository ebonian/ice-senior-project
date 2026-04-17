"""
Post-backfill OHLCV quality audit — before vs after comparison.

Downloads consolidated daily/ohlcv/ (on-chain swaps) and daily/prices/
(Binance klines) from B2 for all available 2026 dates.  Compares stale
candle rates, hourly coverage, price deviation, and produces a dashboard
showing the improvement.

Unlike 06_audit_b2_prices.py (which downloads dozens of raw snapshots per
day), this reads one consolidated file per source per day — much faster.

Usage (from backtest_model_server/):
    python scripts/07_audit_ohlcv_quality.py
    python scripts/07_audit_ohlcv_quality.py --start 2026-01-01 --end 2026-04-17

Requires: B2_ACCOUNT_ID, B2_ACCOUNT_KEY, B2_BUCKET_NAME env vars.
Output:   plots/ohlcv_quality_audit.png
          results/ohlcv_quality_audit.csv
"""

import sys
import io
import argparse
import logging
from pathlib import Path
from datetime import date, timedelta

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

POOL_PREFIX = "eth_usdt_0p05"


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


def download_parquet(bucket, key: str) -> pd.DataFrame | None:
    try:
        buf = io.BytesIO()
        bucket.download_file_by_name(key).save(buf)
        buf.seek(0)
        return pd.read_parquet(buf)
    except Exception:
        return None


def discover_daily_dates(bucket, subdir: str) -> list[date]:
    """Find all dates with daily/{subdir}/ files."""
    prefix = f"{POOL_PREFIX}/daily/{subdir}/"
    dates = set()
    for fv, _ in bucket.ls(prefix, recursive=False):
        name = fv.file_name.split("/")[-1]
        if name.endswith(".parquet"):
            try:
                dates.add(date.fromisoformat(name.replace(".parquet", "")))
            except ValueError:
                pass
    return sorted(dates)


# ---------------------------------------------------------------------------
# Download & parse
# ---------------------------------------------------------------------------

def load_daily_file(bucket, subdir: str, d: date) -> pd.DataFrame | None:
    """Download one consolidated daily file, return standardised DataFrame."""
    key = f"{POOL_PREFIX}/daily/{subdir}/{d.isoformat()}.parquet"
    df = download_parquet(bucket, key)
    if df is None or len(df) == 0:
        return None

    if "open_time" in df.columns:
        df["datetime"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    elif df.index.name in ("datetime", None) and hasattr(df.index, "tz"):
        df = df.reset_index()
        if "datetime" not in df.columns:
            df.columns = ["datetime"] + list(df.columns[1:])

    for col in ("open", "high", "low", "close", "volume"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    if "datetime" not in df.columns:
        return None

    df = df.sort_values("datetime").reset_index(drop=True)
    return df


def is_stale_row(row) -> bool:
    """Flat OHLC + zero volume = forward-filled stale candle."""
    flat = (
        row["open"] == row["high"] == row["low"] == row["close"]
    )
    zero_vol = row.get("volume", 0) == 0 or pd.isna(row.get("volume", 0))
    return flat and zero_vol


def analyse_day(df: pd.DataFrame) -> dict:
    """Compute quality metrics for one day's hourly candles."""
    n = len(df)
    if n == 0:
        return {"rows": 0, "stale": 0, "stale_pct": 0, "max_streak": 0,
                "price_min": None, "price_max": None, "price_range_pct": 0}

    stale_flags = [is_stale_row(row) for _, row in df.iterrows()]
    stale_count = sum(stale_flags)

    # Compute max streak of stale candles
    streak = max_streak = 0
    for s in stale_flags:
        if s:
            streak += 1
            max_streak = max(max_streak, streak)
        else:
            streak = 0

    # Compute max streak of unchanged close
    close_vals = df["close"].values
    unchanged_streak = max_unchanged = 0
    for i in range(1, len(close_vals)):
        if abs(close_vals[i] - close_vals[i - 1]) < 1e-6:
            unchanged_streak += 1
            max_unchanged = max(max_unchanged, unchanged_streak)
        else:
            unchanged_streak = 0

    pmin = df["close"].min()
    pmax = df["close"].max()
    prange = (pmax / pmin - 1) * 100 if pmin > 0 else 0

    return {
        "rows": n,
        "stale": stale_count,
        "stale_pct": round(100 * stale_count / n, 1),
        "max_streak": max(max_streak, max_unchanged),
        "price_min": round(pmin, 2),
        "price_max": round(pmax, 2),
        "price_range_pct": round(prange, 2),
    }


# ---------------------------------------------------------------------------
# Main audit logic
# ---------------------------------------------------------------------------

def run_audit(bucket, start: date, end: date):
    """Download both sources for every date, compare quality."""

    log.info("Discovering available dates...")
    ohlcv_dates = set(discover_daily_dates(bucket, "ohlcv"))
    prices_dates = set(discover_daily_dates(bucket, "prices"))
    all_dates = sorted(ohlcv_dates | prices_dates)
    all_dates = [d for d in all_dates if start <= d <= end]

    log.info("OHLCV dates: %d, Prices dates: %d, Union: %d (in range)",
             len([d for d in ohlcv_dates if start <= d <= end]),
             len([d for d in prices_dates if start <= d <= end]),
             len(all_dates))

    if not all_dates:
        log.error("No data found in [%s, %s]", start, end)
        sys.exit(1)

    records = []
    ohlcv_hourly_all = []
    prices_hourly_all = []

    for i, d in enumerate(all_dates):
        log.info("[%d/%d] %s", i + 1, len(all_dates), d.isoformat())

        rec = {"date": d, "has_ohlcv": False, "has_prices": False}

        # --- On-chain OHLCV ---
        ohlcv_df = load_daily_file(bucket, "ohlcv", d)
        if ohlcv_df is not None and len(ohlcv_df) > 0:
            rec["has_ohlcv"] = True
            stats = analyse_day(ohlcv_df)
            for k, v in stats.items():
                rec[f"ohlcv_{k}"] = v
            ohlcv_df["date"] = d
            ohlcv_df["hour"] = ohlcv_df["datetime"].dt.hour
            ohlcv_df["source"] = "ohlcv"
            ohlcv_hourly_all.append(ohlcv_df)
        else:
            for k in ("rows", "stale", "stale_pct", "max_streak",
                       "price_min", "price_max", "price_range_pct"):
                rec[f"ohlcv_{k}"] = 0 if k != "price_min" and k != "price_max" else None

        # --- Binance prices ---
        prices_df = load_daily_file(bucket, "prices", d)
        if prices_df is not None and len(prices_df) > 0:
            rec["has_prices"] = True
            stats = analyse_day(prices_df)
            for k, v in stats.items():
                rec[f"prices_{k}"] = v
            prices_df["date"] = d
            prices_df["hour"] = prices_df["datetime"].dt.hour
            prices_df["source"] = "prices"
            prices_hourly_all.append(prices_df)
        else:
            for k in ("rows", "stale", "stale_pct", "max_streak",
                       "price_min", "price_max", "price_range_pct"):
                rec[f"prices_{k}"] = 0 if k != "price_min" and k != "price_max" else None

        # --- Price deviation where both exist ---
        if ohlcv_df is not None and prices_df is not None:
            try:
                o = ohlcv_df[["datetime", "close"]].rename(columns={"close": "close_ohlcv"})
                p = prices_df[["datetime", "close"]].rename(columns={"close": "close_prices"})
                o["_h"] = o["datetime"].dt.floor("h")
                p["_h"] = p["datetime"].dt.floor("h")
                m = o.merge(p, on="_h")
                if len(m) > 0:
                    dev = (abs(m["close_ohlcv"] - m["close_prices"]) / m["close_prices"] * 100)
                    rec["max_dev_pct"] = round(dev.max(), 4)
                    rec["mean_dev_pct"] = round(dev.mean(), 4)
                else:
                    rec["max_dev_pct"] = rec["mean_dev_pct"] = None
            except Exception:
                rec["max_dev_pct"] = rec["mean_dev_pct"] = None
        else:
            rec["max_dev_pct"] = rec["mean_dev_pct"] = None

        records.append(rec)

    daily = pd.DataFrame(records)

    ohlcv_hourly = pd.concat(ohlcv_hourly_all, ignore_index=True) if ohlcv_hourly_all else pd.DataFrame()
    prices_hourly = pd.concat(prices_hourly_all, ignore_index=True) if prices_hourly_all else pd.DataFrame()

    return daily, ohlcv_hourly, prices_hourly


# ---------------------------------------------------------------------------
# Printing
# ---------------------------------------------------------------------------

def print_summary(daily: pd.DataFrame, start: date, end: date):
    n = len(daily)
    has_o = daily["has_ohlcv"].sum()
    has_p = daily["has_prices"].sum()

    # OHLCV totals
    o_rows = daily["ohlcv_rows"].sum()
    o_stale = daily["ohlcv_stale"].sum()
    o_pct = round(100 * o_stale / o_rows, 1) if o_rows > 0 else 0
    o_max = daily["ohlcv_max_streak"].max() if has_o else 0

    # Prices totals
    p_rows = daily["prices_rows"].sum()
    p_stale = daily["prices_stale"].sum()
    p_pct = round(100 * p_stale / p_rows, 1) if p_rows > 0 else 0
    p_max = daily["prices_max_streak"].max() if has_p else 0

    print()
    print("=" * 78)
    print("  POST-BACKFILL OHLCV QUALITY AUDIT")
    print("=" * 78)
    print(f"  Date range : {start} to {end}  ({n} days checked)")
    print()
    print(f"  {'':30s}  {'On-chain OHLCV':>16s}  {'Binance prices':>16s}")
    print(f"  {'':30s}  {'(daily/ohlcv/)':>16s}  {'(daily/prices/)':>16s}")
    print(f"  {'-'*30}  {'-'*16}  {'-'*16}")
    print(f"  {'Days with data':30s}  {has_o:>13d}/{n}  {has_p:>13d}/{n}")
    print(f"  {'Total candles':30s}  {o_rows:>16.0f}  {p_rows:>16.0f}")
    print(f"  {'Stale candles':30s}  {o_stale:>16.0f}  {p_stale:>16.0f}")
    print(f"  {'Stale %':30s}  {o_pct:>15.1f}%  {p_pct:>15.1f}%")
    print(f"  {'Worst streak (hours)':30s}  {o_max:>16.0f}  {p_max:>16.0f}")

    # Improvement
    if p_pct > 0 and o_pct < p_pct:
        improvement = p_pct - o_pct
        print()
        print(f"  IMPROVEMENT:  stale rate dropped {p_pct:.1f}% -> {o_pct:.1f}%  "
              f"(-{improvement:.1f} pp)")
    elif o_pct == 0 and p_pct > 0:
        print()
        print(f"  IMPROVEMENT:  stale rate dropped {p_pct:.1f}% -> 0%  (fully resolved)")

    # Missing OHLCV dates
    missing = daily[~daily["has_ohlcv"]]
    if len(missing) > 0:
        print()
        print(f"  WARNING: {len(missing)} dates missing daily/ohlcv/ files:")
        for _, row in missing.iterrows():
            print(f"    {row['date']}")

    # Incomplete days (< 24 rows)
    if has_o:
        incomplete = daily[(daily["has_ohlcv"]) & (daily["ohlcv_rows"] < 24)]
        if len(incomplete) > 0:
            print()
            print(f"  WARNING: {len(incomplete)} dates have < 24 hourly candles:")
            for _, row in incomplete.iterrows():
                print(f"    {row['date']}  rows={row['ohlcv_rows']:.0f}")

    # Price deviation
    devs = daily["max_dev_pct"].dropna()
    if len(devs) > 0:
        print()
        print(f"  Price deviation (OHLCV vs Binance):")
        print(f"    Mean max deviation : {devs.mean():.4f}%")
        print(f"    Worst day max dev  : {devs.max():.4f}%")

    print()
    print("=" * 78)
    print()


def print_per_day_table(daily: pd.DataFrame):
    """Compact per-day comparison table."""
    print(f"  {'Date':12s}  {'OHLCV rows':>10s}  {'OHLCV stale%':>12s}  "
          f"{'Prices rows':>11s}  {'Prices stale%':>13s}  {'Max dev%':>9s}")
    print(f"  {'-'*12}  {'-'*10}  {'-'*12}  {'-'*11}  {'-'*13}  {'-'*9}")

    for _, r in daily.iterrows():
        o_r = f"{r['ohlcv_rows']:.0f}" if r["has_ohlcv"] else "---"
        o_s = f"{r['ohlcv_stale_pct']:.1f}%" if r["has_ohlcv"] else "---"
        p_r = f"{r['prices_rows']:.0f}" if r["has_prices"] else "---"
        p_s = f"{r['prices_stale_pct']:.1f}%" if r["has_prices"] else "---"
        dev = f"{r['max_dev_pct']:.3f}%" if pd.notna(r.get("max_dev_pct")) else "---"
        print(f"  {str(r['date']):12s}  {o_r:>10s}  {o_s:>12s}  "
              f"{p_r:>11s}  {p_s:>13s}  {dev:>9s}")
    print()


# ---------------------------------------------------------------------------
# Plotting
# ---------------------------------------------------------------------------

def plot_dashboard(daily: pd.DataFrame, ohlcv_hourly: pd.DataFrame,
                   prices_hourly: pd.DataFrame, out_path: Path):
    """5-panel before/after dashboard."""

    fig, axes = plt.subplots(5, 1, figsize=(20, 22),
                             height_ratios=[2.5, 1.2, 1.2, 1.5, 1.5])
    fig.suptitle("OHLCV Quality Audit — On-chain vs Binance",
                 fontsize=16, fontweight="bold", y=0.98)

    daily_dates = pd.to_datetime(daily["date"])

    # ── Panel 1: Price overlay with stale regions ─────────────────────────
    ax = axes[0]

    if len(ohlcv_hourly) > 0:
        odt = pd.to_datetime(ohlcv_hourly["datetime"])
        ax.plot(odt, ohlcv_hourly["close"], linewidth=0.8,
                color="#2196F3", label="On-chain OHLCV close", zorder=3)

    if len(prices_hourly) > 0:
        pdt = pd.to_datetime(prices_hourly["datetime"])
        ax.plot(pdt, prices_hourly["close"], linewidth=0.5,
                color="#FF9800", alpha=0.6, label="Binance close", zorder=2)

        # Shade Binance stale regions
        stale_flags = [is_stale_row(r) for _, r in prices_hourly.iterrows()]
        in_stale = False
        for i, s in enumerate(stale_flags):
            if s and not in_stale:
                start_t = pdt.iloc[i]
                in_stale = True
            elif not s and in_stale:
                ax.axvspan(start_t, pdt.iloc[i], alpha=0.15, color="#F44336", zorder=1)
                in_stale = False
        if in_stale:
            ax.axvspan(start_t, pdt.iloc[-1], alpha=0.15, color="#F44336", zorder=1)
        ax.axvspan(pdt.iloc[0], pdt.iloc[0], alpha=0.15,
                   color="#F44336", label="Binance stale")

    ax.set_ylabel("Price ($)")
    ax.legend(loc="upper left", fontsize=9)
    ax.set_title("Price Timeline — On-chain vs Binance (stale regions shaded)", fontsize=12)
    ax.grid(True, alpha=0.3)

    # ── Panel 2: Side-by-side stale % bars ────────────────────────────────
    ax = axes[1]
    width = 0.38
    x = np.arange(len(daily))
    bars_o = daily["ohlcv_stale_pct"].fillna(0).values
    bars_p = daily["prices_stale_pct"].fillna(0).values

    ax.bar(x - width / 2, bars_p, width, color="#FF9800", alpha=0.7, label="Binance prices")
    ax.bar(x + width / 2, bars_o, width, color="#2196F3", alpha=0.7, label="On-chain OHLCV")
    ax.set_ylabel("Stale %")
    ax.set_title("Daily Stale Candle % — Before (Binance) vs After (On-chain)", fontsize=12)
    ax.set_ylim(0, 105)
    ax.axhline(50, color="#F44336", ls="--", lw=0.8, alpha=0.5)
    ax.legend(fontsize=9)
    ax.grid(True, alpha=0.3, axis="y")

    # X-ticks
    if len(daily) <= 40:
        ax.set_xticks(x)
        ax.set_xticklabels([str(d) for d in daily["date"]], rotation=45, ha="right", fontsize=7)
    else:
        step = max(1, len(daily) // 25)
        ticks = list(range(0, len(daily), step))
        ax.set_xticks(ticks)
        ax.set_xticklabels([str(daily["date"].iloc[t]) for t in ticks],
                           rotation=45, ha="right", fontsize=7)

    # ── Panel 3: Max streak comparison ────────────────────────────────────
    ax = axes[2]
    streak_o = daily["ohlcv_max_streak"].fillna(0).values
    streak_p = daily["prices_max_streak"].fillna(0).values
    ax.bar(x - width / 2, streak_p, width, color="#FF9800", alpha=0.7, label="Binance prices")
    ax.bar(x + width / 2, streak_o, width, color="#2196F3", alpha=0.7, label="On-chain OHLCV")
    ax.set_ylabel("Max Streak (h)")
    ax.set_title("Longest Stale Streak per Day", fontsize=12)
    ax.axhline(6, color="#F44336", ls="--", lw=0.8, alpha=0.5, label="6h threshold")
    ax.legend(fontsize=9)
    ax.grid(True, alpha=0.3, axis="y")
    if len(daily) <= 40:
        ax.set_xticks(x)
        ax.set_xticklabels([str(d) for d in daily["date"]], rotation=45, ha="right", fontsize=7)
    else:
        ax.set_xticks(ticks)
        ax.set_xticklabels([str(daily["date"].iloc[t]) for t in ticks],
                           rotation=45, ha="right", fontsize=7)

    # ── Panel 4: Binance staleness heatmap (before) ──────────────────────
    _plot_staleness_heatmap(axes[3], prices_hourly, daily,
                           "Binance Prices — Staleness Heatmap (BEFORE)")

    # ── Panel 5: On-chain OHLCV staleness heatmap (after) ────────────────
    _plot_staleness_heatmap(axes[4], ohlcv_hourly, daily,
                           "On-chain OHLCV — Staleness Heatmap (AFTER)")

    fig.tight_layout(rect=[0, 0, 1, 0.96])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    log.info("Dashboard saved to %s", out_path)


def _plot_staleness_heatmap(ax, hourly_df: pd.DataFrame, daily: pd.DataFrame,
                            title: str):
    """Hour × date staleness heatmap."""
    cmap = LinearSegmentedColormap.from_list("stale", ["#E8F5E9", "#FFEB3B", "#F44336"])

    if len(hourly_df) == 0:
        ax.set_title(f"{title}  [NO DATA]", fontsize=12)
        ax.text(0.5, 0.5, "No data", transform=ax.transAxes,
                ha="center", va="center", fontsize=14, color="#999")
        return

    hourly_df = hourly_df.copy()
    hourly_df["is_stale"] = hourly_df.apply(is_stale_row, axis=1)
    pivot = hourly_df.pivot_table(
        index="hour", columns="date", values="is_stale",
        aggfunc="mean", fill_value=0,
    )

    im = ax.imshow(pivot.values, aspect="auto", cmap=cmap, vmin=0, vmax=1,
                   interpolation="nearest")
    ax.set_yticks(range(0, 24, 2))
    ax.set_ylabel("Hour (UTC)")
    ax.set_title(title, fontsize=12)

    n_cols = len(pivot.columns)
    if n_cols <= 40:
        ax.set_xticks(range(n_cols))
        ax.set_xticklabels([str(d) for d in pivot.columns],
                           rotation=45, ha="right", fontsize=6)
    else:
        step = max(1, n_cols // 25)
        t = list(range(0, n_cols, step))
        ax.set_xticks(t)
        ax.set_xticklabels([str(pivot.columns[i]) for i in t],
                           rotation=45, ha="right", fontsize=6)

    plt.colorbar(im, ax=ax, label="Stale fraction", shrink=0.6, pad=0.02)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Audit on-chain OHLCV vs Binance prices — post-backfill verification"
    )
    parser.add_argument("--start", type=str, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", type=str, help="End date (YYYY-MM-DD)")
    args = parser.parse_args()

    today = date.today()
    bucket = connect_b2()

    # Auto-detect range from available OHLCV dates if not specified
    if args.start and args.end:
        start = date.fromisoformat(args.start)
        end = date.fromisoformat(args.end)
    else:
        log.info("Auto-detecting date range from B2...")
        ohlcv_dates = discover_daily_dates(bucket, "ohlcv")
        prices_dates = discover_daily_dates(bucket, "prices")
        all_dates = sorted(set(ohlcv_dates) | set(prices_dates))
        # Filter to 2026 only
        all_dates = [d for d in all_dates if d.year == 2026]
        if not all_dates:
            log.error("No 2026 data found in B2")
            sys.exit(1)
        start = all_dates[0]
        end = all_dates[-1]
        log.info("Auto-detected: %s to %s (%d dates)", start, end, len(all_dates))

    log.info("Audit range: %s to %s", start, end)

    # Run audit
    daily, ohlcv_hourly, prices_hourly = run_audit(bucket, start, end)

    # Print results
    print_summary(daily, start, end)
    print_per_day_table(daily)

    # Save CSV
    results_dir = BASE_DIR / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    csv_path = results_dir / "ohlcv_quality_audit.csv"
    daily.to_csv(csv_path, index=False)
    log.info("Daily summary saved to %s", csv_path)

    # Plot dashboard
    plots_dir = BASE_DIR / "plots"
    plot_dashboard(daily, ohlcv_hourly, prices_hourly,
                   plots_dir / "ohlcv_quality_audit.png")

    # Save hourly detail CSVs
    if len(ohlcv_hourly) > 0:
        ohlcv_hourly.to_csv(results_dir / "ohlcv_hourly_detail.csv", index=False)
    if len(prices_hourly) > 0:
        prices_hourly.to_csv(results_dir / "prices_hourly_detail.csv", index=False)
    log.info("Hourly detail CSVs saved to %s", results_dir)


if __name__ == "__main__":
    main()
