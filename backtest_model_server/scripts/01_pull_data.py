"""
Phase 1a — Pull raw swap data from B2 for the configured date range.

Usage (from backtest_model_server/):
    python scripts/01_pull_data.py
    python scripts/01_pull_data.py --config config/backtest_config.yaml
    python scripts/01_pull_data.py --list   # dry-run: show available dates

Requires env vars:  B2_ACCOUNT_ID, B2_ACCOUNT_KEY, B2_BUCKET_NAME
Output:             data/raw_swaps/raw/swaps/YYYY-MM-DD/*.parquet       (15-min raw swaps for simulation)
                    data/raw_swaps/raw/prices/YYYY-MM-DD/*.parquet      (optional)
                    data/raw_swaps/daily/ohlcv/YYYY-MM-DD.parquet       (hourly OHLCV, built by the pipeline consolidator)

The daily/ohlcv/ files are the same on-chain-derived OHLCV the model server
consumes in prod (see pipeline/consolidator/ohlcv.go :: BuildOHLCVFromSwaps).
Script 02 concatenates them into data/ohlcv/hourly_ohlcv.parquet instead of
rebuilding locally from swaps.
"""

import sys
import os
import argparse
import logging
from pathlib import Path
from datetime import date, datetime

# ---------------------------------------------------------------------------
# Resolve paths
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
BASE_DIR   = SCRIPT_DIR.parent                          # backtest_model_server/
LLAMINET   = BASE_DIR.parent.parent                     # C:/Coding/llaminet/
PIPELINE   = LLAMINET / "pipeline" / "scripts"

# Add pipeline scripts to path so we can import fetch_b2_data directly
sys.path.insert(0, str(PIPELINE))

import yaml

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


def load_config(config_path: Path) -> dict:
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def parse_config_date(value, field_name: str) -> datetime:
    """Parse config date values to datetime for fetch_b2_data helpers."""
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(
                f"Invalid {field_name} '{value}' (expected ISO format YYYY-MM-DD)"
            ) from exc
    raise TypeError(
        f"Invalid {field_name} type {type(value).__name__} (expected str/date/datetime)"
    )


def main():
    parser = argparse.ArgumentParser(description="Pull B2 swap/prices data for backtest date range")
    parser.add_argument("--config", default=str(BASE_DIR / "config" / "backtest_config.yaml"))
    parser.add_argument("--list", action="store_true", help="Dry-run: list available dates and exit")
    parser.add_argument("--types", default="swaps,ohlcv",
                        help="Comma-separated data types to download. Raw types (swaps, prices, mints, "
                             "burns, state, states) pull 15-min files. 'ohlcv' pulls daily consolidated "
                             "OHLCV (default: swaps,ohlcv)")
    args = parser.parse_args()

    cfg = load_config(Path(args.config))
    try:
        start_date = parse_config_date(cfg["start_date"], "start_date")
        end_date = parse_config_date(cfg["end_date"], "end_date")
    except (KeyError, TypeError, ValueError) as e:
        log.error("Invalid date config: %s", e)
        sys.exit(1)

    if start_date > end_date:
        log.error(
            "Invalid date range: start_date (%s) is after end_date (%s)",
            start_date.date().isoformat(),
            end_date.date().isoformat(),
        )
        sys.exit(1)

    output_dir = BASE_DIR / "data" / "raw_swaps"

    log.info("Date range : %s → %s", start_date.date().isoformat(), end_date.date().isoformat())
    log.info("Output dir : %s", output_dir)
    log.info("Types      : %s", args.types)

    # ------------------------------------------------------------------
    # Import fetch_b2_data functions
    # ------------------------------------------------------------------
    try:
        from fetch_b2_data import (
            load_b2_credentials,
            create_b2_client,
            list_all_raw_files,
            filter_files_by_date_range,
            print_summary,
            DATA_TYPES,
        )
    except ImportError as e:
        log.error("Cannot import fetch_b2_data from %s: %s", PIPELINE, e)
        sys.exit(1)

    # ------------------------------------------------------------------
    # Authenticate
    # ------------------------------------------------------------------
    try:
        account_id, account_key, bucket_name = load_b2_credentials()
    except Exception as e:
        log.error("B2 credentials error: %s", e)
        log.error("Set B2_ACCOUNT_ID, B2_ACCOUNT_KEY, B2_BUCKET_NAME env vars")
        sys.exit(1)

    b2 = create_b2_client(account_id, account_key)
    bucket = b2.get_bucket_by_name(bucket_name)
    log.info("Connected to B2 bucket: %s", bucket_name)

    # ------------------------------------------------------------------
    # List or download
    # ------------------------------------------------------------------
    data_types = [t.strip() for t in args.types.split(",") if t.strip()]
    ohlcv_requested = "ohlcv" in data_types
    raw_types = [t for t in data_types if t != "ohlcv"]

    invalid_types = [t for t in raw_types if t not in DATA_TYPES]
    if invalid_types:
        log.error(
            "Invalid --types values: %s (valid: %s,ohlcv)",
            ",".join(invalid_types), ",".join(DATA_TYPES),
        )
        sys.exit(1)

    pool_prefix = cfg.get("pool_prefix", "eth_usdc_0p05")
    log.info("Pool prefix: %s", pool_prefix)
    all_raw_files = list_all_raw_files(bucket, pool_prefix=pool_prefix) if raw_types else {}

    if args.list:
        for dtype in raw_types:
            files = all_raw_files.get(dtype, [])
            filtered = filter_files_by_date_range(files, start_date, end_date, is_daily=False)
            log.info("[raw %s] %d files available in range", dtype, len(filtered))
            for f in filtered[:5]:
                print(f"  {f}")
            if len(filtered) > 5:
                print(f"  ... and {len(filtered) - 5} more")
        if ohlcv_requested:
            ohlcv_dates = _list_daily_ohlcv_dates(bucket, start_date, end_date, pool_prefix)
            log.info("[daily ohlcv] %d files available in range", len(ohlcv_dates))
            for d in ohlcv_dates[:5]:
                print(f"  {pool_prefix}/daily/ohlcv/{d}.parquet")
            if len(ohlcv_dates) > 5:
                print(f"  ... and {len(ohlcv_dates) - 5} more")
        return

    log.info("Starting download...")
    downloaded: dict = {}

    if raw_types:
        raw_downloaded = {dtype: [] for dtype in raw_types}
        output_dir.mkdir(parents=True, exist_ok=True)
        for dtype in raw_types:
            files = all_raw_files.get(dtype, [])
            filtered = filter_files_by_date_range(files, start_date, end_date, is_daily=False)
            if not filtered:
                log.warning("[%s] no files found in range for pool_prefix=%s", dtype, pool_prefix)
                continue

            log.info("[%s] downloading %d files", dtype, len(filtered))
            for remote_path in filtered:
                parts = remote_path.split("/")
                if len(parts) < 7:
                    log.warning("Skipping unexpected B2 path shape: %s", remote_path)
                    continue
                date_path = f"{parts[3]}-{parts[4]}-{parts[5]}"
                filename = parts[-1]
                local_path = output_dir / "raw" / dtype / date_path / filename
                try:
                    local_path.parent.mkdir(parents=True, exist_ok=True)
                    bucket.download_file_by_name(remote_path).save_to(str(local_path))
                    raw_downloaded[dtype].append(local_path)
                except Exception as e:
                    log.warning("Error downloading %s: %s", remote_path, e)
        downloaded.update(raw_downloaded)

    if ohlcv_requested:
        ohlcv_downloaded = _download_daily_ohlcv(
            bucket, start_date, end_date, output_dir=output_dir, pool_prefix=pool_prefix,
        )
        downloaded["ohlcv"] = ohlcv_downloaded

    print_summary(downloaded)

    total = sum(len(v) for v in downloaded.values())
    log.info("Done. Downloaded %d files to %s", total, output_dir)


def _list_daily_ohlcv_dates(bucket, start_date, end_date, pool_prefix: str) -> list[str]:
    """Return sorted list of YYYY-MM-DD strings available in the daily/ohlcv/ prefix, inclusive of range."""
    prefix = f"{pool_prefix}/daily/ohlcv/"
    dates: list[str] = []
    for file_version, _ in bucket.ls(folder_to_list=prefix, recursive=True):
        name = file_version.file_name
        if not name.endswith(".parquet"):
            continue
        date_str = name.split("/")[-1].removesuffix(".parquet")
        try:
            dt = datetime.fromisoformat(date_str)
        except ValueError:
            continue
        if start_date <= dt <= end_date:
            dates.append(date_str)
    return sorted(dates)


def _download_daily_ohlcv(bucket, start_date, end_date,
                          output_dir: Path,
                          pool_prefix: str) -> list[Path]:
    """Download all daily OHLCV parquet files in range to {output_dir}/daily/ohlcv/."""
    prefix = f"{pool_prefix}/daily/ohlcv/"
    dates = _list_daily_ohlcv_dates(bucket, start_date, end_date, pool_prefix)
    if not dates:
        log.warning("No daily/ohlcv files found in %s → %s",
                    start_date.date().isoformat(), end_date.date().isoformat())
        return []

    dest_dir = output_dir / "daily" / "ohlcv"
    dest_dir.mkdir(parents=True, exist_ok=True)
    log.info("Downloading %d daily OHLCV files to %s", len(dates), dest_dir)

    written: list[Path] = []
    for date_str in dates:
        remote = f"{prefix}{date_str}.parquet"
        local = dest_dir / f"{date_str}.parquet"
        try:
            bucket.download_file_by_name(remote).save_to(str(local))
            written.append(local)
        except Exception as e:
            log.warning("Failed to download %s: %s", remote, e)
    return written


if __name__ == "__main__":
    main()
