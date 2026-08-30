#!/usr/bin/env python3
"""Contract tests for E005. Run before trusting any number in REPORT.md.

    nix develop .#gate1 -c python backtest_model_server/e005/tests/test_e005_contracts.py

What can silently invalidate this experiment, and the test that catches it:

  1. Frozen-constant drift — E005 must use gate1's cost model and E003's
     envelope unchanged (identity AND values).
  2. Width mapping — the percentage arms must reproduce E003's W10/W40/W160
     exactly on the control's spacing, or the control comparison is about
     nothing.
  3. ENGINE-EXTENSION VALIDITY GATE — the generalized simulator must
     reproduce E003's lag1h_rh1h control row within +-0.05 on fees/gamma and
     +-5% on net $/day at the matching arms, judged against e003's own
     results.json, not a transcription.
  4. Accounting identity — per arm, the decomposed LP P&L must equal the
     directly-tracked cumulative ledger.
  5. Input integrity — funding/marks CSVs complete over the window; the HL
     ETH series must equal the bot repo's recorded series (E003's input).
  6. Selector provenance — keccak self-test (import-time) plus the derived
     Swap topic against gate1's frozen constant.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

E005 = Path(__file__).resolve().parents[1]
BMS = E005.parent
sys.path.insert(0, str(BMS / "gate1"))
sys.path.insert(0, str(BMS / "e003"))
sys.path.insert(0, str(E005))

from engine import cost_model as CM  # noqa: E402
import envelope as E003_ENV  # noqa: E402
import pools as P  # noqa: E402
import keccak as K  # noqa: E402
from engine.rpc import TOPIC_SWAP  # noqa: E402

FAILS: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{('  — ' + detail) if detail else ''}")
    if not ok:
        FAILS.append(name)


print("1. frozen constants")
check("cost model version is gate1-2026-08-29",
      CM.COST_MODEL_VERSION == "gate1-2026-08-29")
check("HPL maker/taker 1.44/4.32 bps",
      CM.HPL_MAKER_BPS == 1.44 and CM.HPL_TAKER_BPS == 4.32)
check("envelope version is e003-2026-08-29",
      P.ENVELOPE_VERSION == "e003-2026-08-29")
check("E005 envelope IS e003's object, not a copy",
      P.ENVELOPE is E003_ENV.ENVELOPE)
tot = {p.name: round(p.total_bps, 3) for p in P.ENVELOPE}
check("envelope totals 1.984 / 3.359 / 8.320 bps",
      tot == {"optimistic": 1.984, "central": 3.359, "pessimistic": 8.320},
      str(tot))
check("central maker share is the notional-weighted 64.63% (E002 F5)",
      abs(P.ENVELOPE_BY_NAME["central"].maker_share_notional - 0.6463) < 1e-12)
check("LP capital / hedge equity / target frozen at E003's values",
      (P.LP_CAPITAL_USD, P.HEDGE_EQUITY_USD, round(P.TARGET_USD_PER_DAY, 4))
      == (1015.0, 405.0, 0.389))

print("2. width-arm mapping")
arms10 = {a["half_ticks"] for a in P.arms_for_spacing(10)}
check("spacing 10 arms = E003's W2/W4/W10/W40/W160 half-ticks",
      arms10 == {10, 20, 50, 200, 800}, str(sorted(arms10)))
arms1 = {a["half_ticks"] for a in P.arms_for_spacing(1)}
check("spacing 1 arms exact-percentage half-ticks",
      arms1 == {10, 20, 50, 198, 797}, str(sorted(arms1)))
arms60 = P.arms_for_spacing(60)
check("spacing 60 arms dedupe to 3 with merged labels",
      [a["half_ticks"] for a in arms60] == [60, 180, 780]
      and arms60[0]["target_pcts"] == [0.001, 0.002, 0.005])
check("every arm half-width is a whole multiple of its spacing",
      all(a["half_ticks"] % sp == 0
          for sp in (1, 10, 60, 200) for a in P.arms_for_spacing(sp)))

print("3. engine-extension validity gate (control reproduction)")
e003_res = json.loads((BMS / "e003" / "out" / "lag1h_rh1h" / "results.json").read_text())
ctrl_f = E005 / "out" / "weth_usdc_0p05" / "control_lag1h_rh1h" / "results.json"
if not ctrl_f.exists():
    check("control run exists", False, str(ctrl_f))
else:
    ctrl = json.loads(ctrl_f.read_text())
    check("control ran on E003's swap window",
          ctrl["window"]["n_swaps"] == e003_res["window"]["n_swaps"],
          f"{ctrl['window']['n_swaps']} vs {e003_res['window']['n_swaps']}")
    pairs = {"always_in_w10": "arm_0.5pct", "always_in_w40": "arm_2pct",
             "always_in_w160": "arm_8.3pct"}
    e_by = {a["arm"]: a for a in e003_res["arms"]}
    c_by = {a["arm"]: a for a in ctrl["arms"]}
    for e_arm, c_arm in pairs.items():
        et, ct = e_by[e_arm]["total"], c_by[c_arm]["total"]
        eg = et["lp_value_change_usd"] + et["hedge_price_pnl_usd"]
        cg = ct["lp_value_change_usd"] + ct["hedge_price_pnl_usd"]
        efg, cfg = et["lp_fees_usd"] / abs(eg), ct["lp_fees_usd"] / abs(cg)
        check(f"{e_arm} ~ {c_arm}: |d fees/gamma| <= 0.05",
              abs(efg - cfg) <= 0.05, f"{efg:.5f} vs {cfg:.5f}")
        for env in ("optimistic", "central", "pessimistic"):
            e_pd, c_pd = et[f"per_day_{env}"], ct[f"per_day_{env}"]
            rel = abs(c_pd - e_pd) / abs(e_pd)
            check(f"{e_arm} ~ {c_arm}: net $/day {env} within 5%",
                  rel <= 0.05, f"{e_pd:.4f} vs {c_pd:.4f} (rel {rel:.2%})")

print("4. accounting identity, every published run")
n_runs = 0
for res_f in sorted((E005 / "out").glob("*/*/results.json")):
    r = json.loads(res_f.read_text())
    for a in r["arms"]:
        if a["arm"] == "always_cash":
            continue
        n_runs += 1
        gap = a["checks"]["lp_value_abs_gap_usd"]
        if gap > 1e-6:
            check(f"identity {res_f.parent.parent.name}/{res_f.parent.name}/{a['arm']}",
                  False, f"gap {gap:.2e}")
        mh = a["checks"]["months_sum_minus_total_hours"]
        if mh > 1e-6:
            check(f"month-hours {res_f.parent.name}/{a['arm']}", False, f"{mh:.2e}")
check(f"decomposed == tracked ledger on all {n_runs} arm runs (gap <= 1e-6)",
      n_runs > 0 and not any(f.startswith("identity") for f in FAILS))

print("5. input integrity")
hours_expected = 2856
for f in sorted((E005 / "data" / "funding").glob("*.csv")):
    df = pd.read_csv(f)
    t = pd.to_datetime(df["time_ms"], unit="ms", utc=True).dt.floor("h")
    gaps = t.diff().dt.total_seconds().iloc[1:].ne(3600).sum()
    check(f"{f.name}: {hours_expected} rows, no gaps",
          len(df) == hours_expected and gaps == 0, f"{len(df)} rows, {gaps} gaps")
for f in sorted((E005 / "data" / "marks").glob("*.csv")):
    df = pd.read_csv(f)
    check(f"{f.name}: {hours_expected} hourly rows",
          len(df) == hours_expected, f"{len(df)}")
bot = pd.read_csv("/home/poon/developments/llaminet/bot/analysis/strategy-review/"
                  "data/hl_funding_eth_hourly.csv")
ours = pd.read_csv(E005 / "data" / "funding" / "hl_funding_eth_hourly.csv")
bot["h"] = pd.to_datetime(bot["time_ms"], unit="ms", utc=True).dt.floor("h")
ours["h"] = pd.to_datetime(ours["time_ms"], unit="ms", utc=True).dt.floor("h")
m = ours.merge(bot, on="h", suffixes=("_a", "_b"))
d = (pd.to_numeric(m["funding_rate_hourly_a"])
     - pd.to_numeric(m["funding_rate_hourly_b"])).abs().max()
check("HL-API ETH funding == bot repo's recorded series on overlap",
      len(m) == hours_expected and d == 0.0, f"{len(m)} h, max diff {d:.1e}")

print("6. selector provenance")
check("derived Swap topic == gate1 frozen TOPIC_SWAP",
      K.event_topic("Swap(address,address,int256,int256,uint160,uint128,int24)")
      == TOPIC_SWAP)

print()
if FAILS:
    print(f"{len(FAILS)} FAILURES:")
    for f in FAILS:
        print(f"  - {f}")
    raise SystemExit(1)
print("all contract tests pass")
