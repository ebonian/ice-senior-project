"""
Phase 7 — Compare multiple strategies side-by-side.

Reads per-strategy outputs written under results/<strategy>/ by the
run_all_strategies.py orchestrator (each one produced by 03 → 04 → 05)
and writes a single comparison view:

    results/comparison.md           side-by-side metrics table + ranking
    results/comparison_summary.json structured summary (for CI / tooling)
    plots/comparison.png            overlaid equity curves + PnL bar chart

Usage (from backtest_model_server/):
    python scripts/06_compare_strategies.py
    python scripts/06_compare_strategies.py --config config/backtest_config.yaml
"""

import sys
import json
import math
import logging
import argparse
from pathlib import Path

import yaml
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.ticker import FuncFormatter

SCRIPT_DIR = Path(__file__).resolve().parent
BASE_DIR   = SCRIPT_DIR.parent

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


USD_FMT = FuncFormatter(lambda x, _: f"${x:,.0f}")


def load_config(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def resolve_strategies(cfg: dict) -> list[str]:
    s = cfg.get("strategies")
    if isinstance(s, list) and s:
        return [str(x) for x in s]
    single = cfg.get("strategy")
    return [str(single)] if single else []


def _fmt(val, spec: str) -> str:
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return "—"
    prefix = ""
    suffix = ""
    s = spec
    if s.startswith("$"):
        prefix = "$"
        s = s[1:]
    if s.endswith("%"):
        suffix = "%"
        s = s[:-1]
    return f"{prefix}{val:{s}}{suffix}"


# ---------------------------------------------------------------------------
# Load per-strategy artifacts
# ---------------------------------------------------------------------------

def load_strategy_bundle(results_dir: Path, strategy: str) -> dict | None:
    sdir = results_dir / strategy
    metrics_path = sdir / "metrics.json"
    trace_path   = sdir / "trace_df.parquet"
    log_path     = sdir / "inference_log.csv"
    if not metrics_path.exists():
        log.warning("Missing metrics.json for %s (expected %s)", strategy, metrics_path)
        return None
    if not trace_path.exists():
        log.warning("Missing trace_df.parquet for %s (expected %s)", strategy, trace_path)
        return None
    with open(metrics_path, encoding="utf-8") as f:
        metrics = json.load(f)
    trace = pd.read_parquet(trace_path)
    infer_log = pd.read_csv(log_path) if log_path.exists() else pd.DataFrame()
    return {
        "strategy":  strategy,
        "metrics":   metrics,
        "trace":     trace,
        "infer_log": infer_log,
        "results_dir": sdir,
    }


# ---------------------------------------------------------------------------
# Plot
# ---------------------------------------------------------------------------

PALETTE = ["#4C72B0", "#C44E52", "#55A868", "#8172B2", "#DD8452", "#937860"]


def plot_comparison(bundles: list[dict], plots_dir: Path, initial_cap: float) -> Path:
    fig = plt.figure(figsize=(16, 9))
    gs  = fig.add_gridspec(2, 2, height_ratios=[2, 1])
    ax_eq    = fig.add_subplot(gs[0, :])
    ax_pnl   = fig.add_subplot(gs[1, 0])
    ax_stats = fig.add_subplot(gs[1, 1])
    fig.suptitle("Strategy Comparison", fontsize=14, fontweight="bold")

    # 1 — overlaid equity curves
    hodl_drawn = False
    for i, b in enumerate(bundles):
        tr  = b["trace"]
        ts  = pd.to_datetime(tr["timestamp"], errors="coerce")
        pv  = tr["portfolio_value"]
        color = PALETTE[i % len(PALETTE)]
        ax_eq.plot(ts, pv, color=color, linewidth=1.4, label=b["strategy"], zorder=3 + i)

        if not hodl_drawn:
            hodl_m = b["metrics"].get("hodl", {})
            hodl_fv = hodl_m.get("final_pv")
            if hodl_fv:
                hodl_line = np.linspace(initial_cap, hodl_fv, len(ts))
                ax_eq.plot(ts, hodl_line, color="#888888", linewidth=1.0,
                           linestyle="--", alpha=0.7, label=f"HODL ${hodl_fv:,.0f}")
            hodl_drawn = True

    ax_eq.axhline(initial_cap, color="#8C8C8C", linestyle=":", linewidth=1.0,
                  label=f"Initial ${initial_cap:,.0f}")
    ax_eq.set_title("Equity Curves")
    ax_eq.set_ylabel("Portfolio Value (USD)")
    ax_eq.yaxis.set_major_formatter(USD_FMT)
    ax_eq.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))
    ax_eq.legend(fontsize=9, loc="upper left")
    ax_eq.grid(alpha=0.2)

    # 2 — final PnL bar chart (model vs HODL vs cash per strategy)
    labels   = [b["strategy"] for b in bundles]
    x        = np.arange(len(labels))
    bar_w    = 0.28
    pnl_m    = [b["metrics"].get("model_server", {}).get("pnl", 0.0) or 0.0 for b in bundles]
    pnl_c    = [b["metrics"].get("always_cash",  {}).get("pnl", 0.0) or 0.0 for b in bundles]
    pnl_h    = [b["metrics"].get("hodl",         {}).get("pnl", 0.0) or 0.0 for b in bundles]

    ax_pnl.bar(x - bar_w, pnl_m, bar_w, label="Model",      color="#4C72B0")
    ax_pnl.bar(x,         pnl_c, bar_w, label="Always-Cash", color="#AAAAAA")
    ax_pnl.bar(x + bar_w, pnl_h, bar_w, label="HODL",       color="#C44E52")
    ax_pnl.axhline(0, color="black", linewidth=0.8)
    ax_pnl.set_xticks(x)
    ax_pnl.set_xticklabels(labels, rotation=15, fontsize=8)
    ax_pnl.set_title("PnL vs Baselines")
    ax_pnl.set_ylabel("PnL (USD)")
    ax_pnl.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"${v:+,.1f}"))
    ax_pnl.legend(fontsize=8)
    ax_pnl.grid(axis="y", alpha=0.2)

    # 3 — Sharpe / MaxDD / trade-count table
    cell_text = []
    for b in bundles:
        m = b["metrics"].get("model_server", {})
        cell_text.append([
            f"{m.get('pnl', 0.0):+.2f}",
            f"{m.get('sharpe_ratio', 0.0):.3f}",
            f"{m.get('max_drawdown_pct', 0.0):.2f}%",
            f"{int(m.get('trade_count', 0) or 0)}",
            f"{m.get('in_range_pct', 0.0):.1f}%",
        ])
    ax_stats.axis("off")
    table = ax_stats.table(
        cellText=cell_text,
        rowLabels=labels,
        colLabels=["PnL $", "Sharpe", "MaxDD", "Trades", "InRange%"],
        loc="center",
        cellLoc="center",
    )
    table.auto_set_font_size(False)
    table.set_fontsize(9)
    table.scale(1.0, 1.5)
    ax_stats.set_title("Model Metrics")

    out_path = plots_dir / "comparison.png"
    fig.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    log.info("Saved %s", out_path)
    return out_path


# ---------------------------------------------------------------------------
# Summary table
# ---------------------------------------------------------------------------

METRIC_ROWS = [
    ("PnL ($)",          "pnl",                    "$.2f"),
    ("Final PV ($)",     "final_pv",                "$.2f"),
    ("Sharpe Ratio",     "sharpe_ratio",            ".3f"),
    ("Max Drawdown (%)", "max_drawdown_pct",        ".2f%"),
    ("Trade Count",      "trade_count",             "d"),
    ("Enter",            "enter_count",             "d"),
    ("Recenter",         "recenter_count",          "d"),
    ("Fee Total ($)",    "fee_total_usd",           "$.2f"),
    ("Hedge PnL ($)",    "hedge_pnl_total_usd",     "$.2f"),
    ("Funding ($)",      "funding_cost_total_usd",  "$.2f"),
    ("TX Cost ($)",      "tx_cost_total_usd",       "$.2f"),
    ("Swing PnL ($)",    "raw_swing_pnl_usd",       "$.2f"),
    ("Cash %",           "cash_pct",                ".1f%"),
    ("In-Range %",       "in_range_pct",            ".1f%"),
    ("OOR %",            "oor_pct",                 ".1f%"),
    ("Win Rate (%)",     "win_rate_pct",            ".1f%"),
    ("Avg Trade (hrs)",  "avg_trade_hours",         ".1f"),
]


def build_markdown(bundles: list[dict], cfg: dict, initial_cap: float,
                   plot_path: Path | None) -> tuple[str, dict]:
    start = cfg["start_date"]
    end   = cfg["end_date"]

    lines: list[str] = [
        f"# Strategy Comparison: {start} → {end}",
        "",
        f"Initial capital: **${initial_cap:,.0f}**  |  "
        f"Strategies: {len(bundles)}  |  "
        f"Server: `{cfg.get('server_url', '')}`",
        "",
    ]

    # Ranking by model PnL (desc)
    ranked = sorted(
        bundles,
        key=lambda b: (b["metrics"].get("model_server", {}).get("pnl") or 0.0),
        reverse=True,
    )

    lines += ["## Ranking (by model PnL)", ""]
    lines += ["| Rank | Strategy | Model PnL | vs HODL | vs Cash | Sharpe | MaxDD |",
              "|------|----------|-----------|---------|---------|--------|-------|"]
    for i, b in enumerate(ranked, 1):
        m = b["metrics"].get("model_server", {})
        h = b["metrics"].get("hodl",         {})
        c = b["metrics"].get("always_cash",  {})
        pnl = m.get("pnl") or 0.0
        hodl_pnl = h.get("pnl") or 0.0
        cash_pnl = c.get("pnl") or 0.0
        lines.append(
            f"| {i} | `{b['strategy']}` | "
            f"${pnl:+.2f} | ${pnl - hodl_pnl:+.2f} | ${pnl - cash_pnl:+.2f} | "
            f"{m.get('sharpe_ratio', 0.0):.3f} | {m.get('max_drawdown_pct', 0.0):.2f}% |"
        )
    lines.append("")

    # Full metric matrix
    header = "| Metric | " + " | ".join(f"`{b['strategy']}`" for b in bundles) + " |"
    sep    = "|--------|" + "|".join(["---"] * len(bundles)) + "|"
    lines += ["## Model Metrics (side-by-side)", "", header, sep]
    for label, key, spec in METRIC_ROWS:
        row = f"| {label} |"
        for b in bundles:
            row += f" {_fmt(b['metrics'].get('model_server', {}).get(key), spec)} |"
        lines.append(row)
    lines.append("")

    # Baselines — one table per baseline, identical across strategies but
    # recorded for traceability.
    lines += ["## Baselines (HODL / Always-Cash)", ""]
    lines += ["| Strategy | HODL PnL | HODL Sharpe | Cash PnL | Cash Sharpe |",
              "|----------|----------|-------------|----------|-------------|"]
    for b in bundles:
        h = b["metrics"].get("hodl",        {})
        c = b["metrics"].get("always_cash", {})
        lines.append(
            f"| `{b['strategy']}` | "
            f"${h.get('pnl', 0.0):+.2f} | {h.get('sharpe_ratio', 0.0):.3f} | "
            f"${c.get('pnl', 0.0):+.2f} | {c.get('sharpe_ratio', 0.0):.3f} |"
        )
    lines.append("")

    if plot_path:
        lines += [f"![Comparison plot]({plot_path.as_posix()})", ""]

    # Structured summary for JSON dump
    summary = {
        "config": {
            "start_date":          start,
            "end_date":            end,
            "initial_capital_usd": initial_cap,
            "server_url":          cfg.get("server_url"),
            "strategies":          [b["strategy"] for b in bundles],
        },
        "ranked": [
            {
                "rank":     i,
                "strategy": b["strategy"],
                "pnl":      b["metrics"].get("model_server", {}).get("pnl"),
                "sharpe":   b["metrics"].get("model_server", {}).get("sharpe_ratio"),
                "max_drawdown_pct":
                    b["metrics"].get("model_server", {}).get("max_drawdown_pct"),
                "trade_count":
                    b["metrics"].get("model_server", {}).get("trade_count"),
            }
            for i, b in enumerate(ranked, 1)
        ],
        "per_strategy": {
            b["strategy"]: b["metrics"] for b in bundles
        },
    }

    return "\n".join(lines) + "\n", summary


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Compare strategies run by run_all_strategies.py")
    parser.add_argument("--config", default=str(BASE_DIR / "config" / "backtest_config.yaml"))
    parser.add_argument("--strategies", nargs="+", default=None,
                        help="Override the strategies list from config.")
    args = parser.parse_args()

    cfg         = load_config(Path(args.config))
    initial_cap = cfg.get("initial_capital_usd", 1000.0)
    results_dir = BASE_DIR / cfg.get("output_dir", "results")
    plots_dir   = BASE_DIR / cfg.get("plots_dir", "plots")
    plots_dir.mkdir(parents=True, exist_ok=True)

    strategies = args.strategies or resolve_strategies(cfg)
    if not strategies:
        log.error("No strategies configured. Set `strategies:` in config or pass --strategies.")
        sys.exit(1)

    log.info("Comparing %d strategies: %s", len(strategies), ", ".join(strategies))

    bundles: list[dict] = []
    for s in strategies:
        b = load_strategy_bundle(results_dir, s)
        if b is not None:
            bundles.append(b)

    if len(bundles) < 2:
        log.error(
            "Need ≥2 strategies with results to compare; found %d. "
            "Run run_all_strategies.py first.",
            len(bundles),
        )
        sys.exit(1)

    plot_path = plot_comparison(bundles, plots_dir, initial_cap)
    md, summary = build_markdown(bundles, cfg, initial_cap, plot_path)

    md_path = results_dir / "comparison.md"
    md_path.parent.mkdir(parents=True, exist_ok=True)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md)
    log.info("Saved %s", md_path)

    json_path = results_dir / "comparison_summary.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, default=str)
    log.info("Saved %s", json_path)

    print("\n" + md)


if __name__ == "__main__":
    main()
