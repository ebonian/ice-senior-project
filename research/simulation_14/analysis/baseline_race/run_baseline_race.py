#!/usr/bin/env python3
"""
Race the shipped simulation_14 1h DQN against always-in fixed-width rules, inside
the DQN's own environment.

Nothing is retrained and no env dynamics or reward are touched. Every policy runs
through `run_three_head_policy_episode` in `UniswapV3HedgedThreeHeadEnv`, with the
env kwargs the shipped model was trained and gated under (`_v2_env_kwargs`), over
identical windows. The only thing that differs between arms is the action chosen
at each bar.

Two pools, because the checkpoint's training pool and its serving pool are not the
same one (see REPORT.md):

    --data-dir _data        ETH/USDC 0.05%, Arbitrum  -- what the model is SERVED on
    --data-dir _data_usdt   ETH/USDT 0.3%,  mainnet   -- what it was TRAINED on

Windows are stated outright rather than recovered from `generate_fold_specs`. The
published walk-forward folds cannot be replayed: the concatenated CSV they used is
gone, and it was a different pool, so the fold index arithmetic does not transfer.
`probe` quantifies that non-reproduction; `race` runs the actual comparison on
windows both arms share exactly.

Usage:
    python run_baseline_race.py race  --data-dir _data      --label usdc_served
    python run_baseline_race.py race  --data-dir _data_usdt --label usdt_trained \
        --episode-bars 250 --n-episodes 2 --min-lead-in 200 --rolling-stride 0
    python run_baseline_race.py probe --data-dir _data
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import sim14_bootstrap  # noqa: E402

sim14_bootstrap.bind()

from fixed_width_rule_policy import build_rule_policies  # noqa: E402
from kongtrae.training.hedged_hierarchical_policy import (  # noqa: E402
    run_always_cash_episode,
    run_paper_threshold_policy_episode,
    run_three_head_policy_episode,
    trace_metrics,
)
from kongtrae.training.train_hedged_three_head_v2_dqn import (  # noqa: E402
    _v2_env_kwargs,
    build_policy,
)
from kongtrae.training.uniswap_v3_ppo_paper import prepare_interval_data  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))

ACTION_WIDTHS = (4, 6, 10, 20)
CAPITAL = 1000.0
HEDGE_MODE = "continuous_delta_hedged"
SEED = 42
TIMEFRAME = "1h"
HOURS_PER_MONTH = 730

# Published held-out PnL per fold for the 1h lineage
# (models/three_head_v3_1h/manifest.json). Fold 0 is the shipped top-level alias.
# Kept here only so `probe` can show how far a replay lands from them.
PUBLISHED_FOLD_TEST_PNL = {
    0: 562.2133532168025,
    1: 435.3082631041309,
    2: 486.5188453641695,
    3: 717.6027948077616,
}


def resolve_dir(path: str) -> str:
    return path if os.path.isabs(path) else os.path.join(HERE, path)


def load_data(data_dir: str):
    return prepare_interval_data(resolve_dir(data_dir), timeframe=TIMEFRAME)


def make_dqn_policy(data, start_idx, end_idx):
    return build_policy(
        model_path=sim14_bootstrap.SHIPPED_1H_MODEL,
        vec_path=sim14_bootstrap.SHIPPED_1H_VECNORM,
        data=data,
        hedge_accounting_mode=HEDGE_MODE,
        action_widths=ACTION_WIDTHS,
        mode="all",
        start_idx=start_idx,
        end_idx=end_idx,
    )


def run_policy_episode(data, policy, start_idx, end_idx):
    return run_three_head_policy_episode(
        data=data,
        three_head_policy=policy,
        capital=CAPITAL,
        mode="all",
        seed=SEED,
        hedge_accounting_mode=HEDGE_MODE,
        start_idx=start_idx,
        end_idx=end_idx,
        action_widths=ACTION_WIDTHS,
        env_kwargs=_v2_env_kwargs(ACTION_WIDTHS),
    )


def episode_metrics(trace: pd.DataFrame) -> dict:
    """`trace_metrics` plus the race-specific columns."""
    metrics = dict(trace_metrics(trace))
    states = trace["position_state"]
    # Three-head episodes label the requested action `three_head_action_label`;
    # the always-cash and paper-rule runners use the two-action env and call it
    # `decision_label`.
    label_col = (
        "three_head_action_label"
        if "three_head_action_label" in trace.columns
        else "decision_label"
    )
    requested = trace[label_col].value_counts().to_dict()
    effective = trace["effective_action"].value_counts().to_dict()

    def col_sum(name):
        return float(trace[name].sum()) if name in trace.columns else 0.0

    metrics.update(
        {
            "steps": int(len(trace)),
            "cum_reward": float(trace["reward"].sum()),
            "cum_reward_usd": col_sum("reward_usd"),
            "lp_fee_usd": col_sum("fee_usd"),
            "funding_cost_usd": col_sum("funding_cost_usd"),
            "tx_cost_usd": col_sum("tx_cost_usd"),
            "hedge_pnl_usd": col_sum("hedge_pnl_usd"),
            "lp_value_change_usd": col_sum("lp_value_change_usd"),
            "il_realized_usd": col_sum("realized_boundary_pnl_usd"),
            "time_in_range_pct": float((states == "lp_in_range").mean() * 100.0),
            "time_oor_pct": float((states == "lp_oor").mean() * 100.0),
            "time_cash_pct": float((states == "cash").mean() * 100.0),
            "masked_invalid_actions": int(
                trace["masked_invalid_action"].sum()
                if "masked_invalid_action" in trace.columns
                else 0
            ),
            "requested_actions": requested,
            "effective_actions": effective,
            "n_hold": int(requested.get("hold", 0) + requested.get("hold_oor", 0)),
            "n_go_cash_requested": int(requested.get("go_cash", 0)),
            "n_stay_cash": int(requested.get("stay_cash", 0)),
            "n_entries": int(
                sum(v for k, v in requested.items() if k.startswith("enter_w"))
            ),
            "entry_widths": {
                k: int(v) for k, v in requested.items() if k.startswith("enter_w")
            },
        }
    )
    metrics["rebalance_count"] = int(metrics["enter_count"] + metrics["recenter_count"])
    return metrics


def plan_windows(n_bars: int, episode_bars: int, n_episodes: int, min_lead_in: int):
    """Non-overlapping episodes packed against the end of the series.

    Packing from the end keeps the newest data in the comparison and leaves the
    lead-in where the indicators need it: everything before the first episode is
    warmup for ma_200 and history for the paper rule's bb_width median.
    """
    span = episode_bars * n_episodes
    start = n_bars - span
    if start < min_lead_in:
        raise ValueError(
            f"{n_bars} bars cannot hold {n_episodes}x{episode_bars} episodes "
            f"plus {min_lead_in} bars of lead-in"
        )
    return [
        {"episode_id": i, "start_idx": start + i * episode_bars,
         "end_idx": start + (i + 1) * episode_bars}
        for i in range(n_episodes)
    ], start


def cmd_probe(args) -> int:
    """Show how far this pool's replay lands from the published fold PnLs."""
    data = load_data(args.data_dir)
    timestamps = list(data.timestamps)
    print(f"series: {len(timestamps)} bars, {timestamps[0]} -> {timestamps[-1]}")
    print(f"pool: fee={data.pool_fee * 100:.2f}%, tick_spacing={data.tick_spacing}")

    test_len = HOURS_PER_MONTH
    policy = make_dqn_policy(data, 0, min(test_len, len(timestamps)))
    starts = list(range(args.min_lead_in, len(timestamps) - test_len + 1, args.stride))
    print(f"replaying {len(starts)} windows of {test_len} bars, stride {args.stride}")

    best = None
    for s in starts:
        pnl = float(trace_metrics(run_policy_episode(data, policy, s, s + test_len))["pnl"])
        err = min(abs(pnl - p) for p in PUBLISHED_FOLD_TEST_PNL.values())
        if best is None or err < best["closest_err"]:
            best = {"start_idx": s, "start_ts": str(timestamps[s]), "pnl": pnl,
                    "closest_err": err}
        if args.verbose:
            print(f"  start {timestamps[s]} -> pnl {pnl:10.2f} (closest published err {err:8.2f})")

    print("\npublished 1h fold PnLs: " + ", ".join(
        f"f{k}=${v:.2f}" for k, v in sorted(PUBLISHED_FOLD_TEST_PNL.items())))
    print(f"closest replay on this pool: ${best['pnl']:.2f} at {best['start_ts']} "
          f"(off by ${best['closest_err']:.2f})")
    return 0


def _summarize(rows, key):
    values = [r[key] for r in rows]
    if not values:
        return 0.0, 0.0
    if len(values) < 2:
        return float(values[0]), 0.0
    return float(statistics.mean(values)), float(statistics.stdev(values))


def cmd_race(args) -> int:
    data = load_data(args.data_dir)
    timestamps = list(data.timestamps)
    results_dir = os.path.join(HERE, "results", args.label)
    os.makedirs(results_dir, exist_ok=True)

    episodes, lead_in = plan_windows(
        len(timestamps), args.episode_bars, args.n_episodes, args.min_lead_in
    )
    print(f"series: {len(timestamps)} bars, {timestamps[0]} -> {timestamps[-1]}")
    print(f"pool: fee={data.pool_fee * 100:.2f}%, tick_spacing={data.tick_spacing}")
    print(f"lead-in {lead_in} bars, then {len(episodes)}x{args.episode_bars}-bar episodes")

    rule_policies = build_rule_policies(ACTION_WIDTHS, args.widths)
    print(f"policies: shipped_dqn, {', '.join(sorted(rule_policies))}, "
          f"always_cash, paper_w4_threshold")

    records = []

    def record(kind, episode_id, policy_name, s, e, trace):
        m = episode_metrics(trace)
        m.update({
            "episode_kind": kind, "episode_id": episode_id, "policy": policy_name,
            "start_idx": int(s), "end_idx": int(e),
            "start_ts": str(timestamps[s]), "end_ts": str(timestamps[e - 1]),
        })
        records.append(m)
        print(f"  {policy_name:30s} pnl={m['pnl']:9.2f} reward={m['cum_reward_usd']:9.2f} "
              f"fees={m['lp_fee_usd']:8.2f} tir={m['time_in_range_pct']:5.1f}% "
              f"rebal={m['rebalance_count']:3d} exits={m['exit_count']:3d}")

    def run_all_arms(kind, episode_id, s, e, include_references):
        dqn = make_dqn_policy(data, s, e)
        record(kind, episode_id, "shipped_dqn", s, e, run_policy_episode(data, dqn, s, e))
        for name, policy in sorted(rule_policies.items()):
            record(kind, episode_id, name, s, e, run_policy_episode(data, policy, s, e))
        if not include_references:
            return
        record(kind, episode_id, "always_cash", s, e, run_always_cash_episode(
            data=data, capital=CAPITAL, mode="all", seed=SEED,
            hedge_accounting_mode=HEDGE_MODE, start_idx=s, end_idx=e))
        record(kind, episode_id, "paper_w4_threshold", s, e,
               run_paper_threshold_policy_episode(
                   data=data, train_start_idx=max(s - HOURS_PER_MONTH, 0),
                   train_end_idx=s, capital=CAPITAL, mode="all", seed=SEED,
                   hedge_accounting_mode=HEDGE_MODE, start_idx=s, end_idx=e,
                   fixed_width=4))

    for ep in episodes:
        s, e = ep["start_idx"], ep["end_idx"]
        print(f"\nepisode {ep['episode_id']}: {timestamps[s]} -> {timestamps[e - 1]} "
              f"({e - s} bars)")
        run_all_arms("episode", ep["episode_id"], s, e, include_references=True)

    if args.rolling_stride > 0:
        span_start, span_end = episodes[0]["start_idx"], episodes[-1]["end_idx"]
        window = args.rolling_window
        starts = list(range(span_start, span_end - window + 1, args.rolling_stride))
        print(f"\nrolling sweep: {len(starts)} windows of {window} bars, "
              f"stride {args.rolling_stride}")
        for k, s in enumerate(starts):
            e = s + window
            print(f"\nrolling {k}: {timestamps[s]} -> {timestamps[e - 1]}")
            run_all_arms("rolling", k, s, e, include_references=False)

    frame = pd.DataFrame(records)
    flat = frame.drop(columns=["requested_actions", "effective_actions", "entry_widths"])
    flat.to_csv(os.path.join(results_dir, "episodes.csv"), index=False)
    with open(os.path.join(results_dir, "episodes.json"), "w") as fh:
        json.dump(records, fh, indent=2, default=str)

    summary = {}
    for kind in frame["episode_kind"].unique():
        subset = frame[frame["episode_kind"] == kind]
        summary[kind] = {}
        dqn_by_ep = {
            r["episode_id"]: r["pnl"]
            for r in subset[subset["policy"] == "shipped_dqn"].to_dict("records")
        }
        for policy in sorted(subset["policy"].unique()):
            rows = subset[subset["policy"] == policy].to_dict("records")
            entry = {"n_episodes": len(rows)}
            for key in ("pnl", "cum_reward_usd", "lp_fee_usd", "funding_cost_usd",
                        "tx_cost_usd", "time_in_range_pct", "time_cash_pct",
                        "rebalance_count", "exit_count", "enter_count",
                        "recenter_count", "raw_boundary_il_last_usd",
                        "raw_swing_pnl_usd", "il_realized_usd", "steps"):
                mean, sd = _summarize(rows, key)
                entry[f"{key}_mean"], entry[f"{key}_sd"] = mean, sd
            entry["pnl_per_episode"] = [float(r["pnl"]) for r in rows]
            if policy != "shipped_dqn":
                deltas = [float(r["pnl"] - dqn_by_ep[r["episode_id"]])
                          for r in rows if r["episode_id"] in dqn_by_ep]
                if deltas:
                    entry["pnl_delta_vs_dqn"] = deltas
                    entry["pnl_delta_vs_dqn_mean"] = float(statistics.mean(deltas))
                    entry["pnl_delta_vs_dqn_sd"] = (
                        float(statistics.stdev(deltas)) if len(deltas) > 1 else 0.0)
                    entry["wins_vs_dqn"] = int(sum(1 for d in deltas if d > 0))
            summary[kind][policy] = entry

    meta = {
        "label": args.label,
        "data_dir": resolve_dir(args.data_dir),
        "pool_fee": float(data.pool_fee),
        "tick_spacing": int(data.tick_spacing),
        "series_start": str(timestamps[0]),
        "series_end": str(timestamps[-1]),
        "series_bars": len(timestamps),
        "lead_in_bars": int(lead_in),
        "episodes": [
            {**ep, "start_ts": str(timestamps[ep["start_idx"]]),
             "end_ts": str(timestamps[ep["end_idx"] - 1])} for ep in episodes
        ],
        "seed": SEED,
        "capital": CAPITAL,
        "action_widths": list(ACTION_WIDTHS),
        "hedge_accounting_mode": HEDGE_MODE,
        "model_path": sim14_bootstrap.SHIPPED_1H_MODEL,
        "vecnormalize_path": sim14_bootstrap.SHIPPED_1H_VECNORM,
        "env_kwargs": {k: str(v) for k, v in _v2_env_kwargs(ACTION_WIDTHS).items()},
    }
    with open(os.path.join(results_dir, "summary.json"), "w") as fh:
        json.dump({"meta": meta, "summary": summary}, fh, indent=2)

    print(f"\nwrote {results_dir}/episodes.csv and summary.json")
    for kind in summary:
        print(f"\n=== {kind} ===")
        for policy, entry in sorted(summary[kind].items()):
            delta = entry.get("pnl_delta_vs_dqn_mean")
            tail = "" if delta is None else (
                f"  delta_vs_dqn={delta:+9.2f} (wins {entry['wins_vs_dqn']}/{entry['n_episodes']})")
            print(f"  {policy:30s} n={entry['n_episodes']:2d} "
                  f"pnl={entry['pnl_mean']:9.2f} +/- {entry['pnl_sd']:7.2f}{tail}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_race = sub.add_parser("race", help="run every policy over identical windows")
    p_race.add_argument("--data-dir", default="_data")
    p_race.add_argument("--label", default="usdc_served")
    p_race.add_argument("--widths", type=int, nargs="+", default=[10, 4, 6, 20])
    p_race.add_argument("--episode-bars", type=int, default=730)
    p_race.add_argument("--n-episodes", type=int, default=4)
    p_race.add_argument("--min-lead-in", type=int, default=730)
    p_race.add_argument("--rolling-window", type=int, default=730)
    p_race.add_argument("--rolling-stride", type=int, default=168)
    p_race.set_defaults(func=cmd_race)

    p_probe = sub.add_parser(
        "probe", help="show how far this pool's replay lands from the published folds")
    p_probe.add_argument("--data-dir", default="_data")
    p_probe.add_argument("--min-lead-in", type=int, default=200)
    p_probe.add_argument("--stride", type=int, default=24)
    p_probe.add_argument("--verbose", action="store_true")
    p_probe.set_defaults(func=cmd_probe)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
