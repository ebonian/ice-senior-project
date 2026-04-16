"""
Walk-forward validation for the realistic three-head Double+Dueling DQN v2.

Each fold:
  6 months train
  1 month eval
  1 month test
  1 month step
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from argparse import Namespace
from dataclasses import dataclass
from statistics import mean, median
from typing import List

PACKAGE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKAGE_PARENT = os.path.dirname(PACKAGE_ROOT)
if PACKAGE_PARENT not in sys.path:
    sys.path.insert(0, PACKAGE_PARENT)

from kongtrae.training.hedged_hierarchical_policy import (
    run_always_cash_episode,
    run_paper_threshold_policy_episode,
    trace_metrics,
)
from kongtrae.training.train_hedged_three_head_v2_dqn import (
    parse_action_widths,
    score_saved_checkpoints,
    train as train_three_head_v2,
)
from kongtrae.training.uniswap_v3_ppo_paper import prepare_hourly_data


WARMUP_HOURS = 200
HOURS_PER_MONTH = 730


@dataclass
class FoldSpec:
    fold_id: int
    train_start: int
    train_end: int
    eval_start: int
    eval_end: int
    test_start: int
    test_end: int
    train_range: tuple[str, str]
    eval_range: tuple[str, str]
    test_range: tuple[str, str]


def generate_fold_specs(
    timestamps,
    train_months: int,
    eval_months: int,
    test_months: int,
    step_months: int,
) -> List[FoldSpec]:
    train_hours = int(train_months * HOURS_PER_MONTH)
    eval_hours = int(eval_months * HOURS_PER_MONTH)
    test_hours = int(test_months * HOURS_PER_MONTH)
    step_hours = int(step_months * HOURS_PER_MONTH)
    n_total = len(timestamps)
    folds = []
    fold_start = WARMUP_HOURS
    fold_id = 0
    while True:
        train_start = fold_start
        train_end = train_start + train_hours
        eval_start = train_end
        eval_end = eval_start + eval_hours
        test_start = eval_end
        test_end = min(test_start + test_hours, n_total)
        if test_start >= n_total:
            break
        if test_end - test_start < max(test_hours // 2, 1):
            break
        folds.append(
            FoldSpec(
                fold_id=fold_id,
                train_start=train_start,
                train_end=train_end,
                eval_start=eval_start,
                eval_end=eval_end,
                test_start=test_start,
                test_end=test_end,
                train_range=(
                    str(timestamps[train_start])[:16],
                    str(timestamps[min(train_end - 1, n_total - 1)])[:16],
                ),
                eval_range=(
                    str(timestamps[eval_start])[:16],
                    str(timestamps[min(eval_end - 1, n_total - 1)])[:16],
                ),
                test_range=(
                    str(timestamps[test_start])[:16],
                    str(timestamps[min(test_end - 1, n_total - 1)])[:16],
                ),
            )
        )
        fold_id += 1
        fold_start += step_hours
    return folds


def cleanup_prior_artifacts(save_name: str) -> None:
    for path in (
        save_name + ".zip",
        save_name + "_vec_normalize.pkl",
        f"checkpoints_{save_name}",
        f"{save_name}_best",
        f"eval_logs_{save_name}",
    ):
        if os.path.isdir(path):
            shutil.rmtree(path)
        elif os.path.exists(path):
            os.remove(path)


def build_train_args(args, fold: FoldSpec, save_name: str) -> Namespace:
    return Namespace(
        data_dir=args.data_dir,
        save_name=save_name,
        tb_log=os.path.join(args.tb_log_dir, save_name),
        start_idx=fold.train_start,
        end_idx=fold.train_end,
        eval_start_idx=fold.eval_start,
        eval_end_idx=fold.eval_end,
        final_eval_start_idx=fold.test_start,
        final_eval_end_idx=fold.test_end,
        capital=args.capital,
        seed=args.seed + fold.fold_id,
        total_timesteps=args.total_timesteps,
        lr=args.lr,
        gamma=args.gamma,
        buffer_size=args.buffer_size,
        learning_starts=args.learning_starts,
        batch_size=args.batch_size,
        tau=args.tau,
        train_freq=args.train_freq,
        target_update_interval=args.target_update_interval,
        exploration_fraction=args.exploration_fraction,
        exploration_initial_eps=args.exploration_initial_eps,
        exploration_final_eps=args.exploration_final_eps,
        net_arch=args.net_arch,
        eval_freq=args.eval_freq,
        checkpoint_freq=args.checkpoint_freq,
        action_widths=args.action_widths,
        min_episode_hours=args.min_episode_hours,
        max_episode_hours=args.max_episode_hours,
        cash_start_prob=args.cash_start_prob,
        in_range_start_prob=args.in_range_start_prob,
        oor_start_prob=args.oor_start_prob,
        profit_scan_horizon_hours=args.profit_scan_horizon_hours,
        profit_scan_stride=args.profit_scan_stride,
        profit_scan_margin_usd=args.profit_scan_margin_usd,
        hard_negative_margin_usd=args.hard_negative_margin_usd,
        prefill_transitions=args.prefill_transitions,
        prefill_policies=args.prefill_policies,
        hedge_accounting_mode=args.hedge_accounting_mode,
        training_reward_mode=args.training_reward_mode,
        reward_scale=args.reward_scale,
    )


def run_walk_forward(args):
    data = prepare_hourly_data(args.data_dir)
    action_widths = parse_action_widths(args.action_widths)
    folds = generate_fold_specs(
        data.timestamps,
        train_months=args.train_months,
        eval_months=args.eval_months,
        test_months=args.test_months,
        step_months=args.step_months,
    )
    if args.max_folds > 0:
        folds = folds[: args.max_folds]
    os.makedirs(args.save_dir, exist_ok=True)
    os.makedirs(args.tb_log_dir, exist_ok=True)
    summary_rows = []

    print(f"Walk-forward three-head Double+Dueling DQN v2: {len(folds)} folds")
    for fold in folds:
        save_name = f"{args.run_prefix}_fold{fold.fold_id}"
        cleanup_prior_artifacts(save_name)

        print("\n" + "=" * 60)
        print(f"Fold {fold.fold_id}")
        print(f"  Train: {fold.train_range[0]} -> {fold.train_range[1]}")
        print(f"  Eval : {fold.eval_range[0]} -> {fold.eval_range[1]}")
        print(f"  Test : {fold.test_range[0]} -> {fold.test_range[1]}")

        train_args = build_train_args(args, fold, save_name)
        train_three_head_v2(train_args)

        checkpoint_rows = score_saved_checkpoints(
            data=data,
            save_name=save_name,
            hedge_accounting_mode=args.hedge_accounting_mode,
            action_widths=action_widths,
            train_window=("all", fold.train_start, fold.train_end),
            eval_window=("all", fold.eval_start, fold.eval_end),
            test_window=("all", fold.test_start, fold.test_end),
        )
        for row in checkpoint_rows:
            row["robust_score"] = float(
                args.selector_train_weight * row["train_pnl"]
                + args.selector_eval_weight * row["eval_pnl"]
            )
        checkpoint_rows.sort(key=lambda row: row["robust_score"], reverse=True)
        checkpoint_scores_path = os.path.join(
            args.save_dir, f"{save_name}_checkpoint_scores.json"
        )
        with open(checkpoint_scores_path, "w") as f:
            json.dump(checkpoint_rows, f, indent=2)
        best_row = checkpoint_rows[0]

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
            fixed_width=4,
        )
        always_cash_metrics = trace_metrics(always_cash_trace)
        paper_metrics = trace_metrics(paper_trace)

        print(
            f"  Selected checkpoint steps={best_row['steps']} "
            f"train_pnl={best_row['train_pnl']:.2f} "
            f"eval_pnl={best_row['eval_pnl']:.2f} "
            f"test_pnl={best_row['test_pnl']:.2f}"
        )
        print(
            f"  Baselines: always_cash={always_cash_metrics['pnl']:.2f}, "
            f"paper_rule={paper_metrics['pnl']:.2f}"
        )

        summary_rows.append(
            {
                "fold_id": fold.fold_id,
                "train_range": fold.train_range,
                "eval_range": fold.eval_range,
                "test_range": fold.test_range,
                **best_row,
                "always_cash_test_pnl": float(always_cash_metrics["pnl"]),
                "paper_rule_test_pnl": float(paper_metrics["pnl"]),
            }
        )

        if args.cleanup_checkpoints:
            checkpoint_dir = f"checkpoints_{save_name}"
            if os.path.isdir(checkpoint_dir):
                shutil.rmtree(checkpoint_dir)

    summary_path = os.path.join(args.save_dir, f"{args.run_prefix}_walk_forward_summary.json")
    with open(summary_path, "w") as f:
        json.dump(summary_rows, f, indent=2)

    model_test_pnls = [row["test_pnl"] for row in summary_rows]
    always_cash_test_pnls = [row["always_cash_test_pnl"] for row in summary_rows]
    paper_test_pnls = [row["paper_rule_test_pnl"] for row in summary_rows]
    beat_cash = sum(model > cash for model, cash in zip(model_test_pnls, always_cash_test_pnls))
    beat_paper = sum(model > paper for model, paper in zip(model_test_pnls, paper_test_pnls))
    print("\nWalk-forward summary")
    print(f"  summary_path={summary_path}")
    print(f"  mean_test_pnl={mean(model_test_pnls) if model_test_pnls else 0.0:.2f}")
    print(f"  median_test_pnl={median(model_test_pnls) if model_test_pnls else 0.0:.2f}")
    print(f"  folds_beating_cash={beat_cash}/{len(summary_rows)}")
    print(f"  folds_beating_paper={beat_paper}/{len(summary_rows)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Walk-forward validate realistic three-head Double+Dueling DQN v2"
    )
    parser.add_argument("--data-dir", default="training_data")
    parser.add_argument("--save-dir", default="walk_forward_three_head_v2")
    parser.add_argument("--tb-log-dir", default="tb_walk_forward_three_head_v2")
    parser.add_argument("--run-prefix", default="wf_three_head_v2")
    parser.add_argument("--capital", type=float, default=1000.0)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--total-timesteps", type=int, default=500000)
    parser.add_argument("--lr", type=float, default=1e-4)
    parser.add_argument("--gamma", type=float, default=0.0)
    parser.add_argument("--buffer-size", type=int, default=200000)
    parser.add_argument("--learning-starts", type=int, default=5000)
    parser.add_argument("--batch-size", type=int, default=128)
    parser.add_argument("--tau", type=float, default=0.005)
    parser.add_argument("--train-freq", type=int, default=4)
    parser.add_argument("--target-update-interval", type=int, default=1000)
    parser.add_argument("--exploration-fraction", type=float, default=0.30)
    parser.add_argument("--exploration-initial-eps", type=float, default=1.0)
    parser.add_argument("--exploration-final-eps", type=float, default=0.05)
    parser.add_argument("--net-arch", type=int, nargs="+", default=[32, 32])
    parser.add_argument("--eval-freq", type=int, default=50000)
    parser.add_argument("--checkpoint-freq", type=int, default=50000)
    parser.add_argument("--action-widths", default="4,6,10,20")
    parser.add_argument("--min-episode-hours", type=int, default=500)
    parser.add_argument("--max-episode-hours", type=int, default=2000)
    parser.add_argument("--cash-start-prob", type=float, default=0.60)
    parser.add_argument("--in-range-start-prob", type=float, default=0.20)
    parser.add_argument("--oor-start-prob", type=float, default=0.20)
    parser.add_argument("--profit-scan-horizon-hours", type=int, default=72)
    parser.add_argument("--profit-scan-stride", type=int, default=6)
    parser.add_argument("--profit-scan-margin-usd", type=float, default=0.0)
    parser.add_argument("--hard-negative-margin-usd", type=float, default=0.0)
    parser.add_argument("--prefill-transitions", type=int, default=20000)
    parser.add_argument("--prefill-policies", default="paper_prior,always_cash")
    parser.add_argument("--train-months", type=int, default=6)
    parser.add_argument("--eval-months", type=int, default=1)
    parser.add_argument("--test-months", type=int, default=1)
    parser.add_argument("--step-months", type=int, default=1)
    parser.add_argument("--max-folds", type=int, default=4)
    parser.add_argument("--selector-train-weight", type=float, default=0.5)
    parser.add_argument("--selector-eval-weight", type=float, default=0.5)
    parser.add_argument("--cleanup-checkpoints", action="store_true")
    parser.add_argument("--hedge-accounting-mode", default="continuous_delta_hedged")
    parser.add_argument(
        "--training-reward-mode",
        default="realistic",
    )
    parser.add_argument("--reward-scale", type=float, default=1.0)
    run_walk_forward(parser.parse_args())
