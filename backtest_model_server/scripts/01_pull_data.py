"""
Phase 1a — Pull raw swap data from B2 for the configured date range.

Usage (from backtest_model_server/):
    python scripts/01_pull_data.py
    python scripts/01_pull_data.py --config config/backtest_config.yaml
    python scripts/01_pull_data.py --list   # dry-run: show available dates

Requires env vars:  B2_ACCOUNT_ID, B2_ACCOUNT_KEY, B2_BUCKET_NAME
Output:             data/raw_swaps/raw/swaps/YYYY-MM-DD/*.parquet
                    data/raw_swaps/raw/prices/YYYY-MM-DD/*.parquet
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
    parser.add_argument("--types", default="swaps,prices",
                        help="Comma-separated data types to download (default: swaps,prices)")
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
            download_raw_files,
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
    invalid_types = [t for t in data_types if t not in DATA_TYPES]
    if invalid_types:
        log.error("Invalid --types values: %s (valid: %s)", ",".join(invalid_types), ",".join(DATA_TYPES))
        sys.exit(1)

    all_files = list_all_raw_files(bucket, pool_prefix="eth_usdc_0p05")

    if args.list:
        for dtype in data_types:
            files = all_files.get(dtype, [])
            filtered = filter_files_by_date_range(files, start_date, end_date, is_daily=False)
            log.info("[%s] %d files available in range", dtype, len(filtered))
            for f in filtered[:5]:
                print(f"  {f}")
            if len(filtered) > 5:
                print(f"  ... and {len(filtered) - 5} more")
        return

    log.info("Starting download...")
    downloaded = download_raw_files(
        bucket,
        start_date=start_date,
        end_date=end_date,
        data_types=data_types,
        output_dir=output_dir,
    )

    print_summary(downloaded)

    total = sum(len(v) for v in downloaded.values())
    log.info("Done. Downloaded %d files to %s", total, output_dir)


if __name__ == "__main__":
    main()
