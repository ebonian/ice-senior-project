"""
Phase 5 — Compute performance metrics and baseline comparison.

Reads trace_df.parquet produced by 03_run_infer_backtest.py,
computes the full metric suite, runs baselines, and writes:
  results/metrics.json     all metrics as JSON
  results/summary.md       human-readable comparison table

Usage (from backtest_model_server/):
    python scripts/04_compute_metrics.py
    python scripts/04_compute_metrics.py --config config/backtest_config.yaml
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

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
BASE_DIR   = SCRIPT_DIR.parent
LLAMINET   = BASE_DIR.parent.parent
SIM14_DIR  = LLAMINET / "research" / "research" / "simulation_14"

sys.path.insert(0, str(SIM14_DIR))
sys.path.insert(0, str(SIM14_DIR / "training"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


def load_config(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# trace_metrics — local implementation (fallback if simulation_14 unavailable)
# ---------------------------------------------------------------------------

def trace_metrics(trace_df: pd.DataFrame) -> dict:
    """
    Compute standard performance metrics from a simulation trace_df.
    Compatible with the schema from hedged_hierarchical_policy.py::trace_metrics.
    """
    if trace_df.empty:
        return {}

    final_pv = float(trace_df["portfolio_value"].iloc[-1])
    if "initial_capital_usd" in trace_df.columns and not trace_df["initial_capital_usd"].isna().all():
        initial_capital = float(trace_df["initial_capital_usd"].iloc[0])
    else:
        initial_capital = float(trace_df["portfolio_value"].iloc[0])
    pnl            = final_pv - initial_capital

    cash_pct = float(trace_df["is_cash_after"].mean() * 100.0)
    oor_pct  = float((trace_df["position_state"] == "lp_oor").mean() * 100.0)

    ea = trace_df["effective_action"]
    enter_count   = int(ea.str.startswith("enter_w").sum())
    recenter_count= int(ea.str.startswith("recenter").sum())
    exit_count    = int((ea == "exit_to_cash").sum())
    trade_count   = enter_count + recenter_count + exit_count

    # Fee, hedge, funding, and PnL breakdown
    fee_total = float(trace_df.get("fee_usd", pd.Series(dtype=float)).fillna(0.0).sum())
    tx_total  = float(trace_df.get("tx_cost_usd", pd.Series(dtype=float)).fillna(0.0).sum())
    hedge_pnl_total = float(
        trace_df.get("hedge_pnl_usd", pd.Series(dtype=float)).fillna(0.0).sum()
    )
    funding_total = float(
        trace_df.get("funding_cost_usd", pd.Series(dtype=float)).fillna(0.0).sum()
    )

    if "gross_fee_carry_usd" in trace_df.columns:
        gross_fee_carry_usd = float(trace_df["gross_fee_carry_usd"].sum())
    else:
        gross_fee_carry_usd = fee_total - funding_total - tx_total

    raw_swing_pnl_usd = float(
        trace_df.get("raw_swing_pnl_usd", pd.Series(dtype=float)).fillna(0.0).sum()
    )

    il_col = trace_df.get("raw_boundary_il_usd", pd.Series(dtype=float)).fillna(0.0)
    raw_boundary_il_last_usd    = float(il_col.iloc[-1]) if len(il_col) > 0 else 0.0
    raw_boundary_il_abs_max_usd = float(il_col.abs().max()) if len(il_col) > 0 else 0.0

    mode = "none"
    if "hedge_accounting_mode" in trace_df.columns and len(trace_df) > 0:
        mode = str(trace_df["hedge_accounting_mode"].iloc[0])

    return {
        "final_pv":                   final_pv,
        "pnl":                        pnl,
        "initial_capital":            initial_capital,
        "cash_pct":                   cash_pct,
        "oor_pct":                    oor_pct,
        "trade_count":                trade_count,
        "enter_count":                enter_count,
        "recenter_count":             recenter_count,
        "exit_count":                 exit_count,
        "fee_total_usd":              fee_total,
        "hedge_pnl_total_usd":        hedge_pnl_total,
        "funding_cost_total_usd":     funding_total,
        "tx_cost_total_usd":          tx_total,
        "gross_fee_carry_usd":        gross_fee_carry_usd,
        "raw_swing_pnl_usd":          raw_swing_pnl_usd,
        "raw_boundary_il_last_usd":   raw_boundary_il_last_usd,
        "raw_boundary_il_abs_max_usd":raw_boundary_il_abs_max_usd,
        "hedge_accounting_mode":      mode,
    }


# ---------------------------------------------------------------------------
# Extended metrics
# ---------------------------------------------------------------------------

def max_drawdown(portfolio_values: pd.Series) -> float:
    """Peak-to-trough maximum drawdown (fraction, negative)."""
    roll_max = portfolio_values.cummax()
    drawdown = (portfolio_values - roll_max) / roll_max
    return float(drawdown.min())


def sharpe_ratio(portfolio_values: pd.Series, periods_per_year: float = 8760.0) -> float:
    """Annualised Sharpe ratio from hourly portfolio values (rf=0)."""
    returns = portfolio_values.pct_change().dropna()
    if returns.std() == 0:
        return 0.0
    return float(returns.mean() / returns.std() * math.sqrt(periods_per_year))


def win_rate(trace_df: pd.DataFrame) -> float:
    """Fraction of closed trades (enter→recenter or enter→exit) with positive swing PnL."""
    if "raw_swing_pnl_usd" not in trace_df.columns:
        return float("nan")
    # Mark trade boundaries: any rebalance or exit action
    is_trade_close = trace_df["effective_action"].str.startswith(("recenter", "exit_to_cash"))
    trades = trace_df.loc[is_trade_close, "raw_swing_pnl_usd"]
    if trades.empty:
        return float("nan")
    return float((trades > 0).mean())


def avg_trade_duration(trace_df: pd.DataFrame) -> float:
    """Mean hours between rebalances for in-position steps."""
    if "hours_since_rebalance" not in trace_df.columns:
        return float("nan")
    in_pos = trace_df[trace_df["position_state"] != "cash"]
    if in_pos.empty:
        return float("nan")
    # Each rebalance resets hours_since_rebalance to 0; the max just before
    # next rebalance is the trade duration.
    rebalance_steps = trace_df["effective_action"].str.startswith(("recenter", "exit_to_cash"))
    durations = trace_df.loc[rebalance_steps, "hours_since_rebalance"]
    if durations.empty:
        return float("nan")
    return float(durations.mean())


def compute_extended_metrics(trace_df: pd.DataFrame) -> dict:
    pv = trace_df["portfolio_value"]
    wr = win_rate(trace_df)
    return {
        "max_drawdown_pct":   max_drawdown(pv) * 100.0,
        "sharpe_ratio":       sharpe_ratio(pv),
        "win_rate_pct":       wr * 100.0 if not math.isnan(wr) else None,
        "avg_trade_hours":    avg_trade_duration(trace_df),
        "total_steps":        len(trace_df),
        "total_hours":        len(trace_df),  # cadence_hours=1
        "in_range_pct":       float((trace_df["position_state"] == "lp_in_range").mean() * 100.0),
    }


# ---------------------------------------------------------------------------
# Baselines
# ---------------------------------------------------------------------------

def build_always_cash_trace(trace_df: pd.DataFrame, initial_capital: float) -> pd.DataFrame:
    """Always-cash baseline: PnL = 0, stays at initial_capital throughout."""
    df = trace_df[["step", "timestamp", "reference_date", "current_price"]].copy()
    df["portfolio_value"]    = initial_capital
    df["effective_action"]   = "hold"
    df["action_label"]       = "HOLD"
    df["position_state"]     = "cash"
    df["is_cash_after"]      = 1
    df["fee_usd"]            = 0.0
    df["tx_cost_usd"]        = 0.0
    df["lp_value_change_usd"]= 0.0
    df["gross_fee_carry_usd"]= 0.0
    df["raw_swing_pnl_usd"]  = 0.0
    df["raw_boundary_il_usd"]= 0.0
    df["hedge_accounting_mode"] = "none"
    df["hours_since_rebalance"] = range(len(df))
    return df


def build_hodl_trace(trace_df: pd.DataFrame, initial_capital: float) -> pd.DataFrame:
    """HODL baseline: buy ETH at first price, hold throughout."""
    df = trace_df[["step", "timestamp", "reference_date", "current_price"]].copy()

    first_price = df["current_price"].iloc[0]
    if first_price <= 0:
        df["portfolio_value"] = initial_capital
    else:
        eth_holdings = initial_capital / first_price
        df["portfolio_value"] = df["current_price"] * eth_holdings

    df["effective_action"]    = "hold"
    df["action_label"]        = "HOLD"
    df["position_state"]      = "lp_in_range"   # treated as full ETH position
    df["is_cash_after"]       = 0
    df["fee_usd"]             = 0.0
    df["tx_cost_usd"]         = 0.0
    df["lp_value_change_usd"] = df["portfolio_value"].diff().fillna(0.0)
    df["gross_fee_carry_usd"] = 0.0
    df["raw_swing_pnl_usd"]   = df["lp_value_change_usd"]
    df["raw_boundary_il_usd"] = 0.0
    df["hedge_accounting_mode"] = "none"
    df["hours_since_rebalance"] = range(len(df))
    return df


# ---------------------------------------------------------------------------
# Try importing simulation_14 trace_metrics (prefer over local fallback)
# ---------------------------------------------------------------------------

def _try_import_trace_metrics():
    try:
        from hedged_hierarchical_policy import trace_metrics as sim_trace_metrics
        log.info("Using trace_metrics from simulation_14")
        return sim_trace_metrics
    except ImportError:
        log.info("simulation_14 not importable — using local trace_metrics implementation")
        return trace_metrics


def _sanitize_for_json(value):
    if isinstance(value, dict):
        return {k: _sanitize_for_json(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_sanitize_for_json(v) for v in value]
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


def load_trace(results_dir: Path) -> pd.DataFrame:
    parquet_path = results_dir / "trace_df.parquet"
    csv_path = results_dir / "local_kongtrae_trace.csv"
    if parquet_path.exists():
        return pd.read_parquet(parquet_path)
    if csv_path.exists():
        return pd.read_csv(csv_path)
    log.error(
        "No trace found. Expected %s or %s — run 03_run_infer_backtest.py or 09_run_local_kongtrae_backtest.py first",
        parquet_path,
        csv_path,
    )
    sys.exit(1)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Compute backtest metrics and baseline comparison")
    parser.add_argument("--config", default=str(BASE_DIR / "config" / "backtest_config.yaml"))
    args = parser.parse_args()

    cfg         = load_config(Path(args.config))
    initial_cap = cfg.get("initial_capital_usd", 1000.0)
    results_dir = BASE_DIR / cfg.get("output_dir", "results")

    trace_df = load_trace(results_dir)
    log.info("Loaded trace_df: %d rows", len(trace_df))

    if trace_df.empty:
        log.error("trace_df is empty")
        sys.exit(1)

    # ------------------------------------------------------------------
    # Model metrics
    # ------------------------------------------------------------------
    _tm = _try_import_trace_metrics()
    model_base   = _tm(trace_df)
    model_ext    = compute_extended_metrics(trace_df)
    model_metrics = {**model_base, **model_ext}
    if "final_pv" in model_metrics:
        model_metrics["initial_capital"] = float(initial_cap)
        model_metrics["pnl"] = float(model_metrics["final_pv"] - initial_cap)
    log.info("Model PnL: $%.2f  Sharpe: %.3f  MaxDD: %.1f%%",
             model_metrics.get("pnl", 0),
             model_metrics.get("sharpe_ratio", 0),
             model_metrics.get("max_drawdown_pct", 0))

    # ------------------------------------------------------------------
    # Baselines
    # ------------------------------------------------------------------
    cash_trace = build_always_cash_trace(trace_df, initial_cap)
    hodl_trace = build_hodl_trace(trace_df, initial_cap)

    cash_base    = _tm(cash_trace)
    cash_ext     = compute_extended_metrics(cash_trace)
    cash_metrics = {**cash_base, **cash_ext}
    if "final_pv" in cash_metrics:
        cash_metrics["initial_capital"] = float(initial_cap)
        cash_metrics["pnl"] = float(cash_metrics["final_pv"] - initial_cap)

    hodl_base    = _tm(hodl_trace)
    hodl_ext     = compute_extended_metrics(hodl_trace)
    hodl_metrics = {**hodl_base, **hodl_ext}
    if "final_pv" in hodl_metrics:
        hodl_metrics["initial_capital"] = float(initial_cap)
        hodl_metrics["pnl"] = float(hodl_metrics["final_pv"] - initial_cap)

    log.info("HODL PnL: $%.2f  Sharpe: %.3f", hodl_metrics.get("pnl", 0), hodl_metrics.get("sharpe_ratio", 0))

    # ------------------------------------------------------------------
    # Save JSON
    # ------------------------------------------------------------------
    output = {
        "config": {
            "start_date":          cfg["start_date"],
            "end_date":            cfg["end_date"],
            "initial_capital_usd": initial_cap,
            "strategy":            cfg.get("strategy", "default"),
        },
        "model_server": model_metrics,
        "always_cash":  cash_metrics,
        "hodl":         hodl_metrics,
    }

    metrics_path = results_dir / "metrics.json"
    with open(metrics_path, "w", encoding="utf-8") as f:
        json.dump(_sanitize_for_json(output), f, indent=2, allow_nan=False)
    log.info("Metrics saved to %s", metrics_path)

    # ------------------------------------------------------------------
    # Summary table (Markdown)
    # ------------------------------------------------------------------
    rows = [
        ("PnL ($)",           "pnl",                   "$.2f"),
        ("Final PV ($)",      "final_pv",               "$.2f"),
        ("Cash %",            "cash_pct",               ".1f%"),
        ("OOR %",             "oor_pct",                ".1f%"),
        ("In-Range %",        "in_range_pct",           ".1f%"),
        ("Trade Count",       "trade_count",            "d"),
        ("Enter Count",       "enter_count",            "d"),
        ("Recenter Count",    "recenter_count",         "d"),
        ("Fee Total ($)",     "fee_total_usd",          "$.2f"),
        ("Hedge PnL ($)",     "hedge_pnl_total_usd",    "$.2f"),
        ("Funding Cost ($)",  "funding_cost_total_usd", "$.2f"),
        ("TX Cost ($)",       "tx_cost_total_usd",      "$.2f"),
        ("Net Fee Carry ($)", "gross_fee_carry_usd",    "$.2f"),
        ("Swing PnL ($)",    "raw_swing_pnl_usd",       "$.2f"),
        ("Max Drawdown (%)",  "max_drawdown_pct",       ".2f%"),
        ("Sharpe Ratio",      "sharpe_ratio",           ".3f"),
        ("Win Rate (%)",      "win_rate_pct",           ".1f%"),
        ("Avg Trade (hrs)",   "avg_trade_hours",        ".1f"),
    ]

    def fmt(val, fmt_spec):
        if val is None or (isinstance(val, float) and math.isnan(val)):
            return "—"
        prefix = ""
        suffix = ""
        spec = fmt_spec
        if spec.startswith("$"):
            prefix = "$"
            spec = spec[1:]
        if spec.endswith("%"):
            suffix = "%"
            spec = spec[:-1]
        return f"{prefix}{val:{spec}}{suffix}"

    lines = [
        f"# Backtest Results: {cfg['start_date']} → {cfg['end_date']}",
        f"Strategy: `{cfg.get('strategy', 'default')}`  |  "
        f"Initial capital: ${initial_cap:,.0f}  |  "
        f"Steps: {len(trace_df)}",
        "",
        "| Metric | Model Server | Always-Cash | HODL |",
        "|--------|-------------|-------------|------|",
    ]
    for label, key, fmt_spec in rows:
        m_val = model_metrics.get(key)
        c_val = cash_metrics.get(key)
        h_val = hodl_metrics.get(key)
        lines.append(f"| {label} | {fmt(m_val, fmt_spec)} | {fmt(c_val, fmt_spec)} | {fmt(h_val, fmt_spec)} |")

    lines += [
        "",
        "## Model vs Baselines",
        f"- vs Always-Cash: {'BEATS' if model_metrics.get('pnl', 0) > 0 else 'UNDERPERFORMS'} "
        f"by ${model_metrics.get('pnl', 0) - cash_metrics.get('pnl', 0):+.2f}",
        f"- vs HODL: {'BEATS' if model_metrics.get('pnl', 0) > hodl_metrics.get('pnl', 0) else 'UNDERPERFORMS'} "
        f"by ${model_metrics.get('pnl', 0) - hodl_metrics.get('pnl', 0):+.2f}",
    ]

    summary_path = results_dir / "summary.md"
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    log.info("Summary saved to %s", summary_path)

    # Print to console
    print("\n" + "\n".join(lines))
    print(f"\nRun 05_plot_dashboard.py to generate visualisations.")


if __name__ == "__main__":
    main()
