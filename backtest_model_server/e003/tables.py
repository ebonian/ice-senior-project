#!/usr/bin/env python3
"""Render E003's report tables from results.json. No number is hand-copied.

    nix develop .#gate1 -c python backtest_model_server/e003/tables.py \
        --run lag0h_rh1h --verdict

`--verdict` additionally evaluates the pre-registered decision rule and prints
which clause fired, so the verdict in REPORT.md is a program output rather than
a judgement call made after looking at the frontier.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

E003 = Path(__file__).resolve().parent
sys.path.insert(0, str(E003))
import envelope as ENV  # noqa: E402

POINTS = ("optimistic", "central", "pessimistic")


def load(run: str) -> dict:
    return json.loads((E003 / "out" / run / "results.json").read_text())


def order(arms: list[dict]) -> list[dict]:
    return sorted(arms, key=lambda a: (a["width"] is None, a["width"] or 0))


def frontier_table(d: dict) -> str:
    out = ["| Arm | ±% | recenters | optimistic | central | pessimistic |",
           "|---|---:|---:|---:|---:|---:|"]
    for a in order(d["arms"]):
        pct = f"±{a['width_pct']*100:.3f}%" if a["width_pct"] is not None else "—"
        t = a["total"]
        out.append(
            f"| `{a['arm']}` | {pct} | {t['n_recenters']:,} | "
            + " | ".join(f"{t['per_day_' + p]:+.3f}" for p in POINTS) + " |")
    return "\n".join(out)


def monthly_table(d: dict, point: str) -> str:
    labels = sorted({m for a in d["arms"] for m in a["months"]})
    out = ["| Arm | " + " | ".join(labels) + " | full window |",
           "|---|" + "---:|" * (len(labels) + 1)]
    for a in order(d["arms"]):
        cells = []
        for lab in labels:
            m = a["months"].get(lab)
            cells.append(f"{m['per_day_' + point]:+.3f}" if m else "—")
        cells.append(f"**{a['total']['per_day_' + point]:+.3f}**")
        out.append(f"| `{a['arm']}` | " + " | ".join(cells) + " |")
    return "\n".join(out)


def attribution_table(d: dict) -> str:
    out = ["| Arm | LP fees | crystallized IL | fee/IL | basket δ | hedge P&L | "
           "funding | on-chain | HPL (central) |",
           "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    cen = ENV.ENVELOPE_BY_NAME["central"]
    for a in order(d["arms"]):
        t = a["total"]
        ratio = (t["lp_fees_usd"] / abs(t["il_usd"])) if t["il_usd"] else float("nan")
        out.append(
            f"| `{a['arm']}` | {t['lp_fees_usd']:+,.2f} | {t['il_usd']:+,.2f} | "
            + (f"{ratio:.3f}" if ratio == ratio else "—")
            + f" | {t['basket_delta_usd']:+,.2f} | {t['hedge_price_pnl_usd']:+,.2f} | "
              f"{t['funding_usd']:+,.2f} | {-t['onchain_cost_usd']:+,.2f} | "
              f"{-cen.cost(t['rehedge_notional_usd']):+,.2f} |")
    return "\n".join(out)


def gamma_table(d: dict) -> str:
    """Fees against what the hedge actually leaves behind.

    For a delta-hedged LP the meaningful cost is not crystallized IL, which is
    measured against a HODL basket nobody holds. It is
    `lp_value_change + hedge_pnl` — the Itô gamma term the short cannot remove,
    because the short cancels the first-order delta and leaves the second-order
    convexity. Fees have to beat THAT, plus execution, for the arm to pay.
    """
    out = ["| Arm | LP fees $/day | hedged gamma $/day | fees/gamma | "
           "on-chain $/day | HPL central $/day | funding $/day | net central $/day | "
           "breakeven fee × |",
           "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    cen = ENV.ENVELOPE_BY_NAME["central"]
    for a in order(d["arms"]):
        t = a["total"]
        days = t["hours"] / 24.0
        gam = t["lp_value_change_usd"] + t["hedge_price_pnl_usd"]
        r = (t["lp_fees_usd"] / abs(gam)) if gam else float("nan")
        # What the pool would have had to pay this position, as a multiple of
        # what it did pay, for the arm to break even with everything else held
        # fixed. Close to constant across arms means the shortfall is a property
        # of the pool (fee tier against realized variance), not of the width.
        need = (-gam - t["funding_usd"] + t["onchain_cost_usd"]
                + cen.cost(t["rehedge_notional_usd"]))
        bx = (need / t["lp_fees_usd"]) if t["lp_fees_usd"] else float("nan")
        out.append(
            f"| `{a['arm']}` | {t['lp_fees_usd']/days:+.3f} | {gam/days:+.3f} | "
            + (f"{r:.3f}" if r == r else "—")
            + f" | {-t['onchain_cost_usd']/days:+.3f} | "
              f"{-cen.cost(t['rehedge_notional_usd'])/days:+.3f} | "
              f"{t['funding_usd']/days:+.3f} | "
              f"**{t['per_day_central']:+.3f}** | "
            + (f"{bx:.2f}×" if bx == bx else "—") + " |")
    return "\n".join(out)


def notional_table(d: dict) -> str:
    """Turnover, plus the pool share the arm's liquidity actually commands.

    The share matters because the fee model credits us
    `L_raw / (L_pool + L_raw)` of every in-range swap. If a narrow arm's implied
    share were large, the counterfactual would be assuming a position big enough
    to move the pool it is being priced against. It is not: see the last column.
    """
    out = ["| Arm | recenters | recenters/day | swapped notional | rehedge notional | "
           "×capital/day | LP fees $/day | implied pool share |",
           "|---|---:|---:|---:|---:|---:|---:|---:|"]
    cap = d["policy"]["lp_capital_usd"]
    lp_bps = 3.75 / 1e4          # cost_model.EFFECTIVE_LP_FEE_BPS, protocol-fee correct
    for a in order(d["arms"]):
        t = a["total"]
        days = t["hours"] / 24.0
        vir = t["volume_in_range_usd"]
        share = (t["lp_fees_usd"] / (vir * lp_bps)) if vir else float("nan")
        out.append(
            f"| `{a['arm']}` | {t['n_recenters']:,} | {t['n_recenters']/days:.2f} | "
            f"${t['swapped_notional_usd']:,.0f} | ${t['rehedge_notional_usd']:,.0f} | "
            f"{t['rehedge_notional_usd']/cap/days:.2f}× | "
            f"{t['lp_fees_usd']/days:.3f} | "
            + (f"{share*100:.4f}%" if share == share else "—") + " |")
    return "\n".join(out)


def verdict(d: dict) -> tuple[str, list[str]]:
    """Evaluate the E003 decision rule exactly as pre-registered."""
    target = ENV.TARGET_USD_PER_DAY
    lines = []
    best_c = max((a for a in d["arms"] if a["width"]),
                 key=lambda a: a["total"]["per_day_central"])
    best_o = max((a for a in d["arms"] if a["width"]),
                 key=lambda a: a["total"]["per_day_optimistic"])
    bc = best_c["total"]["per_day_central"]
    bo = best_o["total"]["per_day_optimistic"]
    months = best_c["months"]
    wins = sum(1 for m in months.values() if m["per_day_central"] > 0)
    lines.append(f"best central arm: {best_c['arm']} at {bc:+.4f}/day "
                 f"(target {target:+.4f})")
    lines.append(f"  monthly sub-windows positive under central: {wins}/{len(months)}")
    lines.append(f"best optimistic arm: {best_o['arm']} at {bo:+.4f}/day")

    if bc >= target and wins > len(months) / 2:
        lines.append("SUPPORTED clause: central >= target AND positive in a "
                     "majority of monthly sub-windows")
        return "SUPPORTED", lines
    if bo < 0.0:
        lines.append("REFUTED clause: no arm reaches $0/day even under the "
                     "OPTIMISTIC envelope")
        return "REFUTED", lines
    lines.append("INCONCLUSIVE clause: profitable somewhere but below target, "
                 "or envelope-dependent in sign "
                 f"(optimistic best {bo:+.4f} >= 0 > central best vs target)")
    return "INCONCLUSIVE", lines


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="lag0h_rh1h")
    ap.add_argument("--verdict", action="store_true")
    args = ap.parse_args()
    d = load(args.run)

    w = d["window"]
    print(f"## run `{args.run}` — {w['start']} -> {w['end']}, "
          f"{w['hours']/24:.2f} days, {w['n_swaps']:,} swaps")
    print(f"cost model {d['cost_model_version']}, envelope {d['envelope_version']}, "
          f"detect lag {d['policy']['detect_lag_hours']}h, "
          f"rehedge {d['policy']['rehedge_hours']}h\n")
    print("### Envelope\n")
    print("| Point | maker share (notional) | fee bps | slippage bps | chase bps | "
          "total bps |")
    print("|---|---:|---:|---:|---:|---:|")
    for p in d["envelope"]:
        print(f"| {p['name']} | {p['maker_share_notional']*100:.2f}% | "
              f"{p['fee_bps']:.3f} | {p['slippage_bps']:.1f} | {p['chase_bps']:.1f} | "
              f"**{p['total_bps']:.3f}** |")
    print("\n### Width / PnL frontier ($/day, full window)\n")
    print(frontier_table(d))
    print("\n### Monthly sub-windows, central envelope ($/day)\n")
    print(monthly_table(d, "central"))
    print("\n### Monthly sub-windows, optimistic envelope ($/day)\n")
    print(monthly_table(d, "optimistic"))
    print("\n### Fees against hedged gamma ($/day)\n")
    print(gamma_table(d))
    print("\n### Cost attribution (full window, USD)\n")
    print(attribution_table(d))
    print("\n### Turnover\n")
    print(notional_table(d))
    if args.verdict:
        v, lines = verdict(d)
        print(f"\n### Decision rule\n\n**{v}**\n")
        for ln in lines:
            print(f"- {ln}")
    gaps = {a["arm"]: a["checks"].get("lp_value_abs_gap_usd")
            for a in d["arms"] if a["checks"]}
    print(f"\nworst accounting-decomposition gap across arms: "
          f"${max(gaps.values()):.2e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
