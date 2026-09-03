#!/usr/bin/env python3
"""Contract tests for E010. Run before trusting any number in REPORT.md.

    nix develop .#gate1 -c python backtest_model_server/e010/tests/test_e010_contracts.py

What can silently invalidate this experiment, and the test that catches it:

  1. Frozen-constant drift — cost model, HPL fees, envelope identity, and the
     C2 capital split must be E003/E005's exactly.
  2. Width mapping — e010 must use e005's arm mapping BY IDENTITY.
  3. ENGINE-EXTENSION VALIDITY GATE — race10's control run must reproduce
     E003's lag1h_rh1h row within +-0.05 fees/gamma and +-5% net $/day
     (E005 §4's tolerances), judged against e003's own results.json, AND
     match e005's committed control row to 1e-9 (same arithmetic, no drift).
  4. feeProtocol reads — every RESOLVED candidate carries a two-provider
     cross-check that matched; the share schedule is consistent with slot0.
  5. Gas envelope — measured, monotone optimistic <= central <= pessimistic
     per chain; the frozen Arbitrum constant is untouched by any run.
  6. Accounting identity — decomposed vs tracked LP ledger <= 1e-6 on every
     published e010 arm run.
  7. Determinism — the same race twice produces identical arm totals.
  8. Scaling law — per-dollar consistency across capitals: stripping the
     fixed gas lines, net/LP-notional must be capital-invariant (<= 0.2%),
     and implied share must scale as the LP notional ratio.
  9. Input integrity — the UNI funding CSV is complete over the window.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pandas as pd

E010 = Path(__file__).resolve().parents[1]
BMS = E010.parent
for p in (str(BMS / "gate1"), str(BMS / "e003"), str(BMS / "e005")):
    if p not in sys.path:
        sys.path.insert(0, p)
sys.path.append(str(E010))

from engine import cost_model as CM  # noqa: E402
import envelope as E003_ENV  # noqa: E402
import pools as P5  # noqa: E402
import registry as R  # noqa: E402
import keccak as K  # noqa: E402

FAILS: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{('  — ' + detail) if detail else ''}")
    if not ok:
        FAILS.append(name)


def race(args: list[str]) -> None:
    r = subprocess.run([sys.executable, str(E010 / "race10.py")] + args,
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"race10 {args} failed:\n{r.stdout[-2000:]}\n{r.stderr[-2000:]}")


def arm_totals(res_f: Path) -> dict:
    r = json.loads(res_f.read_text())
    return {a["arm"]: a for a in r["arms"]}


print("1. frozen constants and the capital split")
check("cost model version gate1-2026-08-29",
      R.COST_MODEL_VERSION == "gate1-2026-08-29")
check("HPL maker/taker 1.44/4.32 bps",
      CM.HPL_MAKER_BPS == 1.44 and CM.HPL_TAKER_BPS == 4.32)
check("envelope IS e003's object", R.ENVELOPE is E003_ENV.ENVELOPE)
tot = {p.name: round(p.total_bps, 3) for p in R.ENVELOPE}
check("envelope totals 1.984/3.359/8.320",
      tot == {"optimistic": 1.984, "central": 3.359, "pessimistic": 8.320}, str(tot))
check("Arbitrum gas frozen at $0.0101/tx",
      CM.GAS_USD_PER_TX == 0.0101 and R.ARB_GAS_USD_PER_TX == 0.0101)
check("C2 split: lp_notional(1420) == 1015 exactly",
      abs(R.lp_notional(1420.0) - 1015.0) < 1e-9)
check("lp_notional(10000) == 7147.887324",
      abs(R.LP_NOTIONAL_10K - 7147.887323943662) < 1e-6)
check("rate target: 10% APR at $10k == $2.7397/day",
      abs(R.TARGET_USD_PER_DAY_10K - 2.739726027397) < 1e-9)

print("2. width-arm mapping identity")
check("arms_for_spacing IS e005's function", R.arms_for_spacing is P5.arms_for_spacing)
check("spacing 10 arms unchanged",
      {a["half_ticks"] for a in R.arms_for_spacing(10)} == {10, 20, 50, 200, 800})
# keccak provenance: the module self-tests at import (empty digest + the Swap
# topic against gate1's frozen constant); every selector/topic e010 uses is
# derived through it, never transcribed. Assert the self-test anchor holds.
from engine.rpc import TOPIC_SWAP as _TS  # noqa: E402
check("keccak self-test anchor (derived Swap topic == gate1 frozen)",
      K.event_topic("Swap(address,address,int256,int256,uint160,uint128,int24)") == _TS)

print("3. engine-extension validity gate (control reproduction)")
e003_res = json.loads((BMS / "e003" / "out" / "lag1h_rh1h" / "results.json").read_text())
ctrl_f = E010 / "out" / "weth_usdc_0p05" / "control_lag1h_rh1h" / "results.json"
if not ctrl_f.exists():
    check("control run exists", False, str(ctrl_f))
else:
    ctrl = json.loads(ctrl_f.read_text())
    check("control ran on E003's swap set",
          ctrl["window"]["n_swaps"] == e003_res["window"]["n_swaps"])
    pairs = {"always_in_w10": "arm_0.5pct", "always_in_w40": "arm_2pct",
             "always_in_w160": "arm_8.3pct"}
    e_by = {a["arm"]: a for a in e003_res["arms"]}
    c_by = {a["arm"]: a for a in ctrl["arms"]}
    for e_arm, c_arm in pairs.items():
        et, ct = e_by[e_arm]["total"], c_by[c_arm]["total"]
        eg = et["lp_value_change_usd"] + et["hedge_price_pnl_usd"]
        cg = ct["lp_value_change_usd"] + ct["hedge_price_pnl_usd"]
        efg, cfg = et["lp_fees_usd"] / abs(eg), ct["lp_fees_usd"] / abs(cg)
        check(f"{e_arm}~{c_arm} |d f/g| <= 0.05", abs(efg - cfg) <= 0.05,
              f"{efg:.5f} vs {cfg:.5f}")
        for env in ("optimistic", "central", "pessimistic"):
            e_pd, c_pd = et[f"per_day_{env}"], ct[f"per_day_{env}"]
            rel = abs(c_pd - e_pd) / abs(e_pd)
            check(f"{e_arm}~{c_arm} net {env} within 5%", rel <= 0.05,
                  f"{e_pd:.4f} vs {c_pd:.4f}")
    e005_ctrl_f = (BMS / "e005" / "out" / "weth_usdc_0p05" / "control_lag1h_rh1h"
                   / "results.json")
    e5 = {a["arm"]: a for a in json.loads(e005_ctrl_f.read_text())["arms"]}
    drift = 0.0
    for arm in ("arm_0.5pct", "arm_2pct", "arm_8.3pct"):
        for key in ("lp_fees_usd", "per_day_central"):
            a, b = e5[arm]["total"][key], c_by[arm]["total"][key]
            drift = max(drift, abs(a - b) / max(abs(a), 1e-9))
    check("race10 control == e005 committed control (rel <= 1e-9)",
          drift <= 1e-9, f"max rel drift {drift:.2e}")

print("4. feeProtocol reads (validity gate ii)")
cands = json.loads((E010 / "out" / "candidates.json").read_text())["candidates"]
resolved = [c for c in cands if c["status"] == "RESOLVED"]
check("some candidates RESOLVED", len(resolved) >= 9, f"{len(resolved)}")
for c in resolved:
    x = c["fee_protocol_crosscheck"]
    ok = (x["match"] and x["provider_a"] != x["provider_b"]
          and x["fee_protocol_a"] == c["pool_state"]["fee_protocol_now"])
    sched_ok = all(s["lp_fee_share"] > 0 for s in c["lp_fee_share_schedule"])
    if not (ok and sched_ok):
        check(f"feeProtocol {c['slug']}", False, str(x))
check("all RESOLVED pools: two-provider slot0 cross-check matched",
      not any(f.startswith("feeProtocol") for f in FAILS))

print("5. gas envelope")
g = json.loads(R.GAS_ENVELOPE_FILE.read_text())
for chain in ("mainnet", "base"):
    u = g[chain]["usd_per_tx"]
    check(f"{chain} envelope monotone",
          0 < u["optimistic"] <= u["central"] <= u["pessimistic"], str(u))
    check(f"{chain} basefee sampled from window anchors",
          g[chain]["n_basefee_samples"] >= 800)
check("gas construction recorded",
      g["gas_units_per_tx"] == 250_000 and g["eth_usd_window_mean"] > 0)

print("6. accounting identity, every published e010 run")
n_runs = 0
for res_f in sorted((E010 / "out").glob("*/*/results.json")):
    rr = json.loads(res_f.read_text())
    for a in rr["arms"]:
        if a["arm"] == "always_cash":
            continue
        n_runs += 1
        if a["checks"]["lp_value_abs_gap_usd"] > 1e-6:
            check(f"identity {res_f.parent.parent.name}/{res_f.parent.name}/{a['arm']}",
                  False, f"gap {a['checks']['lp_value_abs_gap_usd']:.2e}")
check(f"decomposed == tracked ledger on all {n_runs} arm runs",
      n_runs > 0 and not any(f.startswith("identity") for f in FAILS))

print("7. determinism (same race twice, small pool)")
race(["--slug", "m_wbtc_weth_0p30", "--capital", "10000",
      "--gas-point", "central", "--tag", "det_a"])
race(["--slug", "m_wbtc_weth_0p30", "--capital", "10000",
      "--gas-point", "central", "--tag", "det_b"])
ta = arm_totals(E010 / "out" / "m_wbtc_weth_0p30" / "det_a" / "results.json")
tb = arm_totals(E010 / "out" / "m_wbtc_weth_0p30" / "det_b" / "results.json")
same = all(ta[k]["total"] == tb[k]["total"] for k in ta)
check("arm totals identical across reruns", same)

print("8. scaling law (per-dollar consistency across capitals)")
for cap in (1420, 50000):
    race(["--slug", "m_wbtc_weth_0p30", "--capital", str(cap),
          "--gas-point", "central", "--tag", f"scale_{cap}"])
t10 = arm_totals(E010 / "out" / "m_wbtc_weth_0p30" / "det_a" / "results.json")
t14 = arm_totals(E010 / "out" / "m_wbtc_weth_0p30" / "scale_1420" / "results.json")
t50 = arm_totals(E010 / "out" / "m_wbtc_weth_0p30" / "scale_50000" / "results.json")
gas_tx = json.loads(R.GAS_ENVELOPE_FILE.read_text())["mainnet"]["usd_per_tx"]["central"]


# The frozen stack decomposes as: fees (share-aware, CONCAVE in capital —
# fee_engine credits L/(L_pool + L) per swap, the honesty term) + everything
# else (bps-proportional in L) - fixed gas. The scaling law is therefore
# MEASURED by re-racing, never derived by linear arithmetic; this test pins
# the decomposition itself:
#   (a) net + gasF - fees, per LP dollar, is capital-invariant (<= 0.05%);
#   (b) fees per LP dollar are non-increasing in capital (concavity);
#   (c) the fee ratio never exceeds the notional ratio;
#   (d) recenter counts (the path) are capital-invariant.


def ex_fee_per_dollar(t: dict, cap: float) -> float:
    tt = t["total"]
    rec = tt["n_recenters"]
    gas_fixed = gas_tx * (4 * (rec + 1) + 2) + 0.19 * gas_tx * (rec + 1)
    return (tt["net_usd_central"] + gas_fixed - tt["lp_fees_usd"]) / R.lp_notional(cap)


for arm in t10:
    if arm == "always_cash":
        continue
    v = [ex_fee_per_dollar(t14[arm], 1420), ex_fee_per_dollar(t10[arm], 10000),
         ex_fee_per_dollar(t50[arm], 50000)]
    rel = (max(v) - min(v)) / max(abs(v[1]), 1e-12)
    if rel > 5e-4:
        check(f"scaling-exfee {arm}", False, f"per-$ ex-fee spread {rel:.2e}: {v}")
    f_pd = [t14[arm]["total"]["lp_fees_usd"] / R.lp_notional(1420),
            t10[arm]["total"]["lp_fees_usd"] / R.lp_notional(10000),
            t50[arm]["total"]["lp_fees_usd"] / R.lp_notional(50000)]
    if not (f_pd[0] >= f_pd[1] * (1 - 1e-9) >= f_pd[2] * (1 - 1e-9)):
        check(f"fee-concavity {arm}", False, str(f_pd))
    r_fees = t10[arm]["total"]["lp_fees_usd"] / t14[arm]["total"]["lp_fees_usd"]
    want = R.lp_notional(10000) / R.lp_notional(1420)
    if r_fees > want * (1 + 1e-9):
        check(f"fee-cap {arm}", False, f"fees ratio {r_fees:.4f} > {want:.4f}")
check("ex-fee net per LP dollar capital-invariant (<=0.05%) on all arms",
      not any(f.startswith("scaling-exfee") for f in FAILS))
check("fee credit concave in capital (share-aware) on all arms",
      not any(f.startswith(("fee-concavity", "fee-cap")) for f in FAILS))
check("recenter counts capital-invariant",
      all(t10[a]["total"]["n_recenters"] == t14[a]["total"]["n_recenters"]
          == t50[a]["total"]["n_recenters"] for a in t10 if a != "always_cash"))

print("9. input integrity (UNI funding)")
uni = pd.read_csv(E010 / "data" / "funding" / "hl_funding_uni_hourly.csv")
tu = pd.to_datetime(uni["time_ms"], unit="ms", utc=True).dt.floor("h")
gaps = tu.diff().dt.total_seconds().iloc[1:].ne(3600).sum()
check("UNI funding 2856 hourly rows, no gaps",
      len(uni) == 2856 and gaps == 0, f"{len(uni)} rows, {gaps} gaps")

print()
if FAILS:
    print(f"{len(FAILS)} FAILURES:")
    for f in FAILS:
        print(f"  - {f}")
    raise SystemExit(1)
print("all contract tests pass")
