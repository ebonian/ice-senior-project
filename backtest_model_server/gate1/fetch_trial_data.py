#!/usr/bin/env python3
"""Download the B2 daily parquets covering the T4/T5 trial windows.

    nix develop .#gate1 -c python backtest_model_server/gate1/fetch_trial_data.py

Writes to gate1/data/b2/<kind>/<YYYY-MM-DD>.parquet and is idempotent (skips
files already on disk). Default span 2026-05-11..2026-05-16 brackets both trial
windows with a day of margin on each side.
"""

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from engine.b2 import B2  # noqa: E402

GATE1 = Path(__file__).resolve().parent
OUT = GATE1 / "data" / "b2"
KINDS = ["swaps", "ohlcv", "mints", "burns", "state"]


def daterange(start: str, end: str):
    d0 = date.fromisoformat(start)
    d1 = date.fromisoformat(end)
    while d0 <= d1:
        yield d0.isoformat()
        d0 += timedelta(days=1)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-05-11")
    ap.add_argument("--end", default="2026-05-16")
    ap.add_argument("--kinds", default=",".join(KINDS))
    args = ap.parse_args()

    b2 = B2()
    kinds = [k.strip() for k in args.kinds.split(",") if k.strip()]
    total = 0
    for kind in kinds:
        for day in daterange(args.start, args.end):
            key = f"{b2.pool_prefix}/daily/{kind}/{day}.parquet"
            dest = OUT / kind / f"{day}.parquet"
            if dest.exists() and dest.stat().st_size > 0:
                print(f"  have {kind}/{day}  {dest.stat().st_size/1e6:.2f} MB")
                continue
            try:
                b2.download_to(key, dest)
                size = dest.stat().st_size
                total += size
                print(f"  got  {kind}/{day}  {size/1e6:.2f} MB")
            except Exception as e:
                print(f"  MISS {kind}/{day}: {e}")
    print(f"downloaded {total/1e6:.1f} MB new")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
