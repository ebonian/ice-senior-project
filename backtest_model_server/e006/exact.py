#!/usr/bin/env python3
"""E006 stage 2 — exact simulation of the DP-selected timing policy.

    nix develop .#gate1 -c python backtest_model_server/e006/exact.py

Stage 1's DP picks held-hour streaks under per-hour payoffs that deliberately
over-credit (see oracle.py's docstring). This stage re-simulates the CENTRAL
point's chosen streaks exactly, through E003's own `run_arm` unmodified:

  - fresh mint at the streak's first swap (entry swap + mint-path txs + hedge
    open, exactly as E003 charges its window entry),
  - the standard lag1h_rh1h loop inside the streak — hourly rehedges, hourly
    funding, breach recenters held to the next hour boundary,
  - burn + swap-back + hedge flatten at the streak's end (E003's window exit).

Out-of-position hours are cash: no fees, no funding, no costs. The policy is
simulated once and priced at all three envelope points afterwards, so no
envelope point can change behaviour (E003's rule). The verdict reads CENTRAL.

$/day is the total over the FULL 119-day window — cash hours are part of the
policy, not a denominator trick.

Reusing `run_arm` also makes the switch-cost→infinity contract literal: a
single streak spanning the whole window IS E003's `always_in` run, and
tests/test_e006_contracts.py asserts the reproduction is exact.

Outputs: out/stage2_results.json, out/stage2_streaks_w<W>.csv.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd

E006 = Path(__file__).resolve().parent
BMS = E006.parent
for p in (BMS / "gate1", BMS / "e003", E006):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
from engine import cost_model as CM   # noqa: E402
import envelope as ENV                 # noqa: E402
import race                            # noqa: E402
import oracle                          # noqa: E402

BUCKET_FIELDS = [f for f in race.Bucket.__dataclass_fields__ if f != "label"]


def simulate_streak(width: int, swaps: pd.DataFrame, funding: dict,
                    t_from: int, t_to: int):
    """Run E003's `run_arm` (lag1h_rh1h, constant notional) on the swap slice
    [t_from, t_to). Hour grids are built exactly as e003/race.py main() builds
    them, so a slice spanning the whole window reproduces E003's run bit for
    bit."""
    ts_all = swaps["timestamp"].to_numpy(np.int64)
    a = int(np.searchsorted(ts_all, t_from, side="left"))
    b = int(np.searchsorted(ts_all, t_to, side="left"))
    sub = swaps.iloc[a:b].reset_index(drop=True)
    if len(sub) < 2:
        return None
    tse = sub["timestamp"].to_numpy(np.int64)
    h0 = (int(tse[0]) // 3600 + 1) * 3600
    h1 = (int(tse[-1]) // 3600) * 3600
    hour_ts = np.arange(h0, h1 + 1, 3600, dtype=np.int64)
    hour_idx = np.searchsorted(tse, hour_ts, side="right") - 1
    hour_px = np.where(hour_idx >= 0,
                       sub["price"].to_numpy()[np.clip(hour_idx, 0, None)], np.nan)
    return race.run_arm(width, sub, funding, hour_ts, hour_px, hour_idx,
                        detect_lag_hours=1, rehedge_hours=1,
                        lp_capital=ENV.LP_CAPITAL_USD, notional_mode="constant",
                        keep_cycles=False)


def add_bucket(dst: dict, b) -> None:
    for f in BUCKET_FIELDS:
        dst[f] = dst.get(f, 0.0) + getattr(b, f)


def net_usd(tot: dict, point) -> float:
    return (tot["lp_value_change_usd"] + tot["lp_fees_usd"]
            - tot["onchain_cost_usd"] + tot["hedge_price_pnl_usd"]
            + tot["funding_usd"] - point.cost(tot["rehedge_notional_usd"]))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-05-01")
    ap.add_argument("--end", default="2026-08-28")
    args = ap.parse_args()

    out_dir = E006 / "out"
    stage1 = json.loads((out_dir / "stage1_results.json").read_text())
    swaps = race.load_swaps(args.start, args.end)
    funding = race.load_funding()
    days = stage1["window"]["days"]

    payload = {
        "experiment": "E006", "stage": 2,
        "cost_model_version": CM.COST_MODEL_VERSION,
        "envelope_version": ENV.E003_ENVELOPE_VERSION,
        "window": stage1["window"],
        "policy": "stage-1 DP selection at the CENTRAL envelope point, "
                  "re-simulated exactly (lag1h_rh1h inside streaks, cash outside); "
                  "priced at all three points afterwards",
        "arms": {},
    }

    for key, arm in stage1["arms"].items():
        w = arm["width"]
        t0 = time.time()
        hours = pd.read_csv(out_dir / f"stage1_hours_w{w}.csv")
        held = hours["held_central"].to_numpy(bool)
        hs = hours["hour_epoch"].to_numpy(np.int64)

        runs = oracle.streaks_of(held)
        total: dict = {}
        months: dict[str, dict] = {}
        rows = []
        max_gap = 0.0
        for (i, j) in runs:
            r = simulate_streak(w, swaps, funding, int(hs[i]), int(hs[j]) + 3600)
            if r is None:
                continue
            add_bucket(total, r.total)
            for lab, b in r.months.items():
                months.setdefault(lab, {})
                add_bucket(months[lab], b)
            gap = r.checks["lp_value_abs_gap_usd"]
            max_gap = max(max_gap, gap)
            rows.append({
                "start_utc": str(pd.Timestamp(int(hs[i]), unit="s", tz="UTC")),
                "end_utc": str(pd.Timestamp(int(hs[j]) + 3600, unit="s", tz="UTC")),
                "hours": r.total.hours,
                "n_recenters": r.total.n_recenters,
                "lp_fees_usd": r.total.lp_fees_usd,
                "funding_usd": r.total.funding_usd,
                "onchain_cost_usd": r.total.onchain_cost_usd,
                "rehedge_notional_usd": r.total.rehedge_notional_usd,
                "net_central_usd": r.total.net_usd(ENV.ENVELOPE_BY_NAME["central"]),
                "lp_value_abs_gap_usd": gap,
            })
        pd.DataFrame(rows).to_csv(out_dir / f"stage2_streaks_w{w}.csv", index=False)

        pts = {}
        for point in ENV.ENVELOPE:
            v = net_usd(total, point) if total else 0.0
            pts[point.name] = {"net_usd": v, "per_day_usd": v / days}
        s1_central = arm["points"]["central"]["value_usd"]
        payload["arms"][key] = {
            "width": w, "width_pct": arm["width_pct"],
            "n_streaks_selected": len(runs),
            "n_streaks_simulated": len(rows),
            "held_hours_simulated": total.get("hours", 0.0),
            "held_frac": total.get("hours", 0.0) / (days * 24.0),
            "max_lp_value_abs_gap_usd": max_gap,
            "points": pts,
            "stage1_central_usd": s1_central,
            "stage2_over_stage1_central":
                (pts["central"]["net_usd"] / s1_central) if s1_central else None,
            "total": total,
            "months": {k: {**months[k],
                           "net_central_usd": net_usd(months[k],
                                                      ENV.ENVELOPE_BY_NAME["central"])}
                       for k in sorted(months)},
        }
        print(f"W{w:<4d} exact central ${pts['central']['net_usd']:+.2f} "
              f"(${pts['central']['per_day_usd']:+.3f}/day) over {len(rows)} streaks, "
              f"{total.get('hours', 0.0):.0f}h held, "
              f"retains {payload['arms'][key]['stage2_over_stage1_central'] if s1_central else float('nan'):.1%} "
              f"of stage-1, max gap {max_gap:.2e}  {time.time()-t0:.0f}s")

    best = max(payload["arms"].values(),
               key=lambda a: a["points"]["central"]["per_day_usd"])
    payload["best_arm_central"] = f"w{best['width']}"
    (out_dir / "stage2_results.json").write_text(json.dumps(payload, indent=2))
    print(f"wrote {out_dir/'stage2_results.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
