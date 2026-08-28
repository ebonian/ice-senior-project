#!/usr/bin/env python3
"""
Rebuild the simulation_14 training swaps CSV from the project's B2 daily parquets.

The concatenated CSV that simulation_14 was trained on
(`swaps_20250504_to_20260212_eth_usdc_0p05.csv`, per
`research/simulation_13/training_data/README.md`) is not on disk, and the daily
CSVs it was built from (`downloaded_data_csv/daily/swaps/`) are not either. The
same swap events are still in B2 under `eth_usdc_0p05/daily/swaps/*.parquet`, so
this script streams them back down and writes the CSV shape that
`prepare_interval_data` expects (`uniswap_v3_ppo_paper.py:420-429`):

    evt_block_time, sqrtPriceX96, amount0, amount1, liquidity, tick

Only a date slice is fetched, not the full training range: the machine this was
written on had ~1.2 GB free and the full 2025-05-04..2026-04-17 series is ~1.46 GB
as CSV. A slice covering the four walk-forward *test* windows plus a long feature
lead-in is enough, because every feature in FEATURE_COLS has a bounded lookback
(longest is ma_200 at 200 bars; the `ewm(alpha=0.05)` volatility term decays by
0.95^n and is below float64 resolution after ~700 bars). See REPORT.md for how the
window alignment is verified against the published fold-0 PnL.

Credentials come from the model service's .env, read-only. The bot/model repos are
never written to.

Usage:
    python fetch_swaps_from_b2.py --start 2025-11-01 --end 2026-04-20
"""

from __future__ import annotations

import argparse
import io
import os
import shutil
import sys

import pandas as pd

DEFAULT_ENV_PATH = "/home/poon/developments/llaminet/model/.env"
B2_SWAPS_PREFIX = "daily/swaps/"
OUT_COLS = ["evt_block_time", "sqrtPriceX96", "amount0", "amount1", "liquidity", "tick"]

# Column names in the B2 daily parquets -> the names prepare_interval_data wants.
B2_TO_TRAINING_COLS = {
    "sqrt_price_x96": "sqrtPriceX96",
    "amount0": "amount0",
    "amount1": "amount1",
    "liquidity": "liquidity",
    "tick": "tick",
}


def read_env(path: str) -> dict:
    env = {}
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            env[key] = value.strip().strip('"').strip("'")
    return env


def open_bucket(env: dict):
    from b2sdk.v2 import B2Api, InMemoryAccountInfo

    api = B2Api(InMemoryAccountInfo())
    api.authorize_account("production", env["B2_ACCOUNT_ID"], env["B2_ACCOUNT_KEY"])
    return api.get_bucket_by_name(env["B2_BUCKET_NAME"])


def free_bytes(path: str) -> int:
    return shutil.disk_usage(path).free


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", required=True, help="first daily key, YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="last daily key, YYYY-MM-DD")
    parser.add_argument(
        "--out-dir",
        default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "_data"),
    )
    parser.add_argument("--env-path", default=DEFAULT_ENV_PATH)
    parser.add_argument(
        "--min-free-gb",
        type=float,
        default=0.25,
        help="abort if free disk would drop below this",
    )
    args = parser.parse_args()

    env = read_env(args.env_path)
    prefix = f"{env.get('B2_POOL_PREFIX', 'eth_usdc_0p05')}/{B2_SWAPS_PREFIX}"
    bucket = open_bucket(env)

    keys = []
    for file_version, _ in bucket.ls(prefix, recursive=True):
        day = os.path.basename(file_version.file_name).replace(".parquet", "")
        if args.start <= day <= args.end:
            keys.append((day, file_version.file_name))
    keys.sort()
    if not keys:
        print(f"No daily swap files in {prefix} for {args.start}..{args.end}", file=sys.stderr)
        return 1

    os.makedirs(args.out_dir, exist_ok=True)
    out_name = (
        f"swaps_{args.start.replace('-', '')}_to_{args.end.replace('-', '')}"
        f"_eth_usdc_0p05.csv"
    )
    out_path = os.path.join(args.out_dir, out_name)

    print(f"{len(keys)} daily files -> {out_path}")
    total_rows = 0
    min_free = int(args.min_free_gb * 1e9)

    with open(out_path, "w") as out_fh:
        for i, (day, key) in enumerate(keys):
            if free_bytes(args.out_dir) < min_free:
                print(
                    f"ABORT at {day}: free disk below {args.min_free_gb} GB",
                    file=sys.stderr,
                )
                return 2
            buf = io.BytesIO()
            bucket.download_file_by_name(key).save(buf)
            buf.seek(0)
            raw = pd.read_parquet(buf)
            frame = pd.DataFrame(
                {
                    "evt_block_time": pd.to_datetime(
                        raw["timestamp"], unit="s", utc=True
                    ),
                    **{
                        dest: raw[src]
                        for src, dest in B2_TO_TRAINING_COLS.items()
                    },
                }
            )[OUT_COLS]
            frame.to_csv(out_fh, index=False, header=(i == 0))
            total_rows += len(frame)
            if i % 20 == 0 or i == len(keys) - 1:
                size_gb = os.path.getsize(out_path) / 1e9
                print(
                    f"  [{i + 1}/{len(keys)}] {day}: {total_rows:,} rows, "
                    f"{size_gb:.2f} GB, {free_bytes(args.out_dir) / 1e9:.2f} GB free"
                )

    print(f"done: {total_rows:,} rows, {os.path.getsize(out_path) / 1e9:.2f} GB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
