#!/usr/bin/env python3
"""Archive HL UNI funding for the E010 window (e005/funding.py's recipe).

    nix develop .#gate1 -c python backtest_model_server/e010/funding_uni.py

The only funding series E010 needs beyond E005's committed CSVs: the UNI perp
(m_uni_weth_0p30's token0 leg). ETH / BTC / LINK funding and the ETHUSDT
marks are reused from e005/data bit-for-bit. Same output schema:
data/funding/hl_funding_uni_hourly.csv with (time_ms, funding_rate_hourly).
"""

from __future__ import annotations

import csv
import sys
import time
from pathlib import Path

import pandas as pd
import requests

E010 = Path(__file__).resolve().parent
sys.path.append(str(E010))
import registry as R  # noqa: E402

FUND_DIR = E010 / "data" / "funding"
START_MS = int(pd.Timestamp(R.WINDOW_START, tz="UTC").timestamp() * 1000)
END_MS = int(pd.Timestamp(R.WINDOW_END, tz="UTC").timestamp() * 1000)


def main() -> int:
    rows, t = [], START_MS
    while t < END_MS:
        r = requests.post("https://api.hyperliquid.xyz/info",
                          json={"type": "fundingHistory", "coin": "UNI",
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

    seen = {}
    for b in rows:
        seen[b["time"]] = b          # dedupe on timestamp, keep last
    rows = [seen[k] for k in sorted(seen)]
    hours_expected = (END_MS - START_MS) // 3_600_000
    ts = pd.to_datetime([b["time"] for b in rows], unit="ms", utc=True).floor("h")
    gaps = ts.to_series().diff().dt.total_seconds().iloc[1:].ne(3600).sum()
    if len(rows) != hours_expected or gaps:
        raise SystemExit(f"UNI funding incomplete: {len(rows)} rows "
                         f"(want {hours_expected}), {gaps} gaps")

    FUND_DIR.mkdir(parents=True, exist_ok=True)
    out = FUND_DIR / "hl_funding_uni_hourly.csv"
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["time_ms", "funding_rate_hourly", "premium"])
        for b in rows:
            w.writerow([b["time"], b["fundingRate"], b.get("premium", "")])
    print(f"wrote {out}: {len(rows)} rows, 0 gaps")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
