#!/usr/bin/env python3
"""Archive Hyperliquid funding and Binance USD marks for every perp E005 needs.

    nix develop .#gate1 -c python backtest_model_server/e005/funding.py

Funding is replayed, never modelled (cost model docstring). The recorded
series are committed as CSVs under `data/funding/` and `data/marks/` so every
number in the report is re-derivable without the APIs.

The ETH funding series is cross-checked against the bot repo's recorded CSV
(`hl_funding_eth_hourly.csv`, the E003 input): the two must agree on their
overlap or neither can be trusted.
"""

from __future__ import annotations

import csv
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

E005 = Path(__file__).resolve().parent
sys.path.insert(0, str(E005))
import pools as P  # noqa: E402

FUND_DIR = E005 / "data" / "funding"
MARK_DIR = E005 / "data" / "marks"
BOT_ETH_CSV = Path("/home/poon/developments/llaminet/bot/analysis/strategy-review/"
                   "data/hl_funding_eth_hourly.csv")

HL_COINS = ["ETH", "BTC", "ARB", "PENDLE", "LINK"]
BINANCE_SYMBOLS = ["ETHUSDT", "BTCUSDT", "ARBUSDT", "LINKUSDT"]

START_MS = int(pd.Timestamp(P.WINDOW_START, tz="UTC").timestamp() * 1000)
END_MS = int(pd.Timestamp(P.WINDOW_END, tz="UTC").timestamp() * 1000)


def fetch_hl_funding(coin: str) -> list[dict]:
    rows, t = [], START_MS
    while t < END_MS:
        r = requests.post("https://api.hyperliquid.xyz/info",
                          json={"type": "fundingHistory", "coin": coin,
                                "startTime": t, "endTime": END_MS - 1},
                          timeout=30)
        r.raise_for_status()
        batch = r.json()
        if not batch:
            break
        for b in batch:
            if b["time"] < END_MS:
                rows.append(b)
        nt = batch[-1]["time"] + 1
        if nt <= t:
            break
        t = nt
        time.sleep(0.25)
    return rows


def write_funding(coin: str, rows: list[dict]) -> Path:
    out = FUND_DIR / f"hl_funding_{coin.lower()}_hourly.csv"
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["time_ms", "iso_utc", "funding_rate_hourly", "premium"])
        for b in rows:
            iso = datetime.fromtimestamp(b["time"] / 1000, tz=timezone.utc).isoformat()
            w.writerow([b["time"], iso, b["fundingRate"], b.get("premium", "")])
    return out


def fetch_binance(symbol: str) -> Path:
    rows, t = [], START_MS
    while t < END_MS:
        r = requests.get("https://api.binance.com/api/v3/klines",
                         params={"symbol": symbol, "interval": "1h",
                                 "startTime": t, "endTime": END_MS - 1,
                                 "limit": 1000},
                         timeout=30)
        r.raise_for_status()
        batch = r.json()
        if not batch:
            break
        rows.extend(batch)
        t = batch[-1][0] + 3_600_000
        time.sleep(0.2)
    out = MARK_DIR / f"binance_{symbol.lower()}_1h.csv"
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["open_time_ms", "iso_utc", "open", "close"])
        for k in rows:
            iso = datetime.fromtimestamp(k[0] / 1000, tz=timezone.utc).isoformat()
            w.writerow([k[0], iso, k[1], k[4]])
    return out


def main() -> int:
    FUND_DIR.mkdir(parents=True, exist_ok=True)
    MARK_DIR.mkdir(parents=True, exist_ok=True)
    expected_hours = (END_MS - START_MS) // 3_600_000

    for coin in HL_COINS:
        out = FUND_DIR / f"hl_funding_{coin.lower()}_hourly.csv"
        if out.exists():
            n = sum(1 for _ in open(out)) - 1
            print(f"[{coin}] cached {n}/{expected_hours} rows")
            continue
        rows = fetch_hl_funding(coin)
        write_funding(coin, rows)
        print(f"[{coin}] {len(rows)}/{expected_hours} funding rows -> {out.name}")

    for sym in BINANCE_SYMBOLS:
        out = MARK_DIR / f"binance_{sym.lower()}_1h.csv"
        if out.exists():
            n = sum(1 for _ in open(out)) - 1
            print(f"[{sym}] cached {n}/{expected_hours} rows")
            continue
        p = fetch_binance(sym)
        n = sum(1 for _ in open(p)) - 1
        print(f"[{sym}] {n}/{expected_hours} klines -> {p.name}")

    # cross-check ETH funding against the bot repo's recorded series
    ours = pd.read_csv(FUND_DIR / "hl_funding_eth_hourly.csv")
    bot = pd.read_csv(BOT_ETH_CSV)
    for df in (ours, bot):
        df["hour"] = pd.to_datetime(df["time_ms"], unit="ms", utc=True).dt.floor("h")
    m = ours.merge(bot, on="hour", suffixes=("_e005", "_bot"))
    diff = (pd.to_numeric(m["funding_rate_hourly_e005"])
            - pd.to_numeric(m["funding_rate_hourly_bot"])).abs()
    print(f"ETH funding vs bot CSV: {len(m)} overlapping hours, "
          f"max abs diff {diff.max():.2e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
