#!/usr/bin/env python3
"""E006 tables and the pre-registered decision rule, as a program.

    nix develop .#gate1 -c python backtest_model_server/e006/tables.py

Reads out/stage1_results.json, out/stage2_results.json, out/descriptive.json;
writes out/tables.md and prints the verdict. The rule (central envelope,
frozen before the run — loop/experiments/E006-timing-oracle-bound.md):

  REFUTED       stage-1 upper bound < +$0.78/day at EVERY width
  SUPPORTED     stage-2 exact oracle >= +$1.56/day at SOME width
  INCONCLUSIVE  otherwise; report target / stage-2 oracle per width
"""

from __future__ import annotations

import json
from pathlib import Path

E006 = Path(__file__).resolve().parent
OUT = E006 / "out"

REFUTE_BAR_PER_DAY = 0.78      # 2x the +$0.389/day target, stage-1 UB
SUPPORT_BAR_PER_DAY = 1.56     # 4x the target, stage-2 exact
TARGET_PER_DAY = 0.38904109589041097


def verdict(s1: dict, s2: dict) -> tuple[str, str]:
    ub = {k: a["points"]["central"]["per_day_usd"] for k, a in s1["arms"].items()}
    ex = {k: a["points"]["central"]["per_day_usd"] for k, a in s2["arms"].items()}
    if all(v < REFUTE_BAR_PER_DAY for v in ub.values()):
        return "REFUTED", (
            f"stage-1 upper bound tops out at ${max(ub.values()):+.3f}/day "
            f"(< +${REFUTE_BAR_PER_DAY}/day at every width)")
    if any(v >= SUPPORT_BAR_PER_DAY for v in ex.values()):
        k = max(ex, key=ex.get)
        return "SUPPORTED", (
            f"stage-2 exact oracle reaches ${ex[k]:+.3f}/day at {k} "
            f"(>= +${SUPPORT_BAR_PER_DAY}/day)")
    return "INCONCLUSIVE", (
        f"stage-1 UB max ${max(ub.values()):+.3f}/day, "
        f"stage-2 exact max ${max(ex.values()):+.3f}/day — between the bars")


def main() -> int:
    s1 = json.loads((OUT / "stage1_results.json").read_text())
    s2 = json.loads((OUT / "stage2_results.json").read_text())
    de = json.loads((OUT / "descriptive.json").read_text())
    days = s1["window"]["days"]

    L: list[str] = []
    L.append("# E006 tables\n")
    L.append(f"Window {s1['window']['start']} → {s1['window']['end']} "
             f"({days:.2f} days, {s1['window']['n_swaps']:,} swaps). "
             f"Cost model `{s1['cost_model_version']}`, envelope "
             f"`{s1['envelope_version']}`. Target +${TARGET_PER_DAY:.3f}/day.\n")

    L.append("## Frontier — oracle $/day by width (central envelope)\n")
    L.append("| Arm | ±% | stage-1 UB opt | **stage-1 UB central** | stage-1 UB pess "
             "| **stage-2 exact central** | exact opt | exact pess | held % | streaks "
             "| capture needed |")
    L.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for k in s1["arms"]:
        a1, a2 = s1["arms"][k], s2["arms"][k]
        p1, p2 = a1["points"], a2["points"]
        ex_c = p2["central"]["per_day_usd"]
        cap = TARGET_PER_DAY / ex_c if ex_c > 0 else float("nan")
        L.append(
            f"| w{a1['width']} | ±{a1['width_pct']*100:.3f}% "
            f"| {p1['optimistic']['per_day_usd']:+.3f} "
            f"| **{p1['central']['per_day_usd']:+.3f}** "
            f"| {p1['pessimistic']['per_day_usd']:+.3f} "
            f"| **{ex_c:+.3f}** "
            f"| {p2['optimistic']['per_day_usd']:+.3f} "
            f"| {p2['pessimistic']['per_day_usd']:+.3f} "
            f"| {a1['points']['central']['held_frac']*100:.1f}% "
            f"| {a1['points']['central']['n_streaks']} "
            f"| {'—' if cap != cap else f'{cap:.0%}'} |")
    L.append("")
    L.append("`capture needed` = target ÷ stage-2 exact oracle: the fraction of "
             "the realistic ceiling a causal model must capture to reach "
             f"+${TARGET_PER_DAY:.3f}/day.\n")

    L.append("## Stage-1 payoff decomposition (all hours, $ over the window)\n")
    L.append("| Arm | Σ fees | Σ funding | Σ gamma | Σ payoff | UB central $ "
             "| stage-2 exact $ | retention |")
    L.append("|---|---:|---:|---:|---:|---:|---:|---:|")
    for k in s1["arms"]:
        a1, a2 = s1["arms"][k], s2["arms"][k]
        ret = a2["stage2_over_stage1_central"]
        L.append(f"| w{a1['width']} | {a1['sum_fees_usd']:+.0f} "
                 f"| {a1['sum_funding_usd']:+.2f} | {a1['sum_gamma_pnl_usd']:+.0f} "
                 f"| {a1['sum_payoff_usd']:+.0f} "
                 f"| {a1['points']['central']['value_usd']:+.2f} "
                 f"| {a2['points']['central']['net_usd']:+.2f} "
                 f"| {'—' if ret is None else f'{ret:.1%}'} |")
    L.append("")

    bk = de["best_arm"]
    st = de["oracle_structure"]
    L.append(f"## Descriptive — NOT part of the verdict (best arm {bk})\n")
    L.append(f"Held {st['held_hours']}/{st['total_hours']} hours "
             f"({st['held_frac']:.1%}) in {st['n_streaks']} streaks — "
             f"mean {st['streak_hours']['mean']:.1f}h, median "
             f"{st['streak_hours']['p50']:.0f}h, p90 {st['streak_hours']['p90']:.0f}h, "
             f"max {st['streak_hours']['max']}h.\n")
    L.append("| Month | hours | held | held % |")
    L.append("|---|---:|---:|---:|")
    for lab, m in st["monthly"].items():
        L.append(f"| {lab} | {m['hours']} | {m['held']} | {m['held_frac']:.1%} |")
    L.append("")
    L.append("### Trailing (causal) signals vs oracle membership\n")
    L.append("| Signal | AUC | held p50 | skipped p50 | held mean | skipped mean |")
    L.append("|---|---:|---:|---:|---:|---:|")
    for name, s in de["signals"].items():
        L.append(f"| {name} | {s['auc_for_held']:.3f} | {s['held']['p50']:.4g} "
                 f"| {s['skipped']['p50']:.4g} | {s['held']['mean']:.4g} "
                 f"| {s['skipped']['mean']:.4g} |")
    L.append("")
    L.append("### Persistence — autocorrelation, lags 1/3/6/12/24h\n")
    L.append("| Series | lag 1 | lag 3 | lag 6 | lag 12 | lag 24 |")
    L.append("|---|---:|---:|---:|---:|---:|")
    for name, acf in de["persistence_acf_lags_1_24"].items():
        L.append(f"| {name} | " + " | ".join(f"{acf[k-1]:.3f}" for k in (1, 3, 6, 12, 24)) + " |")
    L.append("")

    v, why = verdict(s1, s2)
    L.append("## Verdict (pre-registered rule)\n")
    L.append(f"**{v}** — {why}.\n")
    if v == "INCONCLUSIVE":
        L.append("Capture-fraction math per width is in the frontier table's "
                 "last column.\n")

    (OUT / "tables.md").write_text("\n".join(L))
    print(f"verdict: {v} — {why}")
    print(f"wrote {OUT/'tables.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
