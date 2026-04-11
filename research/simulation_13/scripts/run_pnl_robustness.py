#!/usr/bin/env python3
"""
Run PnL robustness: multiple evaluation periods and all three models (DQN, PPO, LSTM).
Loads data once per (period, model) and prints a summary table.

Usage (from repo root):
    .venv/bin/python research/simulation_13/scripts/run_pnl_robustness.py
    .venv/bin/python research/simulation_13/scripts/run_pnl_robustness.py --capital 100 --gas-cost 0.02
"""

import os
import sys
import argparse

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SIM_DIR = os.path.normpath(os.path.join(SCRIPT_DIR, ".."))
REPO_ROOT = os.path.normpath(os.path.join(SCRIPT_DIR, "..", "..", ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from compute_pnl import run_fee_calculation, REPO_ROOT, SIM_DIR

# Robustness: different start dates (periods) and all models
PERIODS = ["2025-06-01", "2025-10-01", "2026-01-01"]
MODELS = ["dqn", "ppo", "lstm"]


def main():
    parser = argparse.ArgumentParser(description="PnL robustness: multiple periods × models")
    parser.add_argument("--downloaded-dir", default=os.path.join(REPO_ROOT, "downloaded_data_csv"))
    parser.add_argument("--model-dir", default=os.path.join(SIM_DIR, "run_004", "models"))
    parser.add_argument("--capital", type=float, default=100.0)
    parser.add_argument("--gas-cost", type=float, default=0.02)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--quick", action="store_true", help="Fewer runs: 2 periods × 2 models (2025-10-01, 2026-01-01 × dqn, ppo)")
    args = parser.parse_args()

    periods = ["2025-10-01", "2026-01-01"] if args.quick else PERIODS
    models = ["dqn", "ppo"] if args.quick else MODELS
    if args.quick:
        print("Quick mode: 2 periods × 2 models\n")

    model_dir = args.model_dir
    if not os.path.isabs(model_dir):
        model_dir = os.path.normpath(os.path.join(SIM_DIR, model_dir))
    if not os.path.exists(model_dir):
        model_dir = os.path.join(REPO_ROOT, "kongtrae", "models")
        print(f"⚠️  run_004 models not found, using {model_dir}\n")

    results = []
    for test_start in periods:
        for model_name in models:
            print(f"\n{'='*60}")
            print(f"  {model_name.upper()} | from {test_start}")
            print(f"{'='*60}")
            try:
                out = run_fee_calculation(
                    args.downloaded_dir,
                    model_name,
                    args.capital,
                    model_dir,
                    args.device,
                    mode="test",
                    gas_cost=args.gas_cost,
                    test_start=test_start,
                )
                out["model"] = model_name
                out["test_start"] = test_start
                results.append(out)
            except Exception as e:
                print(f"  ERROR: {e}")
                results.append({
                    "model": model_name,
                    "test_start": test_start,
                    "period_start": None,
                    "period_end": None,
                    "test_days": 0,
                    "net_pnl": None,
                    "rebalance_count": 0,
                    "agent_fees": None,
                    "lvr": None,
                })

    # Summary table
    print("\n\n" + "=" * 100)
    print("  ROBUSTNESS SUMMARY (Net PnL, $/day, APR across periods and models)")
    print("=" * 100)
    capital = args.capital
    fmt = "{:<12} {:<6} {:>10} {:>12} {:>10} {:>8} {:>10} {:>10}"
    print(fmt.format("Period", "Model", "Net PnL", "Net $/day", "APR %", "Days", "Rebal", "Fees"))
    print("-" * 100)
    for r in results:
        period = r.get("test_start", "?")
        model = r.get("model", "?")
        net = r.get("net_pnl")
        days = r.get("test_days") or 1
        rebal = r.get("rebalance_count", 0)
        fees = r.get("agent_fees")
        if net is not None and days > 0:
            pnl_day = net / days
            apr = (net / days) * 365 / capital * 100
            print(fmt.format(period, model.upper(), f"${net:.2f}", f"${pnl_day:.2f}", f"{apr:.1f}", f"{days:.0f}", rebal, f"${fees:.2f}" if fees is not None else "?"))
        else:
            print(fmt.format(period, model.upper(), "FAIL", "-", "-", "-", rebal, "-"))
    print("=" * 100)

    # Write same summary to run_004 for later reference
    report_path = os.path.join(SIM_DIR, "run_004", "pnl_robustness_report.txt")
    try:
        with open(report_path, "w") as f:
            f.write("PnL robustness summary (capital=${:.0f}, gas=${:.2f}/rebalance)\n\n".format(args.capital, args.gas_cost))
            f.write(fmt.format("Period", "Model", "Net PnL", "Net $/day", "APR %", "Days", "Rebal", "Fees") + "\n")
            f.write("-" * 100 + "\n")
            for r in results:
                period = r.get("test_start", "?")
                model = r.get("model", "?")
                net = r.get("net_pnl")
                days = r.get("test_days") or 1
                rebal = r.get("rebalance_count", 0)
                fees = r.get("agent_fees")
                if net is not None and days > 0:
                    pnl_day = net / days
                    apr = (net / days) * 365 / capital * 100
                    f.write(fmt.format(period, model.upper(), f"${net:.2f}", f"${pnl_day:.2f}", f"{apr:.1f}", f"{days:.0f}", rebal, f"${fees:.2f}" if fees is not None else "?") + "\n")
                else:
                    f.write(fmt.format(period, model.upper(), "FAIL", "-", "-", "-", rebal, "-") + "\n")
        print(f"\nReport written to {report_path}")
    except Exception as e:
        print(f"\nCould not write report: {e}")


if __name__ == "__main__":
    main()
