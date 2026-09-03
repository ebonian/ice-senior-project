#!/usr/bin/env python3
"""E011 decision rule as a program + REPORT tables.

    nix develop .#gate1 -c python backtest_model_server/e011/tables11.py

Applies loop/experiments/E011-link-ceiling.md's pre-registered rule to the
checkpointed artifacts — nothing else — and renders the per-arm tables.

Output: out/decision.json, out/tables.md.
"""

from __future__ import annotations

import numpy as np

import common11 as C

TARGET = C.TARGET_10PCT
TARGET2 = C.TARGET_20PCT


def main() -> int:
    s1 = C.read_json(C.OUT / "stage1_results.json")
    s2 = C.read_json(C.OUT / "stage2_results.json")
    fu = C.read_json(C.OUT / "funding_results.json")
    co = C.read_json(C.OUT / "coarse_results.json")
    wk = C.read_json(C.OUT / "wick_results.json")

    refuted = all(a["points"]["central"]["per_day_usd"] < TARGET
                  for a in s1["arms"].values())

    qualifying = [label for label, a in s2["arms"].items()
                  if a["points"]["central"]["per_day_usd"] >= TARGET2]
    f1_pass = fu["F1"]["passes"]
    f2_pass_arms = [label for label in qualifying
                    if fu["F2"][label]["passes_f2_floor"]]
    supported = bool(qualifying) and f1_pass and bool(f2_pass_arms)

    verdict = ("REFUTED" if refuted
               else "SUPPORTED" if supported else "INCONCLUSIVE")

    decision = {
        "experiment": "E011", "verdict": verdict,
        "rule": {
            "refuted_if": f"stage-1 UB < {TARGET:.4f}/day central at every arm",
            "refuted_fires": refuted,
            "supported_if": (f"stage-2 exact >= {TARGET2:.4f}/day central at "
                             "some arm AND F1 AND F2 on that arm"),
            "qualifying_arms_net": qualifying,
            "f1_passes": f1_pass,
            "f2_passes_on_qualifying": f2_pass_arms,
            "supported_fires": supported,
        },
        "per_arm": {},
        "funding": {
            "f1_trailing_12m_package_per_day":
                fu["F1"]["trailing_12m_package_per_day"],
            "f2": fu["F2"],
        },
        "wick_clean": {label: {
            "held_top10_swap_weight":
                wk["arms"][label]["held_swaps"]["top10_share"],
            "full_window_top10": wk["full_window"]["top10_share"]}
            for label in s2["arms"]},
    }
    for label in s1["arms"]:
        a1, a2 = s1["arms"][label], s2["arms"][label]
        decision["per_arm"][label] = {
            "width_pct": a1["width_pct"],
            "stage1_ub_per_day": {p: a1["points"][p]["per_day_usd"]
                                  for p in C.POINTS},
            "stage2_exact_per_day": {p: a2["points"][p]["per_day_usd"]
                                     for p in C.POINTS},
            "held_frac": a2["held_frac"],
            "n_streaks": a2["n_streaks_simulated"],
            "streak_len_median_h":
                a1["points"]["central"]["streak_len_median_h"],
            "capture_bar_10pct":
                TARGET / a2["points"]["central"]["per_day_usd"]
                if a2["points"]["central"]["per_day_usd"] > 0 else None,
            "capture_bar_20pct":
                TARGET2 / a2["points"]["central"]["per_day_usd"]
                if a2["points"]["central"]["per_day_usd"] > 0 else None,
        }
    C.write_json(C.OUT / "decision.json", decision)

    L = []
    L.append("## Per-arm ceiling ($/day over 118.99 days, coupled envelope "
             "points)\n")
    L.append("| arm | width | always-in central (E010) | stage-1 UB "
             "opt/cen/pess | stage-2 exact opt/cen/pess | held % | streaks "
             "(med h) | capture bar 10% |")
    L.append("|---|---|---:|---|---|---:|---|---:|")
    e010c = {a["arm"]: a["total"]["per_day_central"]
             for a in C.read_json(C.E010_RESULTS["central"])["arms"]}
    for label, d in decision["per_arm"].items():
        s1p, s2p = d["stage1_ub_per_day"], d["stage2_exact_per_day"]
        L.append(
            f"| {label} | ±{d['width_pct']*100:.2f}% | "
            f"{e010c[label]:+.3f} | "
            f"{s1p['optimistic']:+.2f} / **{s1p['central']:+.2f}** / "
            f"{s1p['pessimistic']:+.2f} | "
            f"{s2p['optimistic']:+.2f} / **{s2p['central']:+.2f}** / "
            f"{s2p['pessimistic']:+.2f} | "
            f"{d['held_frac']*100:.1f}% | {d['n_streaks']} "
            f"({d['streak_len_median_h']:.0f}) | "
            + (f"{d['capture_bar_10pct']*100:.0f}% |"
               if d['capture_bar_10pct'] else "— |"))
    L.append("")

    L.append("## Coarseness (central; stage-2 exact $/day, stage-1 UB in "
             "parens)\n")
    cons = ["unconstrained"] + [c for c, _, _ in
                                (("minhold_6h", 0, 0), ("minhold_12h", 0, 0),
                                 ("minhold_24h", 0, 0), ("grain_4h", 0, 0),
                                 ("grain_24h", 0, 0))]
    L.append("| constraint | " + " | ".join(
        f"±{decision['per_arm'][l]['width_pct']*100:.2f}%"
        for l in decision["per_arm"]) + " |")
    L.append("|---|" + "---:|" * len(decision["per_arm"]))
    for cname in cons:
        row = [cname]
        for label in decision["per_arm"]:
            arm = co["arms"][label]
            v = (arm["unconstrained"] if cname == "unconstrained"
                 else arm["constraints"][cname])
            row.append(f"{v['stage2_per_day']:+.2f} "
                       f"({v['stage1_per_day']:+.2f})")
        L.append("| " + " | ".join(row) + " |")
    L.append("")

    p = fu["package_daily_usd"]
    L.append("## LINK-PERP funding look (two-leg package on wide-arm "
             f"notionals ${fu['notionals_usd']['link_leg_N0']:,.0f} LINK + "
             f"${fu['notionals_usd']['eth_leg_N1']:,.0f} ETH)\n")
    L.append(f"- LINK leg: full-history {fu['link_leg']['mean_ann_pct']:+.2f}% "
             f"ann on notional, trailing-12m "
             f"{fu['link_leg']['trailing_12m_ann_pct']:+.2f}%, floor-pinned "
             f"{fu['link_leg']['pinned_frac_full']*100:.1f}%, negative "
             f"{fu['link_leg']['negative_frac_full']*100:.1f}% of hours "
             f"({fu['link_leg']['first_utc']} → {fu['link_leg']['last_utc']})")
    L.append(f"- ETH leg: full {fu['eth_leg']['mean_ann_pct']:+.2f}%, "
             f"trailing-12m {fu['eth_leg']['trailing_12m_ann_pct']:+.2f}%")
    L.append(f"- package: full ${p['full_mean_per_day']:+.3f}/day, "
             f"trailing-12m ${p['trailing_12m_mean_per_day']:+.3f}/day; "
             f"worst 30d ${p['worst_rolling_30d_per_day']:+.3f}/day "
             f"({p['worst_rolling_30d_start']}); longest negative run "
             f"{p['longest_negative_run_days']}d; negative days "
             f"{p['negative_day_fraction_full']*100:.1f}% full / "
             f"{p['negative_day_fraction_trailing_12m']*100:.1f}% t12m")
    L.append(f"- regimes: up ${p['up_regime_mean_per_day']:+.3f}/day, down "
             f"${p['down_regime_mean_per_day']:+.3f}/day (down-share "
             f"{p['down_regime_day_share']*100:.0f}%); cross-venue sign "
             f"agreement {fu['cross_venue_sign_agreement_8h']*100:.1f}%")
    L.append(f"- halves, LINK ann%: " + ", ".join(
        f"{h} {v:+.1f}" for h, v in fu["link_leg"]["halves_ann_pct"].items()))
    L.append("")
    (C.OUT / "tables.md").write_text("\n".join(L))
    print(f"VERDICT: {verdict}")
    print(f"  refuted fires: {refuted}; qualifying {qualifying}; "
          f"F1 {f1_pass}; F2 on qualifying {f2_pass_arms}")
    print(f"wrote {C.OUT/'decision.json'} and tables.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
