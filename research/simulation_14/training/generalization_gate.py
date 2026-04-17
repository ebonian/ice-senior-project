"""
Generalization gate for Kongtrae 3-head DQN models.

This script is intentionally stricter than a single walk-forward run. It can:
  1. Generate or execute shifted walk-forward commands for 1h and 15min models.
  2. Re-evaluate existing summary JSONs with the evaluator-identical policy loader.
  3. Add regime labels, width mix, action diagnostics, and pass/fail gates.

The gate does not change the reward, accounting, action space, or model design.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from statistics import mean, median
from typing import Iterable

import numpy as np
import pandas as pd

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
    score_saved_checkpoints,
)
from kongtrae.training.uniswap_v3_ppo_paper import FEATURE_COLS, prepare_interval_data
from kongtrae.training.walk_forward_three_head_v2_dqn import (
    HOURS_PER_MONTH,
    generate_fold_specs,
    run_walk_forward,
)


DEFAULT_RUN_MAP = {
    ("1h", 0, 42): (
        "walk_forward_three_head_v2_1h_maskfix_100k",
        "wf_three_head_v2_1h_maskfix_100k",
    ),
    ("15min", 0, 42): (
        "walk_forward_three_head_v2_15min_maskfix_150k",
        "wf_three_head_v2_15min_maskfix_150k",
    ),
}


@dataclass(frozen=True)
class GateCombo:
    timeframe: str
    seed: int
    offset_days: int


class StaticThreeHeadPolicy:
    """Simple fixed-width baseline under the v2 three-head action contract."""

    def __init__(self, width: int, action_widths: Iterable[int], recenter_oor: bool):
        self.width = int(width)
        self.action_widths = tuple(int(w) for w in action_widths)
        self.recenter_oor = bool(recenter_oor)
        if self.width not in self.action_widths:
            raise ValueError(f"Width {self.width} not in action widths {self.action_widths}")

    def predict(self, obs, return_q: bool = False):
        obs_arr = np.asarray(obs, dtype=np.float32)
        state_idx = int(np.argmax(obs_arr[:3]))
        if state_idx == 0:  # cash
            value = 1 + self.action_widths.index(self.width)
        elif state_idx == 1:  # in range
            value = 0
        else:  # OOR
            value = 2 if self.recenter_oor else 0
        return type("Pred", (), {"value": int(value), "q_gap": 0.0})()


def parse_csv_list(raw: str, cast=str) -> list:
    return [cast(x.strip()) for x in str(raw).split(",") if x.strip()]


def offset_label(offset_days: int | float) -> str:
    return f"o{int(offset_days)}d"


def build_run_names(timeframe: str, seed: int, offset_days: int, label: str) -> tuple[str, str]:
    safe_tf = str(timeframe).replace("/", "_")
    prefix = f"wf_three_head_v2_{safe_tf}_{label}_{offset_label(offset_days)}_s{int(seed)}"
    save_dir = f"walk_forward_three_head_v2_{safe_tf}_{label}_{offset_label(offset_days)}_s{int(seed)}"
    return save_dir, prefix


def summary_path_for(save_dir: str, run_prefix: str) -> Path:
    return Path(save_dir) / f"{run_prefix}_walk_forward_summary.json"


def existing_or_planned_names(combo: GateCombo, label: str) -> tuple[str, str]:
    return DEFAULT_RUN_MAP.get(
        (combo.timeframe, combo.offset_days, combo.seed),
        build_run_names(combo.timeframe, combo.seed, combo.offset_days, label),
    )


def timeframe_timesteps(args, timeframe: str) -> int:
    if timeframe == "1h":
        return int(args.timesteps_1h)
    if timeframe == "15min":
        return int(args.timesteps_15min)
    return int(args.timesteps_other)


def timeframe_profit_scan_stride(args, timeframe: str) -> int:
    if timeframe == "1h":
        return int(args.profit_scan_stride_1h)
    if timeframe == "15min":
        return int(args.profit_scan_stride_15min)
    return int(args.profit_scan_stride_other)


def build_walk_forward_args(args, combo: GateCombo, save_dir: str, run_prefix: str) -> argparse.Namespace:
    timesteps = timeframe_timesteps(args, combo.timeframe)
    eval_freq = min(int(args.eval_freq), timesteps)
    checkpoint_freq = min(int(args.checkpoint_freq), timesteps)
    return argparse.Namespace(
        data_dir=args.data_dir,
        timeframe=combo.timeframe,
        save_dir=save_dir,
        tb_log_dir=f"tb_{save_dir}",
        run_prefix=run_prefix,
        capital=args.capital,
        seed=combo.seed,
        total_timesteps=timesteps,
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
        eval_freq=eval_freq,
        checkpoint_freq=checkpoint_freq,
        action_widths=args.action_widths,
        min_episode_hours=args.min_episode_hours,
        max_episode_hours=args.max_episode_hours,
        cash_start_prob=args.cash_start_prob,
        in_range_start_prob=args.in_range_start_prob,
        oor_start_prob=args.oor_start_prob,
        profit_scan_horizon_hours=args.profit_scan_horizon_hours,
        profit_scan_stride=timeframe_profit_scan_stride(args, combo.timeframe),
        profit_scan_margin_usd=args.profit_scan_margin_usd,
        hard_negative_margin_usd=args.hard_negative_margin_usd,
        prefill_transitions=args.prefill_transitions,
        prefill_policies=args.prefill_policies,
        recenter_cooldown_hours=args.recenter_cooldown_hours,
        recenter_emergency_oor_sigma=args.recenter_emergency_oor_sigma,
        fee_haircut=args.fee_haircut,
        active_liquidity_multiplier=args.active_liquidity_multiplier,
        train_months=args.train_months,
        eval_months=args.eval_months,
        test_months=args.test_months,
        step_months=args.step_months,
        start_offset_days=float(combo.offset_days),
        max_folds=args.max_folds,
        selector_train_weight=args.selector_train_weight,
        selector_eval_weight=args.selector_eval_weight,
        cleanup_checkpoints=args.cleanup_checkpoints,
        hedge_accounting_mode=args.hedge_accounting_mode,
        training_reward_mode=args.training_reward_mode,
        reward_scale=args.reward_scale,
    )


def build_cli_command(args, combo: GateCombo, save_dir: str, run_prefix: str) -> list[str]:
    wf_args = build_walk_forward_args(args, combo, save_dir, run_prefix)
    cmd = [
        sys.executable,
        "-u",
        "kongtrae/training/walk_forward_three_head_v2_dqn.py",
        "--timeframe",
        wf_args.timeframe,
        "--save-dir",
        wf_args.save_dir,
        "--tb-log-dir",
        wf_args.tb_log_dir,
        "--run-prefix",
        wf_args.run_prefix,
        "--seed",
        str(wf_args.seed),
        "--total-timesteps",
        str(wf_args.total_timesteps),
        "--max-folds",
        str(wf_args.max_folds),
        "--checkpoint-freq",
        str(wf_args.checkpoint_freq),
        "--eval-freq",
        str(wf_args.eval_freq),
        "--learning-starts",
        str(wf_args.learning_starts),
        "--prefill-transitions",
        str(wf_args.prefill_transitions),
        "--net-arch",
        *(str(x) for x in wf_args.net_arch),
        "--gamma",
        str(wf_args.gamma),
        "--action-widths",
        wf_args.action_widths,
        "--profit-scan-stride",
        str(wf_args.profit_scan_stride),
        "--start-offset-days",
        str(wf_args.start_offset_days),
    ]
    return cmd


def regime_summary(data, fold) -> dict:
    timestamps = data.timestamps[fold.test_start : fold.test_end]
    if len(timestamps) == 0:
        return {}
    features = np.asarray([data.features[t] for t in timestamps], dtype=np.float32)
    prices = np.asarray([float(data.prices[t]) for t in timestamps], dtype=np.float64)
    volumes = np.asarray([float(data.volumes.get(t, 0.0)) for t in timestamps], dtype=np.float64)
    all_volumes = np.asarray(list(data.volumes.values()), dtype=np.float64)
    volume_pctl = float((all_volumes <= volumes.mean()).mean()) if len(all_volumes) else 0.0

    market = features[:, FEATURE_COLS.index("market_regime")]
    fast = features[:, FEATURE_COLS.index("regime_fast")]
    vol_regime = features[:, FEATURE_COLS.index("vol_regime")]
    natr = features[:, FEATURE_COLS.index("natr_14")]
    bb_width = features[:, FEATURE_COLS.index("bb_width")]
    volume_sma_ratio = features[:, FEATURE_COLS.index("volume_sma_ratio")]

    def dominant_regime(values) -> str:
        bull = float((values > 0.5).mean())
        bear = float((values < -0.5).mean())
        side = 1.0 - bull - bear
        if bull >= bear and bull >= side:
            return "bull"
        if bear >= bull and bear >= side:
            return "bear"
        return "sideways"

    price_return_pct = float((prices[-1] / max(prices[0], 1e-12) - 1.0) * 100.0)
    if price_return_pct > 8:
        price_path = "bull"
    elif price_return_pct < -8:
        price_path = "bear"
    else:
        price_path = "sideways"
    vol_level = "high_vol" if float(vol_regime.mean()) >= 0.5 else "low_vol"
    fee_level = "high_fee" if volume_pctl >= 0.66 else ("low_fee" if volume_pctl <= 0.33 else "mid_fee")
    return {
        "regime_market": dominant_regime(market),
        "regime_fast": dominant_regime(fast),
        "price_path": price_path,
        "price_return_pct": price_return_pct,
        "vol_level": vol_level,
        "vol_regime_mean": float(vol_regime.mean()),
        "natr_mean": float(natr.mean()),
        "bb_width_mean": float(bb_width.mean()),
        "volume_sma_ratio_mean": float(volume_sma_ratio.mean()),
        "fee_level": fee_level,
        "mean_volume_usd": float(volumes.mean()),
        "volume_percentile": volume_pctl,
    }


def width_mix_from_trace(trace_df: pd.DataFrame) -> dict:
    labels = []
    current = "Cash"
    for _, row in trace_df.iterrows():
        action = str(row["effective_action"])
        state_after = str(row["next_position_state"])
        selected_width = int(row.get("selected_width", 0) or 0)
        if (
            action.startswith("enter_w")
            or action.startswith("recenter_w")
            or action == "recenter_same_width"
        ) and selected_width > 0:
            current = f"W{selected_width}"
        elif action == "exit_to_cash" or state_after == "cash":
            current = "Cash"
        labels.append(current)
    counts = pd.Series(labels).value_counts(normalize=True).mul(100.0).to_dict()
    return {f"width_pct_{k.lower()}": float(v) for k, v in sorted(counts.items())}


def replay_model_row(args, data, fold, row: dict, action_widths: tuple[int, ...]) -> dict:
    model_path, vec_path = resolve_model_vec_paths(row)
    policy = build_policy(
        model_path=model_path,
        vec_path=vec_path,
        data=data,
        hedge_accounting_mode=args.hedge_accounting_mode,
        mode="all",
        action_widths=action_widths,
        start_idx=fold.test_start,
        end_idx=fold.test_end,
        recenter_cooldown_hours=args.recenter_cooldown_hours,
        recenter_emergency_oor_sigma=args.recenter_emergency_oor_sigma,
        fee_haircut=args.fee_haircut,
        active_liquidity_multiplier=args.active_liquidity_multiplier,
    )
    trace = run_three_head_policy_episode(
        data=data,
        three_head_policy=policy,
        capital=args.capital,
        mode="all",
        hedge_accounting_mode=args.hedge_accounting_mode,
        action_widths=action_widths,
        start_idx=fold.test_start,
        end_idx=fold.test_end,
        env_kwargs=_v2_env_kwargs(
            action_widths,
            recenter_cooldown_hours=args.recenter_cooldown_hours,
            recenter_emergency_oor_sigma=args.recenter_emergency_oor_sigma,
            fee_haircut=args.fee_haircut,
            active_liquidity_multiplier=args.active_liquidity_multiplier,
        ),
    )
    metrics = trace_metrics(trace)
    days = max((fold.test_end - fold.test_start) / max(float(getattr(data, "periods_per_hour", 1.0)), 1.0) / 24.0, 1e-9)
    return {
        "replay_pnl": float(metrics["pnl"]),
        "replay_final_pv": float(metrics["final_pv"]),
        "replay_trade_count": int(metrics["trade_count"]),
        "trades_per_day": float(metrics["trade_count"] / days),
        "replay_cash_pct": float(metrics["cash_pct"]),
        "replay_oor_pct": float(metrics["oor_pct"]),
        "replay_gross_fee_carry_usd": float(metrics["gross_fee_carry_usd"]),
        "replay_raw_swing_pnl_usd": float(metrics["raw_swing_pnl_usd"]),
        "masked_invalid_actions": int(trace.get("masked_invalid_action", pd.Series(dtype=int)).sum()),
        **width_mix_from_trace(trace),
    }


def run_static_baselines(args, data, fold, action_widths: tuple[int, ...]) -> dict:
    if not args.include_fixed_baselines:
        return {}
    results = {}
    for width in action_widths:
        for mode_name, recenter_oor in (
            ("deploy_hold", False),
            ("fixed_recenter", True),
        ):
            policy = StaticThreeHeadPolicy(width=width, action_widths=action_widths, recenter_oor=recenter_oor)
            trace = run_three_head_policy_episode(
                data=data,
                three_head_policy=policy,
                capital=args.capital,
                mode="all",
                hedge_accounting_mode=args.hedge_accounting_mode,
                action_widths=action_widths,
                start_idx=fold.test_start,
                end_idx=fold.test_end,
                env_kwargs=_v2_env_kwargs(
                    action_widths,
                    recenter_cooldown_hours=args.recenter_cooldown_hours,
                    recenter_emergency_oor_sigma=args.recenter_emergency_oor_sigma,
                    fee_haircut=args.fee_haircut,
                    active_liquidity_multiplier=args.active_liquidity_multiplier,
                ),
            )
            metrics = trace_metrics(trace)
            results[f"{mode_name}_w{width}_pnl"] = float(metrics["pnl"])
            results[f"{mode_name}_w{width}_trades"] = int(metrics["trade_count"])
    return results


def resolve_model_vec_paths(row: dict) -> tuple[str, str]:
    """Resolve summary model paths, including older runs whose checkpoints were cleaned."""
    model_path = Path(str(row["model_path"]))
    vec_path = Path(str(row["vec_path"]))
    if model_path.exists() and vec_path.exists():
        return str(model_path), str(vec_path)

    save_name = ""
    if model_path.parts and model_path.parts[0].startswith("checkpoints_"):
        save_name = model_path.parts[0].replace("checkpoints_", "", 1)
    if not save_name:
        save_name = model_path.stem.replace("_steps", "")

    candidates = [
        (Path(f"{save_name}.zip"), Path(f"{save_name}_vec_normalize.pkl")),
        (Path(f"{save_name}_best") / "best_model.zip", Path(f"{save_name}_best") / "best_vecnormalize.pkl"),
    ]
    for candidate_model, candidate_vec in candidates:
        if candidate_model.exists() and candidate_vec.exists():
            return str(candidate_model), str(candidate_vec)

    raise FileNotFoundError(
        "Could not resolve model/VecNormalize paths for summary row: "
        f"model_path={row.get('model_path')} vec_path={row.get('vec_path')}"
    )


def summarize_gate(rows: list[dict], args) -> dict:
    if not rows:
        return {"status": "missing", "reason": "no rows"}
    pnls = [float(r["test_pnl"]) for r in rows]
    cash = [float(r.get("always_cash_test_pnl", 0.0)) for r in rows]
    paper = [float(r.get("paper_rule_test_pnl", 0.0)) for r in rows]
    invalid = [int(r.get("masked_invalid_actions", 0)) for r in rows]
    worst = min(pnls)
    beat_cash = sum(p > c for p, c in zip(pnls, cash))
    beat_paper = sum(p > b for p, b in zip(pnls, paper))
    pass_cash = (
        median(pnls) > args.min_median_pnl
        and beat_cash / len(rows) >= args.min_beat_cash_frac
        and worst >= args.catastrophic_pnl
        and sum(invalid) == 0
    )
    pass_paper = mean(pnls) > mean(paper) if paper else False
    return {
        "folds": len(rows),
        "mean_test_pnl": float(mean(pnls)),
        "median_test_pnl": float(median(pnls)),
        "worst_test_pnl": float(worst),
        "mean_paper_pnl": float(mean(paper)) if paper else 0.0,
        "beat_cash": int(beat_cash),
        "beat_paper": int(beat_paper),
        "invalid_actions": int(sum(invalid)),
        "pass_cash_gate": bool(pass_cash),
        "pass_paper_gate": bool(pass_paper),
        "status": "pass" if pass_cash and pass_paper else ("candidate" if pass_cash else "fail"),
    }


def load_summary_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path) as f:
        return json.load(f)


def recompute_test_baselines(args, data, fold) -> dict:
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
        fee_haircut=args.fee_haircut,
        active_liquidity_multiplier=args.active_liquidity_multiplier,
    )
    always_cash_metrics = trace_metrics(always_cash_trace)
    paper_metrics = trace_metrics(paper_trace)
    return {
        "always_cash_test_pnl": float(always_cash_metrics["pnl"]),
        "paper_rule_test_pnl": float(paper_metrics["pnl"]),
    }


def rescore_fold_checkpoint_row(args, data, fold, run_prefix: str, action_widths: tuple[int, ...]) -> dict | None:
    save_name = f"{run_prefix}_fold{fold.fold_id}"
    checkpoint_rows = score_saved_checkpoints(
        data=data,
        save_name=save_name,
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
    if not checkpoint_rows:
        return None
    for checkpoint_row in checkpoint_rows:
        checkpoint_row["robust_score"] = float(
            args.selector_train_weight * checkpoint_row["train_pnl"]
            + args.selector_eval_weight * checkpoint_row["eval_pnl"]
        )
    checkpoint_rows.sort(key=lambda checkpoint_row: checkpoint_row["robust_score"], reverse=True)
    best_row = dict(checkpoint_rows[0])
    best_row["rescored_checkpoints"] = True
    return best_row


def report_combo(args, combo: GateCombo, save_dir: str, run_prefix: str) -> tuple[list[dict], dict]:
    summary_path = summary_path_for(save_dir, run_prefix)
    rows = load_summary_rows(summary_path)
    if not rows:
        return [], {
            "timeframe": combo.timeframe,
            "seed": combo.seed,
            "start_offset_days": combo.offset_days,
            "summary_path": str(summary_path),
            "status": "missing",
        }

    data = prepare_interval_data(args.data_dir, timeframe=combo.timeframe)
    folds = generate_fold_specs(
        data.timestamps,
        train_months=args.train_months,
        eval_months=args.eval_months,
        test_months=args.test_months,
        step_months=args.step_months,
        periods_per_hour=float(getattr(data, "periods_per_hour", 1.0)),
        start_offset_days=combo.offset_days,
    )
    if args.max_folds > 0:
        folds = folds[: args.max_folds]
    action_widths = parse_action_widths(args.action_widths)
    detailed_rows = []
    for row in rows:
        fold_id = int(row["fold_id"])
        if fold_id >= len(folds):
            continue
        fold = folds[fold_id]
        if args.rescore_checkpoints:
            rescored = rescore_fold_checkpoint_row(args, data, fold, run_prefix, action_widths)
            if rescored is not None:
                row = {
                    **row,
                    **rescored,
                    **recompute_test_baselines(args, data, fold),
                }
        detailed = {
            "timeframe": combo.timeframe,
            "seed": combo.seed,
            "start_offset_days": combo.offset_days,
            "summary_path": str(summary_path),
            **row,
            **regime_summary(data, fold),
        }
        if args.replay_traces:
            detailed.update(replay_model_row(args, data, fold, row, action_widths))
        if args.include_fixed_baselines:
            detailed.update(run_static_baselines(args, data, fold, action_widths))
        detailed_rows.append(detailed)

    combo_summary = {
        "timeframe": combo.timeframe,
        "seed": combo.seed,
        "start_offset_days": combo.offset_days,
        "summary_path": str(summary_path),
        **summarize_gate(detailed_rows, args),
    }
    return detailed_rows, combo_summary


def run_gate(args) -> None:
    combos = [
        GateCombo(timeframe=tf, seed=seed, offset_days=offset)
        for tf in parse_csv_list(args.timeframes, str)
        for seed in parse_csv_list(args.seeds, int)
        for offset in parse_csv_list(args.offset_days, int)
    ]
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    all_rows = []
    combo_summaries = []
    planned_commands = []

    for combo in combos:
        save_dir, run_prefix = existing_or_planned_names(combo, args.label)
        summary_path = summary_path_for(save_dir, run_prefix)
        cmd = build_cli_command(args, combo, save_dir, run_prefix)
        planned_commands.append(" ".join(cmd))
        if args.execute and not summary_path.exists():
            print(f"\nRunning {combo.timeframe} seed={combo.seed} offset={combo.offset_days}d")
            subprocess.run(cmd, check=True)
        rows, summary = report_combo(args, combo, save_dir, run_prefix)
        all_rows.extend(rows)
        combo_summaries.append(summary)

    detail_path = output_dir / f"{args.label}_fold_details.csv"
    summary_path = output_dir / f"{args.label}_combo_summary.json"
    commands_path = output_dir / f"{args.label}_planned_commands.txt"
    if all_rows:
        pd.DataFrame(all_rows).to_csv(detail_path, index=False)
    with open(summary_path, "w") as f:
        json.dump(combo_summaries, f, indent=2)
    with open(commands_path, "w") as f:
        f.write("\n".join(planned_commands) + "\n")

    print("\nGeneralization gate")
    print(f"  detail_csv={detail_path}")
    print(f"  combo_summary={summary_path}")
    print(f"  planned_commands={commands_path}")
    for summary in combo_summaries:
        print(
            "  "
            f"{summary['timeframe']} seed={summary['seed']} "
            f"offset={summary['start_offset_days']}d "
            f"status={summary.get('status')} "
            f"mean={summary.get('mean_test_pnl', 0.0):+.2f} "
            f"median={summary.get('median_test_pnl', 0.0):+.2f} "
            f"beat_cash={summary.get('beat_cash', 0)}/{summary.get('folds', 0)} "
            f"beat_paper={summary.get('beat_paper', 0)}/{summary.get('folds', 0)} "
            f"invalid={summary.get('invalid_actions', 0)}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run/report generalization gates for 1h and 15min DQN models")
    parser.add_argument("--data-dir", default="training_data")
    parser.add_argument("--timeframes", default="1h,15min")
    parser.add_argument("--seeds", default="42")
    parser.add_argument("--offset-days", default="0")
    parser.add_argument("--label", default="generalization_gate")
    parser.add_argument("--output-dir", default="debug_outputs/generalization_gate")
    parser.add_argument("--execute", action="store_true", help="Train missing combinations before reporting")
    parser.add_argument("--replay-traces", action="store_true", help="Replay selected checkpoints for width/invalid diagnostics")
    parser.add_argument(
        "--rescore-checkpoints",
        action="store_true",
        help="Re-score saved checkpoints with current accounting and select by train+eval before reporting",
    )
    parser.add_argument("--include-fixed-baselines", action="store_true")

    parser.add_argument("--capital", type=float, default=1000.0)
    parser.add_argument("--timesteps-1h", type=int, default=100000)
    parser.add_argument("--timesteps-15min", type=int, default=150000)
    parser.add_argument("--timesteps-other", type=int, default=100000)
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
    parser.add_argument("--profit-scan-stride-1h", type=int, default=6)
    parser.add_argument("--profit-scan-stride-15min", type=int, default=6)
    parser.add_argument("--profit-scan-stride-other", type=int, default=6)
    parser.add_argument("--profit-scan-margin-usd", type=float, default=0.0)
    parser.add_argument("--hard-negative-margin-usd", type=float, default=0.0)
    parser.add_argument("--prefill-transitions", type=int, default=20000)
    parser.add_argument("--prefill-policies", default="paper_prior,always_cash")
    parser.add_argument("--recenter-cooldown-hours", type=float, default=0.0)
    parser.add_argument("--recenter-emergency-oor-sigma", type=float, default=2.5)
    parser.add_argument("--fee-haircut", type=float, default=1.0)
    parser.add_argument("--active-liquidity-multiplier", type=float, default=1.0)
    parser.add_argument("--train-months", type=int, default=6)
    parser.add_argument("--eval-months", type=int, default=1)
    parser.add_argument("--test-months", type=int, default=1)
    parser.add_argument("--step-months", type=int, default=1)
    parser.add_argument("--max-folds", type=int, default=4)
    parser.add_argument("--selector-train-weight", type=float, default=0.5)
    parser.add_argument("--selector-eval-weight", type=float, default=0.5)
    parser.add_argument("--cleanup-checkpoints", action="store_true")
    parser.add_argument("--hedge-accounting-mode", default="continuous_delta_hedged")
    parser.add_argument("--training-reward-mode", default="realistic")
    parser.add_argument("--reward-scale", type=float, default=1.0)

    parser.add_argument("--min-median-pnl", type=float, default=0.0)
    parser.add_argument("--min-beat-cash-frac", type=float, default=0.75)
    parser.add_argument("--catastrophic-pnl", type=float, default=-250.0)
    args = parser.parse_args()
    run_gate(args)


if __name__ == "__main__":
    main()
