#!/usr/bin/env python3
"""E007 — fetch + reduce Binance ETHUSDT 1m klines (candidate C4's input).

    nix develop .#gate1 -c python backtest_model_server/e007/fetch_binance.py \
        [--zip-dir DIR]

Source: https://data.binance.vision monthly zips
`data/spot/monthly/klines/ETHUSDT/1m/ETHUSDT-1m-<YYYY-MM>.zip` for 2026-04
(warmup tail only) through 2026-07, and daily zips
`data/spot/daily/klines/ETHUSDT/1m/ETHUSDT-1m-2026-08-<DD>.zip` for
2026-08-01..27 (the monthly 2026-08 dump was not yet published on the run
date 2026-09-02). Binance lists no ETH/USDC spot pair; ETHUSDT is the
off-chain reference, as everywhere in this project.

Reduced to (open_time_s, close, n_trades), trimmed to
[2026-04-30 00:00, 2026-08-28 00:00) UTC, and committed as
`data/binance_ethusdt_1m.csv.gz` — the from-scratch rederivation recipe is
this script. `open_time` auto-detects ms vs us epoch; header rows in newer
dumps are skipped.

With --zip-dir the zips are read from disk instead of fetched (used on the
run date; the URLs above are the recipe).
"""

from __future__ import annotations

import argparse
import csv
import gzip
import io
import urllib.request
import zipfile
from pathlib import Path

E007 = Path(__file__).resolve().parent
BASE = "https://data.binance.vision/data/spot"
MONTHLIES = ["2026-04", "2026-05", "2026-06", "2026-07"]
AUG_DAYS = [f"2026-08-{d:02d}" for d in range(1, 28)]
T_LO = 1777507200   # 2026-04-30 00:00:00 UTC
T_HI = 1787875200   # 2026-08-28 00:00:00 UTC


def zip_names() -> list[tuple[str, str]]:
    out = [(f"ETHUSDT-1m-{m}.zip", f"{BASE}/monthly/klines/ETHUSDT/1m/ETHUSDT-1m-{m}.zip")
           for m in MONTHLIES]
    out += [(f"ETHUSDT-1m-{d}.zip", f"{BASE}/daily/klines/ETHUSDT/1m/ETHUSDT-1m-{d}.zip")
            for d in AUG_DAYS]
    return out


def rows_from_zip(blob: bytes):
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        name = z.namelist()[0]
        text = z.read(name).decode()
    for line in csv.reader(io.StringIO(text)):
        if not line or not line[0].strip().lstrip("-").isdigit():
            continue        # header row in newer dumps
        t = int(line[0])
        if t > 10**15:      # microseconds
            t //= 10**6
        elif t > 10**12:    # milliseconds
            t //= 10**3
        yield t, line[4], line[8]   # open_time_s, close, n_trades


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--zip-dir", type=Path, default=None,
                    help="read pre-downloaded zips from here instead of fetching")
    args = ap.parse_args()

    rows: list[tuple[int, str, str]] = []
    for fname, url in zip_names():
        if args.zip_dir:
            cands = [args.zip_dir / fname, args.zip_dir / "aug" / fname]
            path = next((c for c in cands if c.exists()), None)
            if path is None:
                raise FileNotFoundError(fname)
            blob = path.read_bytes()
        else:
            blob = urllib.request.urlopen(url, timeout=120).read()
        n0 = len(rows)
        rows.extend(r for r in rows_from_zip(blob) if T_LO <= r[0] < T_HI)
        print(f"{fname}: kept {len(rows) - n0} rows")

    rows.sort(key=lambda r: r[0])
    dedup = [r for i, r in enumerate(rows) if i == 0 or r[0] != rows[i - 1][0]]
    out = E007 / "data" / "binance_ethusdt_1m.csv.gz"
    out.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(out, "wt", newline="") as f:
        w = csv.writer(f)
        w.writerow(["open_time_s", "close", "n_trades"])
        w.writerows(dedup)
    span = (dedup[0][0], dedup[-1][0])
    print(f"wrote {out}: {len(dedup)} rows, {span[0]}..{span[1]} "
          f"({(span[1]-span[0])/60 + 1:.0f} minutes nominal)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
