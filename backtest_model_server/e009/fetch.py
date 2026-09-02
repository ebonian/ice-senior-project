#!/usr/bin/env python3
"""E009 fetch recipe — archive the long funding histories the experiment needs.

    nix develop .#gate1 -c python backtest_model_server/e009/fetch.py

Sources (pre-registered, E009-funding-persistence.md §Method):
  1. Hyperliquid `fundingHistory` for ETH, full available history
     (earliest record 2023-05-12T00:00Z) → data/hl_funding_eth_hourly_long.csv
  2. Binance USDT-margined ETHUSDT funding (8h) from 2020-03-01
     → data/binance_ethusdt_funding_8h.csv        (descriptive proxy only)
  3. Binance ETHUSDT daily klines from 2020-03-01
     → data/binance_ethusdt_1d.csv                (regime classification)

The fetch END boundary is frozen at 2026-09-03T00:00Z so re-runs are
reproducible; every request is bounded and the total payload is ~2 MB.
Cached: an existing complete CSV is not re-fetched (delete to force).
"""

from __future__ import annotations

import csv
import json
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

E009 = Path(__file__).resolve().parent
DATA = E009 / "data"

# Frozen window boundaries (pre-registered).
HL_START_MS = int(datetime(2023, 5, 1, tzinfo=timezone.utc).timestamp() * 1000)
BINANCE_START_MS = int(datetime(2020, 3, 1, tzinfo=timezone.utc).timestamp() * 1000)
END_MS = int(datetime(2026, 9, 3, tzinfo=timezone.utc).timestamp() * 1000)


def _iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()


def _post_json(url: str, payload: dict) -> object:
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def _get_json(url: str) -> object:
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.loads(r.read())


def fetch_hl_funding() -> Path:
    out = DATA / "hl_funding_eth_hourly_long.csv"
    if out.exists():
        print(f"[HL ETH] cached {sum(1 for _ in open(out)) - 1} rows")
        return out
    rows, t = [], HL_START_MS
    while t < END_MS:
        batch = _post_json("https://api.hyperliquid.xyz/info",
                           {"type": "fundingHistory", "coin": "ETH",
                            "startTime": t, "endTime": END_MS - 1})
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
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["time_ms", "iso_utc", "funding_rate_hourly", "premium"])
        for b in rows:
            w.writerow([b["time"], _iso(b["time"]), b["fundingRate"],
                        b.get("premium", "")])
    print(f"[HL ETH] {len(rows)} rows -> {out.name}")
    return out


def fetch_binance_funding() -> Path:
    out = DATA / "binance_ethusdt_funding_8h.csv"
    if out.exists():
        print(f"[Binance funding] cached {sum(1 for _ in open(out)) - 1} rows")
        return out
    rows, t = [], BINANCE_START_MS
    while t < END_MS:
        batch = _get_json("https://fapi.binance.com/fapi/v1/fundingRate"
                          f"?symbol=ETHUSDT&startTime={t}&endTime={END_MS - 1}"
                          "&limit=1000")
        if not batch:
            break
        rows.extend(b for b in batch if b["fundingTime"] < END_MS)
        nt = batch[-1]["fundingTime"] + 1
        if nt <= t:
            break
        t = nt
        time.sleep(0.2)
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["funding_time_ms", "iso_utc", "funding_rate_8h", "mark_price"])
        for b in rows:
            w.writerow([b["fundingTime"], _iso(b["fundingTime"]),
                        b["fundingRate"], b.get("markPrice", "")])
    print(f"[Binance funding] {len(rows)} rows -> {out.name}")
    return out


def fetch_binance_daily() -> Path:
    out = DATA / "binance_ethusdt_1d.csv"
    if out.exists():
        print(f"[Binance 1d] cached {sum(1 for _ in open(out)) - 1} rows")
        return out
    rows, t = [], BINANCE_START_MS
    while t < END_MS:
        batch = _get_json("https://api.binance.com/api/v3/klines"
                          f"?symbol=ETHUSDT&interval=1d&startTime={t}"
                          f"&endTime={END_MS - 1}&limit=1000")
        if not batch:
            break
        rows.extend(k for k in batch if k[0] < END_MS)
        t = batch[-1][0] + 86_400_000
        time.sleep(0.2)
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["open_time_ms", "iso_utc", "open", "close"])
        for k in rows:
            w.writerow([k[0], _iso(k[0]), k[1], k[4]])
    print(f"[Binance 1d] {len(rows)} rows -> {out.name}")
    return out


def main() -> int:
    DATA.mkdir(parents=True, exist_ok=True)
    fetch_hl_funding()
    fetch_binance_funding()
    fetch_binance_daily()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
