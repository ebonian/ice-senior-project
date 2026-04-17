"""
Phase 1b-1c — Convert raw swaps to hourly OHLCV and validate against Binance.

Usage (from backtest_model_server/):
    python scripts/02_prepare_ohlcv.py
    python scripts/02_prepare_ohlcv.py --config config/backtest_config.yaml
    python scripts/02_prepare_ohlcv.py --skip-validation   # skip Binance comparison

Input:   data/raw_swaps/raw/swaps/ (preferred) or data/raw_swaps/swaps/ (legacy)
Output:  data/ohlcv/hourly_ohlcv.parquet
         data/ohlcv/binance_comparison.csv   (unless --skip-validation)
         data/ohlcv/binance_comparison.png
"""

import sys
import argparse
import logging
from pathlib import Path
from datetime import date, datetime

import yaml
import pandas as pd

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
BASE_DIR   = SCRIPT_DIR.parent
LLAMINET   = BASE_DIR.parent.parent
POC_DIR    = LLAMINET / "research" / "research" / "poc"

sys.path.insert(0, str(POC_DIR))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


def load_config(config_path: Path) -> dict:
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def normalize_config_date(value, field_name: str) -> str:
    """Return config date as YYYY-MM-DD string for slicing and API calls."""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value).date().isoformat()
        except ValueError as exc:
            raise ValueError(
                f"Invalid {field_name} '{value}' (expected ISO format YYYY-MM-DD)"
            ) from exc
    raise TypeError(
        f"Invalid {field_name} type {type(value).__name__} (expected str/date/datetime)"
    )


def main():
    parser = argparse.ArgumentParser(description="Build hourly OHLCV from raw swaps + validate vs Binance")
    parser.add_argument("--config", default=str(BASE_DIR / "config" / "backtest_config.yaml"))
    parser.add_argument("--skip-validation", action="store_true",
                        help="Skip Binance comparison (useful offline or for quick runs)")
    parser.add_argument("--show-plots", action="store_true", help="Show matplotlib popup windows")
    args = parser.parse_args()

    cfg = load_config(Path(args.config))
    try:
        start_date = normalize_config_date(cfg["start_date"], "start_date")
        end_date = normalize_config_date(cfg["end_date"], "end_date")
    except (KeyError, TypeError, ValueError) as e:
        log.error("Invalid date config: %s", e)
        sys.exit(1)

    if start_date > end_date:
        log.error("Invalid date range: start_date (%s) is after end_date (%s)", start_date, end_date)
        sys.exit(1)

    threshold  = cfg.get("binance_deviation_threshold_pct", 0.5)

    raw_candidates = [
        BASE_DIR / "data" / "raw_swaps" / "swaps",      # legacy/expected layout
        BASE_DIR / "data" / "raw_swaps" / "raw" / "swaps",  # fetch_b2_data.py layout
    ]
    raw_dir = raw_candidates[0]
    for candidate in raw_candidates:
        if candidate.exists() and any(candidate.rglob("*.parquet")):
            raw_dir = candidate
            break

    ohlcv_dir = BASE_DIR / "data" / "ohlcv"
    ohlcv_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Import POC helpers
    # ------------------------------------------------------------------
    try:
        from poc_ohlc_from_swap_data import load_swaps_from_parquet, build_hourly_ohlcv
    except ImportError as e:
        log.error("Cannot import poc_ohlc_from_swap_data from %s: %s", POC_DIR, e)
        sys.exit(1)

    # ------------------------------------------------------------------
    # Build OHLCV from raw swaps
    # ------------------------------------------------------------------
    if not raw_dir.exists() or not any(raw_dir.rglob("*.parquet")):
        log.error(
            "No parquet files found in expected locations: %s",
            ", ".join(str(p) for p in raw_candidates),
        )
        log.error("Run 01_pull_data.py first")
        sys.exit(1)
    log.info("Using raw swaps directory: %s", raw_dir)

    log.info("Loading swaps from %s ...", raw_dir)
    swaps = load_swaps_from_parquet(raw_dir)
    log.info("Loaded %d swap events", len(swaps))

    if swaps.empty:
        log.error("No swap data loaded — check that B2 download succeeded")
        sys.exit(1)

    log.info("Building hourly OHLCV ...")
    hourly = build_hourly_ohlcv(swaps, decimals0=18, decimals1=6)
    log.info("Hourly OHLCV: %d rows, %s → %s",
             len(hourly), hourly.index.min(), hourly.index.max())

    # Filter to configured date range
    hourly = hourly.loc[start_date:end_date]
    log.info("Filtered to range: %d rows", len(hourly))

    # Save
    ohlcv_path = ohlcv_dir / "hourly_ohlcv.parquet"
    hourly.to_parquet(ohlcv_path)
    log.info("Saved OHLCV to %s", ohlcv_path)

    # Also save a candle plot
    try:
        from poc_ohlc_from_swap_data import plot_candles
        plot_candles(
            hourly,
            output_png=ohlcv_dir / "ohlcv_candles.png",
            title=f"ETH/USDC Hourly OHLCV ({start_date} → {end_date})",
            tz_label="UTC",
            show_popup=args.show_plots,
        )
        log.info("Candle chart saved to data/ohlcv/ohlcv_candles.png")
    except Exception as e:
        log.warning("Could not plot candles: %s", e)

    # ------------------------------------------------------------------
    # Validate against Binance
    # ------------------------------------------------------------------
    if args.skip_validation:
        log.info("Skipping Binance validation (--skip-validation flag set)")
        return

    try:
        from compare_swaps_vs_binance import (
            fetch_binance_hourly_ohlcv,
            build_comparison_dataframe,
            plot_comparison,
        )
    except ImportError as e:
        log.warning("Cannot import compare_swaps_vs_binance: %s — skipping validation", e)
        return

    log.info("Fetching Binance OHLCV for validation ...")
    try:
        binance = fetch_binance_hourly_ohlcv(
            start_utc=pd.Timestamp(start_date, tz="UTC"),
            end_utc=pd.Timestamp(end_date, tz="UTC") + pd.Timedelta(days=1),
        )
    except Exception as e:
        log.warning("Binance fetch failed: %s — skipping validation", e)
        return

    log.info("Binance rows: %d", len(binance))
    comp = build_comparison_dataframe(hourly, binance)

    if comp.empty:
        log.warning("Comparison DataFrame is empty — no overlapping timestamps")
        return

    # Check deviation
    median_diff_bps = comp["close_diff_bps"].abs().median()
    log.info("Median close price deviation: %.2f bps (%.4f%%)", median_diff_bps, median_diff_bps / 100)

    comp_path = ohlcv_dir / "binance_comparison.csv"
    comp.to_csv(comp_path)
    log.info("Comparison CSV saved to %s", comp_path)

    try:
        plot_comparison(
            comp,
            output_png=ohlcv_dir / "binance_comparison.png",
            tz_label="UTC",
            show_popup=args.show_plots,
        )
        log.info("Comparison chart saved to data/ohlcv/binance_comparison.png")
    except Exception as e:
        log.warning("Could not plot comparison: %s", e)

    threshold_bps = threshold * 100  # convert pct to bps
    if median_diff_bps > threshold_bps:
        log.error(
            "VALIDATION FAILED: median price deviation %.2f bps exceeds threshold %.2f bps (%.2f%%)",
            median_diff_bps, threshold_bps, threshold,
        )
        log.error("Check B2 swap data quality or widen threshold in config")
        sys.exit(1)
    else:
        log.info("Validation PASSED: deviation within %.2f%% threshold", threshold)


if __name__ == "__main__":
    main()
