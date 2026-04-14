#!/usr/bin/env python3
"""
Concat all daily swap CSVs from downloaded_data_csv/daily/swaps into a single
swaps_YYYYMMDD_to_YYYYMMDD_eth_usdc_0p05.csv in simulation_13/training_data.

Output format matches simulation_12: evt_block_time, sqrtPriceX96, amount0, amount1, liquidity, tick.
"""

import os
import glob
import argparse

import pandas as pd

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SIM_DIR = os.path.normpath(os.path.join(SCRIPT_DIR, ".."))
REPO_ROOT = os.path.normpath(os.path.join(SCRIPT_DIR, "..", "..", ".."))

# Columns expected by prepare_hourly_data_extended (uniswap_v3_dqn_paper.py)
OUT_COLS = ["evt_block_time", "sqrtPriceX96", "amount0", "amount1", "liquidity", "tick"]


def main():
    parser = argparse.ArgumentParser(description="Concat daily swaps into sim13 training_data CSV")
    parser.add_argument(
        "--swaps-dir",
        default=os.path.join(REPO_ROOT, "downloaded_data_csv", "daily", "swaps"),
        help="Directory containing daily YYYY-MM-DD.csv swap files",
    )
    parser.add_argument(
        "--out-dir",
        default=os.path.join(SIM_DIR, "training_data"),
        help="Output directory for consolidated CSV",
    )
    parser.add_argument("--chunk-files", type=int, default=30, help="Number of daily files per chunk")
    args = parser.parse_args()

    files = sorted(glob.glob(os.path.join(args.swaps_dir, "*.csv")))
    if not files:
        raise FileNotFoundError(f"No CSV files in {args.swaps_dir}")

    # Date range from filenames (YYYY-MM-DD.csv)
    basenames = [os.path.basename(f).replace(".csv", "") for f in files]
    start_date = basenames[0].replace("-", "")
    end_date = basenames[-1].replace("-", "")
    out_name = f"swaps_{start_date}_to_{end_date}_eth_usdc_0p05.csv"
    out_path = os.path.join(args.out_dir, out_name)
    os.makedirs(args.out_dir, exist_ok=True)

    print(f"Input: {len(files)} files in {args.swaps_dir}")
    print(f"Output: {out_path}")
    print(f"Chunk size: {args.chunk_files} files")

    total_rows = 0
    for i in range(0, len(files), args.chunk_files):
        chunk_files = files[i : i + args.chunk_files]
        dfs = []
        for f in chunk_files:
            try:
                df = pd.read_csv(f, low_memory=False)
                # Normalize column names (downloaded uses timestamp, sqrt_price_x96)
                df.columns = [c.strip().lower().replace("-", "_") for c in df.columns]
                if "timestamp" in df.columns:
                    df["evt_block_time"] = pd.to_datetime(df["timestamp"], unit="s", utc=True)
                else:
                    raise ValueError(f"Missing 'timestamp' in {f}")
                if "sqrt_price_x96" in df.columns:
                    df["sqrtPriceX96"] = df["sqrt_price_x96"]
                elif "sqrtpricex96" in df.columns:
                    df["sqrtPriceX96"] = df["sqrtpricex96"]
                else:
                    raise ValueError(f"Missing sqrt_price_x96 in {f}")
                for c in ["amount0", "amount1", "liquidity", "tick"]:
                    if c not in df.columns:
                        raise ValueError(f"Missing '{c}' in {f}")
                dfs.append(df[OUT_COLS])
            except Exception as e:
                print(f"  Skip {os.path.basename(f)}: {e}")
                continue
        if not dfs:
            continue
        chunk_df = pd.concat(dfs, ignore_index=True)
        chunk_df = chunk_df.sort_values("evt_block_time")
        write_header = i == 0
        mode = "w" if i == 0 else "a"
        chunk_df.to_csv(out_path, index=False, header=write_header, mode=mode)
        total_rows += len(chunk_df)
        print(f"  Chunk {i // args.chunk_files + 1}: {len(chunk_df):,} rows (total {total_rows:,})")

    # Final sort of entire file not needed if chunks are sorted and appended in order
    print(f"Done. Total rows: {total_rows:,}")
    print(f"Saved: {out_path}")


if __name__ == "__main__":
    main()
