"""
Evaluate an existing Kongtrae three-head v2 DQN model on walk-forward folds.

This is for checking the shipped model without retraining it. It uses the same
environment/accounting path as the v2 walk-forward trainer.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from statistics import mean, median

PACKAGE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKAGE_PARENT = os.path.dirname(PACKAGE_ROOT)
if PACKAGE_PARENT not in sys.path:
    sys.path.insert(0, PACKAGE_PARENT)

from kongtrae.training.hedged_hierarchical_policy import (
    run_always_cash_episode,
    run_paper_threshold_policy_episode,
    run_three_head_policy_episode,
    trace_metrics,
)
from kongtrae.training.train_hedged_three_head_v2_dqn import (
    _v2_env_kwargs,
    build_policy,
    parse_action_widths,
    score_checkpoint_windows,
)
from kongtrae.training.uniswap_v3_ppo_paper import prepare_interval_data
from kongtrae.training.walk_forward_three_head_v2_dqn import generate_fold_specs


def evaluate(args) -> list[dict]:
    data = prepare_interval_data(args.data_dir, timeframe=args.timeframe)
    action_widths = parse_action_widths(args.action_widths)
    folds = generate_fold_specs(
        data.timestamps,
        train_months=args.train_months,
        eval_months=args.eval_months,
        test_months=args.test_months,
        step_months=args.step_months,
        periods_per_hour=float(getattr(data, "periods_per_hour", 1.0)),
    )
    if args.max_folds > 0:
        folds = folds[: args.max_folds]

    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    env_kwargs = _v2_env_kwargs(
        action_widths,
        recenter_cooldown_hours=args.recenter_cooldown_hours,
        recenter_emergency_oor_sigma=args.recenter_emergency_oor_sigma,
        fee_haircut=args.fee_haircut,
        active_liquidity_multiplier=args.active_liquidity_multiplier,
    )
    rows = []

    print(
        f"Evaluating existing three-head v2 model: {len(folds)} folds "
        f"on {data.timeframe} bars"
    )
    print(f"  model={args.model_path}")
    print(f"  vecnormalize={args.vec_path}")

    for fold in folds:
        print("\n" + "=" * 60)
        print(f"Fold {fold.fold_id}")
        print(f"  Train: {fold.train_range[0]} -> {fold.train_range[1]}")
        print(f"  Eval : {fold.eval_range[0]} -> {fold.eval_range[1]}")
        print(f"  Test : {fold.test_range[0]} -> {fold.test_range[1]}")

        policy = build_policy(
            model_path=args.model_path,
            vec_path=args.vec_path,
            data=data,
            hedge_accounting_mode=args.hedge_accounting_mode,
            action_widths=action_widths,
            mode="all",
            start_idx=fold.train_start,
            end_idx=fold.train_end,
            recenter_cooldown_hours=args.recenter_cooldown_hours,
            recenter_emergency_oor_sigma=args.recenter_emergency_oor_sigma,
            fee_haircut=args.fee_haircut,
            active_liquidity_multiplier=args.active_liquidity_multiplier,
        )
        score_row = score_checkpoint_windows(
            policy=policy,
            data=data,
            hedge_accounting_mode=args.hedge_accounting_mode,
            action_widths=action_widths,
            train_window=("all", fold.train_start, fold.train_end),
            eval_window=("all", fold.eval_start, fold.eval_end),
            test_window=("all", fold.test_start, fold.test_end),
            recenter_cooldown_hours=args.recenter_cooldown_hours,
            recenter_emergency_oor_sigma=args.recenter_emergency_oor_sigma,
            fee_haircut=args.fee_haircut,
            active_liquidity_multiplier=args.active_liquidity_multiplier,
        )

        test_trace = run_three_head_policy_episode(
            data=data,
            three_head_policy=policy,
            capital=args.capital,
            mode="all",
            hedge_accounting_mode=args.hedge_accounting_mode,
            start_idx=fold.test_start,
            end_idx=fold.test_end,
            action_widths=action_widths,
            env_kwargs=env_kwargs,
        )
        test_metrics = trace_metrics(test_trace)
        requested = Counter(test_trace["three_head_action_label"])
        effective = Counter(test_trace["effective_action"])

        always_cash_trace = run_always_cash_episode(
            data=data,
            capital=args.capital,
            mode="all",
            hedge_accounting_mode=args.hedge_accounting_mode,
            start_idx=fold.test_start,
            end_idx=fold.test_end,
        )
        paper_trace = run_paper_threshold_policy_episode(
            data=data,
            train_start_idx=fold.train_start,
            train_end_idx=fold.train_end,
            capital=args.capital,
            mode="all",
            hedge_accounting_mode=args.hedge_accounting_mode,
            start_idx=fold.test_start,
            end_idx=fold.test_end,
            fixed_width=args.paper_width,
            fee_haircut=args.fee_haircut,
            active_liquidity_multiplier=args.active_liquidity_multiplier,
        )
        always_cash_metrics = trace_metrics(always_cash_trace)
        paper_metrics = trace_metrics(paper_trace)

        row = {
            "fold_id": fold.fold_id,
            "train_range": fold.train_range,
            "eval_range": fold.eval_range,
            "test_range": fold.test_range,
            "model_path": args.model_path,
            "vec_path": args.vec_path,
            "steps": "existing",
            **score_row,
            "robust_score": float(
                args.selector_train_weight * score_row["train_pnl"]
                + args.selector_eval_weight * score_row["eval_pnl"]
            ),
            "always_cash_test_pnl": float(always_cash_metrics["pnl"]),
            "paper_rule_test_pnl": float(paper_metrics["pnl"]),
            "test_requested_actions": dict(sorted(requested.items())),
            "test_effective_actions": dict(sorted(effective.items())),
            "test_trace_pnl": float(test_metrics["pnl"]),
            "test_trace_trade_count": int(test_metrics["trade_count"]),
        }
        rows.append(row)
        print(
            f"  Existing model train_pnl={score_row['train_pnl']:.2f} "
            f"eval_pnl={score_row['eval_pnl']:.2f} "
            f"test_pnl={score_row['test_pnl']:.2f}"
        )
        print(
            f"  Baselines: always_cash={always_cash_metrics['pnl']:.2f}, "
            f"paper_rule={paper_metrics['pnl']:.2f}"
        )
        print(f"  Requested: {dict(sorted(requested.items()))}")
        print(f"  Effective: {dict(sorted(effective.items()))}")

    with open(args.output, "w") as f:
        json.dump(rows, f, indent=2)

    test_pnls = [row["test_pnl"] for row in rows]
    cash_pnls = [row["always_cash_test_pnl"] for row in rows]
    paper_pnls = [row["paper_rule_test_pnl"] for row in rows]
    beat_cash = sum(model > cash for model, cash in zip(test_pnls, cash_pnls))
    beat_paper = sum(model > paper for model, paper in zip(test_pnls, paper_pnls))
    print("\nExisting-model walk-forward summary")
    print(f"  output={args.output}")
    print(f"  mean_test_pnl={mean(test_pnls) if test_pnls else 0.0:.2f}")
    print(f"  median_test_pnl={median(test_pnls) if test_pnls else 0.0:.2f}")
    print(f"  folds_beating_cash={beat_cash}/{len(rows)}")
    print(f"  folds_beating_paper={beat_paper}/{len(rows)}")
    return rows


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Evaluate an existing Kongtrae three-head DQN")
    parser.add_argument("--data-dir", default="training_data")
    parser.add_argument("--timeframe", default="1h")
    parser.add_argument("--model-path", default="kongtrae/models/dqn_three_head_v3_1h.zip")
    parser.add_argument("--vec-path", default="kongtrae/models/dqn_three_head_v3_1h_vecnormalize.pkl")
    parser.add_argument("--output", default="debug_outputs/shipped_three_head_v3_1h_eval_summary.json")
    parser.add_argument("--capital", type=float, default=1000.0)
    parser.add_argument("--action-widths", default="4,6,10,20")
    parser.add_argument("--train-months", type=int, default=6)
    parser.add_argument("--eval-months", type=int, default=1)
    parser.add_argument("--test-months", type=int, default=1)
    parser.add_argument("--step-months", type=int, default=1)
    parser.add_argument("--max-folds", type=int, default=4)
    parser.add_argument("--selector-train-weight", type=float, default=0.5)
    parser.add_argument("--selector-eval-weight", type=float, default=0.5)
    parser.add_argument("--hedge-accounting-mode", default="continuous_delta_hedged")
    parser.add_argument("--paper-width", type=int, default=4)
    parser.add_argument("--recenter-cooldown-hours", type=float, default=0.0)
    parser.add_argument("--recenter-emergency-oor-sigma", type=float, default=2.5)
    parser.add_argument("--fee-haircut", type=float, default=1.0)
    parser.add_argument("--active-liquidity-multiplier", type=float, default=1.0)
    evaluate(parser.parse_args())
