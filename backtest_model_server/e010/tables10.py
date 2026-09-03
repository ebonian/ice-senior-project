#!/usr/bin/env python3
"""E010 tables and the pre-registered decision rule as a program.

    nix develop .#gate1 -c python backtest_model_server/e010/tables10.py

Reads the raced results (out/<slug>/lag1h_rh1h_cap*_gas-*/results.json),
coverage, candidates and gas envelope; evaluates gates (a)-(e) per venue x
arm at the $10k reference with the COUPLED envelope (gas point g read at HPL
point g); emits out/decision.json and out/tables.md.

Verdict clauses, verbatim from the pre-registration:
  SUPPORTED    >= 1 venue x arm passes (a) f/g >= 1.5 central full-window,
               (b) f/g > 1.0 central every month, (c) net >= 10% APR central
               at $10k (>= +$2.7397/day), (d) implied share <= 1% at $10k,
               (e) volume persistence >= 25% of peak month.
  INCONCLUSIVE no full pass, but >= 1 venue clears f/g >= 1.0 on an
               honest-share arm through all validity gates.
  REFUTED      nothing >= 1.0 anywhere, mainnet included.
Plus, always: the feeProtocol hypothesis outcome, and the measured scaling
law at $1.42k / $10k / $50k for every venue's best arm.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

E010 = Path(__file__).resolve().parent
sys.path.append(str(E010))
for p in (str(E010.parent / "gate1"), str(E010.parent / "e005")):
    if p not in sys.path:
        sys.path.insert(0, p)
import registry as R  # noqa: E402

CAP = 10_000.0
TARGET_PD = R.target_usd_per_day(CAP)
E010_SLUGS = [c.slug for c in R.CANDIDATES]
PARTB_SLUGS = ["wsteth_weth_0p01", "link_weth_0p05"]     # Arbitrum re-bind


def load(slug: str, tag: str) -> dict | None:
    f = E010 / "out" / slug / tag / "results.json"
    return json.loads(f.read_text()) if f.exists() else None


def fg_of(t: dict) -> float:
    g = t["lp_value_change_usd"] + t["hedge_price_pnl_usd"]
    return t["lp_fees_usd"] / abs(g) if g else float("inf")


def arm_metrics(rr: dict, a: dict) -> dict:
    t = a["total"]
    tier = rr["pool"]["fee"] / 1e6
    shr = rr["pool"]["lp_fee_share"]
    days = t["hours"] / 24.0
    vir = t["volume_in_range_usd"]
    gam = t["lp_value_change_usd"] + t["hedge_price_pnl_usd"]
    months_fg = {k: fg_of(b) for k, b in a["months"].items()}
    months_net = {k: b["per_day_central"] for k, b in a["months"].items()}
    return {
        "arm": a["arm"], "width_pct": a["width_pct"],
        "recenters": t["n_recenters"],
        "fees_per_day": t["lp_fees_usd"] / days,
        "gamma_per_day": gam / days,
        "onchain_per_day": t["onchain_cost_usd"] / days,
        "funding_per_day": t["funding_usd"] / days,
        "fg_full": fg_of(t),
        "months_fg": months_fg,
        "worst_month_fg": min(months_fg.values()),
        "months_net_central": months_net,
        "all_months_net_positive": all(v > 0 for v in months_net.values()),
        "net_central_per_day": t["per_day_central"],
        "implied_share": (t["lp_fees_usd"] / (vir * tier * shr)) if vir else 0.0,
        "gamma_sign": "positive-drift" if gam > 0 else "negative",
    }


def volume_persistence(monthly: dict) -> dict:
    vals = list(monthly.values())
    ratio = min(vals) / max(vals) if vals and max(vals) else 0.0
    return {"min_over_peak": ratio, "pass": ratio >= 0.25}


def main() -> int:
    cands = {c["slug"]: c for c in
             json.loads((E010 / "out" / "candidates.json").read_text())["candidates"]}
    cov = json.loads((E010 / "out" / "coverage.json").read_text())["pools"]
    gas = json.loads(R.GAS_ENVELOPE_FILE.read_text())

    venue_rows, arm_rows = [], []
    for slug in E010_SLUGS + PARTB_SLUGS:
        partb = slug in PARTB_SLUGS
        cc = load(slug, f"lag1h_rh1h_cap{int(CAP)}_gas-central")
        if cc is None:
            cand = cands.get(slug, {})
            venue_rows.append({"slug": slug, "chain": cand.get("chain", "?"),
                               "status": cand.get("status", "NOT-RACED"),
                               "in_verdict": False})
            continue
        opt = load(slug, f"lag1h_rh1h_cap{int(CAP)}_gas-optimistic")
        pes = load(slug, f"lag1h_rh1h_cap{int(CAP)}_gas-pessimistic")
        c14 = load(slug, "lag1h_rh1h_cap1420_gas-central")
        c50 = load(slug, "lag1h_rh1h_cap50000_gas-central")
        rh0 = load(slug, f"lag1h_rh0h_cap{int(CAP)}_gas-central")
        chain = cc["pool"]["chain"]
        if partb:
            vp = {"min_over_peak": None, "pass": True}   # E005 measured it
        else:
            monthly = cov[slug]["daily"]["monthly_swap_counts"]
            vp = volume_persistence(monthly)

        by_arm_o = ({a["arm"]: a for a in opt["arms"]} if opt else {})
        by_arm_p = ({a["arm"]: a for a in pes["arms"]} if pes else {})
        by_14 = ({a["arm"]: a for a in c14["arms"]} if c14 else {})
        by_50 = ({a["arm"]: a for a in c50["arms"]} if c50 else {})
        by_rh0 = ({a["arm"]: a for a in rh0["arms"]} if rh0 else {})

        best = None
        headroom = False
        for a in cc["arms"]:
            if a["arm"] == "always_cash":
                continue
            m = arm_metrics(cc, a)
            # coupled envelope: gas point g read at HPL point g
            m["net_optimistic_per_day"] = (
                by_arm_o[a["arm"]]["total"]["per_day_optimistic"]
                if by_arm_o else None)
            m["net_pessimistic_per_day"] = (
                by_arm_p[a["arm"]]["total"]["per_day_pessimistic"]
                if by_arm_p else None)
            m["net_10k_rh0h_central"] = (
                by_rh0[a["arm"]]["total"]["per_day_central"] if by_rh0 else None)
            m["net_1420_central"] = (
                by_14[a["arm"]]["total"]["per_day_central"] if by_14 else None)
            m["net_50k_central"] = (
                by_50[a["arm"]]["total"]["per_day_central"] if by_50 else None)
            m["apr_10k_central_pct"] = m["net_central_per_day"] * 365 / CAP * 100
            m["apr_1420_central_pct"] = (m["net_1420_central"] * 365 / 1420 * 100
                                         if m["net_1420_central"] is not None else None)
            m["apr_50k_central_pct"] = (m["net_50k_central"] * 365 / 50000 * 100
                                        if m["net_50k_central"] is not None else None)
            gates = {
                "a_fg_ge_1p5": m["fg_full"] >= 1.5,
                "b_monthly_fg_gt_1": all(v > 1.0 for v in m["months_fg"].values()),
                "c_net_ge_10pct_apr": m["net_central_per_day"] >= TARGET_PD,
                "d_share_le_1pct": m["implied_share"] <= 0.01,
                "e_volume_persistence": vp["pass"],
            }
            m["gates"] = gates
            m["passes_all"] = all(gates.values())
            m["honest_headroom"] = (m["fg_full"] >= 1.0 and gates["d_share_le_1pct"])
            headroom = headroom or m["honest_headroom"]
            m["slug"], m["chain"], m["part"] = slug, chain, ("B" if partb else "C")
            arm_rows.append(m)
            if best is None or m["net_central_per_day"] > best["net_central_per_day"]:
                best = m
        venue_rows.append({
            "slug": slug, "chain": chain,
            "family": cands.get(slug, {}).get("family", "arb-rebind"),
            "in_verdict": not partb,
            "lp_fee_share": cc["pool"]["lp_fee_share"],
            "fee_protocol": cands.get(slug, {}).get("pool_state", {}).get(
                "fee_protocol_now"),
            "volume_persistence": vp,
            "model_headroom": headroom,
            "best_arm": best["arm"], "best": best,
        })

    # not-raced candidates (recorded, never silently dropped)
    for slug, c in cands.items():
        if c["status"] != "RESOLVED" and not any(v["slug"] == slug for v in venue_rows):
            venue_rows.append({"slug": slug, "chain": c["chain"],
                               "status": c["status"], "in_verdict": False})

    verdict_rows = [m for m in arm_rows if m["part"] == "C"]
    supported = [m for m in verdict_rows if m["passes_all"]]
    honest_10 = [m for m in verdict_rows if m["honest_headroom"]]
    if supported:
        verdict = "SUPPORTED"
    elif honest_10:
        verdict = "INCONCLUSIVE"
    else:
        verdict = "REFUTED"

    fee_protocol_outcome = {
        "hypothesis": "mainnet v3 pools at feeProtocol 0x0 would multiply LP "
                      "fee income x1.33 (B4/M004)",
        "measured": {v["slug"]: {"fee_protocol": v.get("fee_protocol"),
                                 "lp_fee_share": v.get("lp_fee_share")}
                     for v in venue_rows if v.get("fee_protocol") is not None},
        "outcome": "DEAD — every mainnet and Base pool reads 0x44 (LPs keep "
                   "3/4, 0.01%/0.05% tiers) or 0x66 (5/6, 0.30% tier), "
                   "identical to Arbitrum; zero in-window SetFeeProtocol "
                   "events; the multiplier is exactly 1.0 and E005's "
                   "0.86-0.97 near-misses stay where they were",
    }

    out = {
        "experiment": "E010", "reference_capital_usd": CAP,
        "lp_notional_usd": R.LP_NOTIONAL_10K,
        "target_usd_per_day": TARGET_PD,
        "gas_envelope": {k: gas[k]["usd_per_tx"] for k in ("mainnet", "base")},
        "verdict": verdict,
        "supported_rows": [f"{m['slug']}/{m['arm']}" for m in supported],
        "honest_headroom_rows": [
            {"slug": m["slug"], "arm": m["arm"], "fg": m["fg_full"],
             "share": m["implied_share"], "net_pd": m["net_central_per_day"],
             "gamma_sign": m["gamma_sign"]} for m in honest_10],
        "fee_protocol_outcome": fee_protocol_outcome,
        "venues": venue_rows, "arm_rows": arm_rows,
    }
    (E010 / "out" / "decision.json").write_text(json.dumps(out, indent=2))

    # ---- tables.md --------------------------------------------------------
    L = []
    L.append("# E010 tables (generated by tables10.py)\n")
    L.append(f"$10k reference (LP notional ${R.LP_NOTIONAL_10K:,.2f}); coupled "
             f"envelope; target +${TARGET_PD:.4f}/day (10% APR).\n")
    L.append("## Part C — venue screen at $10k, best arm per venue "
             "(coupled central)\n")
    L.append("| venue | chain | best arm | f/g full | worst-mo f/g | "
             "net $/d cen | net opt | net pess | APR% cen | share | "
             "headroom | gates failed |")
    L.append("|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|---|")
    for v in venue_rows:
        if "best" not in v:
            L.append(f"| {v['slug']} | {v['chain']} | — | | | | | | | | | "
                     f"{v.get('status')} |")
            continue
        b = v["best"]
        failed = ",".join(k[0] for k, ok in b["gates"].items() if not ok) or "none"
        opt_s = (f"{b['net_optimistic_per_day']:+.3f}"
                 if b["net_optimistic_per_day"] is not None else "(frozen)")
        pes_s = (f"{b['net_pessimistic_per_day']:+.3f}"
                 if b["net_pessimistic_per_day"] is not None else "(frozen)")
        L.append(
            f"| {v['slug']} | {v['chain']} | {b['arm']} ±{b['width_pct']*100:.2f}% "
            f"| {b['fg_full']:.3f} | {b['worst_month_fg']:.3f} "
            f"| {b['net_central_per_day']:+.3f} "
            f"| {opt_s} "
            f"| {pes_s} "
            f"| {b['apr_10k_central_pct']:+.2f} "
            f"| {b['implied_share']*100:.3f}% "
            f"| {'YES' if v['model_headroom'] else 'no'} | {failed} |")
    L.append("\n## Scaling law — best arm, measured central net $/day "
             "(APR%) at each capital\n")
    L.append("| venue | $1,420 | $10,000 | $50,000 |")
    L.append("|---|---:|---:|---:|")
    for v in venue_rows:
        if "best" not in v:
            continue
        b = v["best"]
        L.append(f"| {v['slug']} "
                 f"| {b['net_1420_central']:+.3f} ({b['apr_1420_central_pct']:+.1f}%) "
                 f"| {b['net_central_per_day']:+.3f} ({b['apr_10k_central_pct']:+.1f}%) "
                 f"| {b['net_50k_central']:+.3f} ({b['apr_50k_central_pct']:+.1f}%) |")
    L.append("\n## Honest-headroom arms (f/g >= 1.0 at share <= 1%)\n")
    L.append("| venue | arm | f/g | share | net $/d | gamma |")
    L.append("|---|---|---:|---:|---:|---|")
    for m in honest_10:
        L.append(f"| {m['slug']} | {m['arm']} | {m['fg_full']:.3f} "
                 f"| {m['implied_share']*100:.3f}% "
                 f"| {m['net_central_per_day']:+.3f} | {m['gamma_sign']} |")
    L.append("\n## All arms (Part C + Part B context)\n")
    L.append("| venue | arm | ±% | rec | fees/d | gamma/d | fund/d | f/g | "
             "worst-mo f/g | mo-net all>0 | net cen $/d | rh0h $/d | share |")
    L.append("|---|---|---:|---:|---:|---:|---:|---:|---:|---|---:|---:|---:|")
    for m in arm_rows:
        rh0h = (f"{m['net_10k_rh0h_central']:+.3f}"
                if m["net_10k_rh0h_central"] is not None else "—")
        L.append(
            f"| {m['slug']} | {m['arm']} | {m['width_pct']*100:.2f} "
            f"| {m['recenters']} | {m['fees_per_day']:+.3f} "
            f"| {m['gamma_per_day']:+.3f} | {m['funding_per_day']:+.3f} "
            f"| {m['fg_full']:.3f} | {m['worst_month_fg']:.3f} "
            f"| {'Y' if m['all_months_net_positive'] else 'n'} "
            f"| {m['net_central_per_day']:+.3f} "
            f"| {rh0h} "
            f"| {m['implied_share']*100:.3f}% |")
    (E010 / "out" / "tables.md").write_text("\n".join(L) + "\n")

    print(f"VERDICT: {verdict}")
    print(f"  supported rows: {out['supported_rows']}")
    print(f"  honest f/g>=1.0 rows: "
          f"{[(r['slug'], r['arm'], round(r['fg'], 3)) for r in out['honest_headroom_rows']]}")
    print(f"  feeProtocol outcome: {fee_protocol_outcome['outcome'][:80]}...")
    print("wrote out/decision.json, out/tables.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
