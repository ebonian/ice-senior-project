from __future__ import annotations

import os

import pandas as pd

from kongtrae.training.uniswap_v3_hedged_fee_env import (
    HEDGE_ACCOUNTING_CONTINUOUS,
    HOLD_ACTION,
    UniswapV3HedgedFeeEnv,
    width_to_action,
)


def _scenario_cache_path(args, action_widths, horizon_hours: int, margin_usd: float, start_idx=None, end_idx=None):
    widths = "_".join(str(w) for w in action_widths)
    timeframe = str(getattr(args, "timeframe", "1h")).replace(" ", "").replace("/", "_")
    window_suffix = ""
    if start_idx is not None and end_idx is not None:
        window_suffix = f"_idx{int(start_idx)}_{int(end_idx)}"
    return os.path.join(
        "debug_outputs",
        (
            f"profit_scenarios_train_{getattr(args, 'hedge_accounting_mode', HEDGE_ACCOUNTING_CONTINUOUS)}"
            f"_tf{timeframe}"
            f"_h{int(horizon_hours)}_s{args.profit_scan_stride}"
            f"_m{str(float(margin_usd)).replace('.', 'p')}"
            f"_w{widths}.csv"
        ).replace(".csv", f"{window_suffix}.csv"),
    )


def _build_or_load_profit_scenario_df(
    data,
    args,
    action_widths,
    horizon_hours: int,
    margin_usd: float,
    start_idx=None,
    end_idx=None,
):
    cache_path = _scenario_cache_path(args, action_widths, horizon_hours, margin_usd, start_idx, end_idx)
    if os.path.exists(cache_path):
        cached = pd.read_csv(cache_path)
        return cached, cache_path, False

    raw_env = UniswapV3HedgedFeeEnv(
        data,
        initial_capital_usd=args.capital,
        mode="train",
        hedge_accounting_mode=args.hedge_accounting_mode,
        start_idx=start_idx,
        end_idx=end_idx,
    )
    width_actions = {width: width_to_action(width) for width in action_widths}
    records = []
    horizon_steps = max(
        int(round(float(horizon_hours) * float(getattr(data, "periods_per_hour", 1.0)))),
        1,
    )
    max_i = max(raw_env.n_steps - horizon_steps - 1, 0)
    for start_idx_i in range(0, max_i, max(int(args.profit_scan_stride), 1)):
        best_reward = -float("inf")
        best_width = int(action_widths[0])
        for width in action_widths:
            raw_env.reset(seed=args.seed)
            raw_env.idx = int(start_idx_i)
            raw_env._set_cash_state(raw_env.initial_capital)
            reward_usd = 0.0
            _, _, done, _, info = raw_env.step(width_actions[width])
            reward_usd += float(info["reward_usd"])
            steps = 1
            while not done and steps < horizon_steps:
                _, _, done, _, info = raw_env.step(HOLD_ACTION)
                reward_usd += float(info["reward_usd"])
                steps += 1
            if reward_usd > best_reward:
                best_reward = reward_usd
                best_width = int(width)
        records.append(
            {
                "start_idx": int(start_idx_i),
                "best_width": int(best_width),
                "best_reward_usd": float(best_reward),
                "positive": float(best_reward > float(margin_usd)),
            }
        )

    scenario_df = pd.DataFrame(records)
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    scenario_df.to_csv(cache_path, index=False)
    return scenario_df, cache_path, True
