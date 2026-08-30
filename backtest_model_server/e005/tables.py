#!/usr/bin/env python3
"""E005 tables + the pre-registered decision rule, as a program.

    nix develop .#gate1 -c python backtest_model_server/e005/tables.py

Reads out/candidates.json, out/coverage.json and every
out/<slug>/lag1h_rh1h/results.json; emits every table REPORT.md quotes and
evaluates the decision rule EXACTLY as pre-registered in
loop/experiments/E005-pool-screen.md:

  SUPPORTED    >= 1 eligible pool x arm passes ALL of
               (a) fees/gamma >= 1.5, full window
               (b) fees/gamma > 1.0 in every calendar month
               (c) net central >= +$0.389/day ($1,420 capital, full stack)
               (d) implied in-range liquidity share <= 1%
               (e) no month's swap count < 25% of the pool's peak month
  REFUTED      no eligible pool reaches fees/gamma >= 1.0 full-window
  INCONCLUSIVE anything between — each watchlist pool named with the gates
               it failed

Writes out/decision.json and out/tables.md.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

E005 = Path(__file__).resolve().parent
sys.path.insert(0, str(E005))
import pools as P  # noqa: E402

PRIMARY_TAG = "lag1h_rh1h"
CONTROL_TAG = "control_lag1h_rh1h"


def fg(t: dict) -> float:
    g = t["lp_value_change_usd"] + t["hedge_price_pnl_usd"]
    return t["lp_fees_usd"] / abs(g) if g else float("nan")


def gamma(t: dict) -> float:
    return t["lp_value_change_usd"] + t["hedge_price_pnl_usd"]


def load_all():
    cands = json.loads((E005 / "out" / "candidates.json").read_text())
    cov = json.loads((E005 / "out" / "coverage.json").read_text())
    races = {}
    for slug_dir in sorted((E005 / "out").iterdir()):
        if not slug_dir.is_dir():
            continue
        for tag in (PRIMARY_TAG, CONTROL_TAG, "lag1h_rh0h", "control_lag1h_rhrec"):
            f = slug_dir / tag / "results.json"
            if f.exists():
                races.setdefault(slug_dir.name, {})[tag] = json.loads(f.read_text())
    return cands, cov, races


def eligibility_rows(cands, cov):
    rows = []
    for c in cands["candidates"]:
        slug = c["slug"]
        row = {"slug": slug, "family": c["family"], "pair": c["pair"],
               "fee_pct": c["fee"] / 1e4, "address": c.get("address")}
        if c["status"] == "NO-POOL":
            row["screen"] = "NO-POOL"
        elif c["status"] == "NO-PERP":
            row["screen"] = "NO-PERP"
        else:
            pc = cov["pools"].get(slug)
            if slug == "weth_usdc_0p05":
                # control: data + coverage are E003's own, verified there
                row["screen"] = "RACED (control, e003 data)"
                row["median_swaps_per_day"] = 28857  # 3,434,113 / 119, e003
                row["lp_fee_share"] = c["lp_fee_share_schedule"][0]["lp_fee_share"]
                rows.append(row)
                continue
            if pc is None:
                row["screen"] = "NOT-FETCHED"
            elif pc["data_status"] == "DATA-FAIL":
                row["screen"] = "DATA-FAIL"
            elif not pc["daily"]["eligible_median_ge_48"]:
                row["screen"] = "INELIGIBLE-thin"
            else:
                row["screen"] = "RACED"
            if pc:
                row["median_swaps_per_day"] = pc["daily"]["median_swaps_per_day"]
                row["monthly_swap_counts"] = pc["daily"]["monthly_swap_counts"]
            row["lp_fee_share"] = c["lp_fee_share_schedule"][0]["lp_fee_share"]
        rows.append(row)
    listed_addrs = {r.get("address") for r in rows if r.get("address")}
    for d in cands["discovery"]:
        if d.get("address") in listed_addrs:
            continue   # chosen pools already have a full candidate row
        if d["status"] in ("SAMPLED-NOT-CHOSEN", "NO-POOL", "NO-PERP"):
            rows.append({"slug": f"{d['token'].lower()}_{d['quote'].lower()}_"
                                 f"{'0p05' if d['fee'] == 500 else '0p30'}",
                         "family": "F4-shortlist", "pair": f"{d['token']}/{d['quote']}",
                         "fee_pct": d["fee"] / 1e4, "address": d.get("address"),
                         "screen": d["status"],
                         "median_swaps_per_day": d.get("sampled_median_per_day")})
    return rows


def volume_persistence(monthly: dict) -> dict:
    """(e) raw counts as pre-registered; per-day disclosed alongside because
    2026-08 has 27 of 31 days in-window."""
    days_in = {"2026-05": 31, "2026-06": 30, "2026-07": 31, "2026-08": 27}
    raw = dict(monthly)
    peak = max(raw.values())
    worst = min(raw.values())
    rate = {k: v / days_in[k] for k, v in raw.items()}
    peak_r, worst_r = max(rate.values()), min(rate.values())
    return {"monthly_counts": raw, "peak": peak,
            "worst_over_peak": worst / peak,
            "worst_over_peak_perday": worst_r / peak_r,
            "pass_raw": worst >= 0.25 * peak,
            "pass_perday": worst_r >= 0.25 * peak_r}


def evaluate(cands, cov, races):
    cand_by = {c["slug"]: c for c in cands["candidates"]}
    pool_rows, arm_rows = [], []
    for slug, tags in sorted(races.items()):
        res = tags.get(PRIMARY_TAG) or tags.get(CONTROL_TAG)
        if res is None:
            continue
        c = cand_by[slug]
        is_control = slug == "weth_usdc_0p05"
        if is_control:
            monthly = {"2026-05": 575631, "2026-06": 1405733,
                       "2026-07": 783198, "2026-08": 669551}   # e003 meta
            eligible = True
        else:
            pc = cov["pools"][slug]
            monthly = pc["daily"]["monthly_swap_counts"]
            eligible = (pc["data_status"] == "OK"
                        and pc["daily"]["eligible_median_ge_48"])
        vp = volume_persistence(monthly)
        tier = c["fee"] / 1e6
        share = c["lp_fee_share_schedule"][0]["lp_fee_share"]
        best = None
        for a in res["arms"]:
            if a["arm"] == "always_cash":
                continue
            t = a["total"]
            days = t["hours"] / 24.0
            g = gamma(t)
            f_g = fg(t)
            months_fg = {k: fg(b) for k, b in a["months"].items()}
            vir = t["volume_in_range_usd"]
            implied_share = (t["lp_fees_usd"] / (vir * tier * share)) if vir else 0.0
            hpl_central = P.ENVELOPE_BY_NAME["central"].cost(t["rehedge_notional_usd"])
            gates = {
                "a_fg_ge_1p5": f_g >= 1.5,
                "b_monthly_fg_gt_1": all(v > 1.0 for v in months_fg.values()),
                "c_net_ge_target": t["per_day_central"] >= P.TARGET_USD_PER_DAY,
                "d_share_le_1pct": implied_share <= 0.01,
                "e_volume_persistence": vp["pass_raw"],
            }
            row = {
                "slug": slug, "family": c["family"], "eligible": eligible,
                "arm": a["arm"], "half_ticks": a["half_width_ticks"],
                "width_pct": a["width_pct"],
                "fees_per_day": t["lp_fees_usd"] / days,
                "gamma_per_day": g / days,
                "fees_over_gamma": f_g,
                "monthly_fg": months_fg,
                "worst_month_fg": min(months_fg.values()),
                "onchain_per_day": t["onchain_cost_usd"] / days,
                "hpl_central_per_day": hpl_central / days,
                "funding_per_day": t["funding_usd"] / days,
                "net_central_per_day": t["per_day_central"],
                "net_optimistic_per_day": t["per_day_optimistic"],
                "net_pessimistic_per_day": t["per_day_pessimistic"],
                "breakeven_x": (t["lp_fees_usd"] - t["net_usd_central"])
                               / t["lp_fees_usd"] if t["lp_fees_usd"] else float("nan"),
                "implied_pool_share": implied_share,
                "recenters": t["n_recenters"],
                "gates": gates,
                "passes_all": eligible and all(gates.values()),
            }
            arm_rows.append(row)
            if best is None or f_g > best["fees_over_gamma"]:
                best = row
        pool_rows.append({
            "slug": slug, "family": c["family"], "eligible": eligible,
            "hedge_mode": res["pool"]["hedge_mode"],
            "lp_fee_share": share, "fee_pct": c["fee"] / 1e4,
            "volume_persistence": vp,
            "best_arm": best["arm"], "best_fg": best["fees_over_gamma"],
            "best_worst_month_fg": best["worst_month_fg"],
            "best_net_central": best["net_central_per_day"],
            "best_gates": best["gates"],
        })

    eligible_arms = [r for r in arm_rows if r["eligible"]]
    supported = [r for r in eligible_arms if r["passes_all"]]
    max_fg = max((r["fees_over_gamma"] for r in eligible_arms), default=float("nan"))
    if supported:
        verdict = "SUPPORTED"
    elif max_fg < 1.0:
        verdict = "REFUTED"
    else:
        verdict = "INCONCLUSIVE"
    watchlist = []
    if verdict == "INCONCLUSIVE":
        for r in eligible_arms:
            if r["fees_over_gamma"] >= 1.0 and not r["passes_all"]:
                failed = [k for k, v in r["gates"].items() if not v]
                watchlist.append({"slug": r["slug"], "arm": r["arm"],
                                  "fees_over_gamma": r["fees_over_gamma"],
                                  "failed_gates": failed})
    return {"verdict": verdict, "max_fees_over_gamma_eligible": max_fg,
            "supported": [{k: r[k] for k in ("slug", "arm", "fees_over_gamma",
                                             "net_central_per_day")}
                          for r in sorted(supported,
                                          key=lambda r: -r["net_central_per_day"])],
            "watchlist": watchlist,
            "pool_rows": pool_rows, "arm_rows": arm_rows}


def fmt_tables(elig, ev) -> str:
    L = []
    L.append("## Eligibility / screen\n")
    L.append("| pool | family | fee | screen | median swaps/day | LP fee share |")
    L.append("|---|---|---:|---|---:|---:|")
    for r in elig:
        med = r.get("median_swaps_per_day")
        shr = r.get("lp_fee_share")
        L.append(f"| {r['slug']} | {r['family']} | {r['fee_pct']:.2f}% | {r['screen']} "
                 f"| {med if med is not None else '—'} "
                 f"| {f'{shr:.4f}' if shr else '—'} |")
    L.append("\n## Per-pool per-arm (lag1h_rh1h, central envelope, $/day)\n")
    L.append("| pool | arm | ±% | fees | gamma | f/g | worst-mo f/g | on-chain "
             "| HPL | funding | net central | breakeven× | pool share | rec |")
    L.append("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for r in ev["arm_rows"]:
        L.append(
            f"| {r['slug']} | {r['arm']} | {r['width_pct']*100:.2f} "
            f"| {r['fees_per_day']:+.3f} | {r['gamma_per_day']:+.3f} "
            f"| **{r['fees_over_gamma']:.3f}** | {r['worst_month_fg']:.3f} "
            f"| {-r['onchain_per_day']:+.3f} | {-r['hpl_central_per_day']:+.3f} "
            f"| {r['funding_per_day']:+.3f} | **{r['net_central_per_day']:+.3f}** "
            f"| {r['breakeven_x']:.2f}× | {r['implied_pool_share']*100:.3f}% "
            f"| {r['recenters']} |")
    L.append("\n## Monthly fees/gamma (best arm per pool)\n")
    months = ["2026-05", "2026-06", "2026-07", "2026-08"]
    L.append("| pool | best arm | " + " | ".join(months) + " | full |")
    L.append("|---|---|" + "---:|" * 5)
    for p in ev["pool_rows"]:
        best = next(r for r in ev["arm_rows"]
                    if r["slug"] == p["slug"] and r["arm"] == p["best_arm"])
        cells = " | ".join(f"{best['monthly_fg'].get(m, float('nan')):.3f}"
                           for m in months)
        L.append(f"| {p['slug']} | {p['best_arm']} | {cells} "
                 f"| **{best['fees_over_gamma']:.3f}** |")
    L.append("\n## Volume persistence (gate e)\n")
    L.append("| pool | 05 | 06 | 07 | 08 | worst/peak raw | worst/peak per-day | pass |")
    L.append("|---|---:|---:|---:|---:|---:|---:|---|")
    for p in ev["pool_rows"]:
        vp = p["volume_persistence"]
        mc = vp["monthly_counts"]
        L.append(f"| {p['slug']} | " + " | ".join(
            f"{mc.get(m, 0):,}" for m in months)
            + f" | {vp['worst_over_peak']:.2f} | {vp['worst_over_peak_perday']:.2f} "
            f"| {'PASS' if vp['pass_raw'] else 'FAIL'} |")
    L.append(f"\n## Verdict: **{ev['verdict']}**  "
             f"(max eligible fees/gamma {ev['max_fees_over_gamma_eligible']:.3f})\n")
    if ev["supported"]:
        L.append("Ranked candidate venues: " + ", ".join(
            f"{s['slug']}/{s['arm']} (net {s['net_central_per_day']:+.3f}/d)"
            for s in ev["supported"]))
    if ev["watchlist"]:
        for w in ev["watchlist"]:
            L.append(f"- watchlist: {w['slug']} {w['arm']} f/g "
                     f"{w['fees_over_gamma']:.3f}, failed {w['failed_gates']}")
    return "\n".join(L) + "\n"


def main() -> int:
    cands, cov, races = load_all()
    elig = eligibility_rows(cands, cov)
    ev = evaluate(cands, cov, races)
    md = fmt_tables(elig, ev)
    (E005 / "out" / "decision.json").write_text(json.dumps(
        {"eligibility": elig, **ev}, indent=2, default=float))
    (E005 / "out" / "tables.md").write_text(md)
    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
