"""
Train the v2 realistic 3-head Double+Dueling DQN.

Shipped Kongtrae configuration:
  cash:
    0 = stay_cash
    1 = enter_w4
    2 = enter_w6
    3 = enter_w10
    4 = enter_w20
    5 = masked

  lp_in_range:
    0 = hold
    1 = go_cash
    2..5 = masked

  lp_oor:
    0 = hold_oor
    1 = go_cash
    2 = recenter_same_width
    3..5 = masked
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import sys
from collections import Counter
from typing import Iterable, Optional

import numpy as np

os.environ.setdefault("MPLCONFIGDIR", "/tmp")

PACKAGE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKAGE_PARENT = os.path.dirname(PACKAGE_ROOT)
if PACKAGE_PARENT not in sys.path:
    sys.path.insert(0, PACKAGE_PARENT)

from stable_baselines3.common.callbacks import CheckpointCallback
from stable_baselines3.common.monitor import Monitor
from stable_baselines3.common.vec_env import DummyVecEnv, VecNormalize

from kongtrae.training.hedged_hierarchical_policy import (
    NormalizedDQNPolicy,
    Q_ALGO_THREE_HEAD_DDQN_DUELING,
    run_three_head_policy_episode,
    trace_metrics,
)
from kongtrae.training.sb3_vecnormalize_callbacks import (
    EvalCallbackWithVecNormalize,
    VecNormalizeCheckpointCallback,
)
from kongtrae.training.three_head_dueling_dqn import ThreeHeadDoubleDuelingDQN
from kongtrae.training.profit_scan import _build_or_load_profit_scenario_df
from kongtrae.training.uniswap_v3_hedged_fee_env import (
    HEDGE_ACCOUNTING_CONTINUOUS,
    HEDGE_ACCOUNTING_DEFAULT,
    HEDGE_ACCOUNTING_IDEALIZED,
    HEDGE_ACCOUNTING_LEGACY,
    TRAINING_REWARD_FEE_TX_PATIENCE,
    TRAINING_REWARD_REALISTIC,
)
from kongtrae.training.uniswap_v3_hedged_hierarchical_env import (
    THREE_HEAD_CASH,
    THREE_HEAD_IN_RANGE,
    THREE_HEAD_OOR,
    build_three_head_masks,
    three_head_num_actions_for_widths,
    UniswapV3HedgedThreeHeadEnv,
)
from kongtrae.training.uniswap_v3_ppo_paper import prepare_interval_data

# Observation layout constants (relative to state one-hot prefix)
PAPER_RATIO_IDX = 3
PAPER_SIGNAL_IDX = 4
CANDIDATE_FEATURE_START = 5


def _v2_env_kwargs(
    action_widths,
    recenter_cooldown_hours: float = 0.0,
    recenter_emergency_oor_sigma: float = 2.5,
    fee_haircut: float = 1.0,
    active_liquidity_multiplier: float = 1.0,
):
    """Build env kwargs for the given widths."""
    return dict(
        action_widths=tuple(action_widths),
        allow_in_range_recenter=False,
        oor_recenter_same_width_only=True,
        recenter_cooldown_hours=float(recenter_cooldown_hours),
        recenter_emergency_oor_sigma=float(recenter_emergency_oor_sigma),
        fee_haircut=float(fee_haircut),
        active_liquidity_multiplier=float(active_liquidity_multiplier),
        include_paper_signal_features=True,
    )


def _v2_policy_state_action_masks(action_widths):
    """Return policy masks matching the shipped v2 env action semantics."""
    masks = build_three_head_masks(action_widths)
    num_actions = masks.shape[1]

    # v2 deliberately keeps LP decisions simple:
    # in-range can only hold or exit; OOR can hold, exit, or recenter same width.
    lp_in_range_mask = np.zeros(num_actions, dtype=np.bool_)
    lp_in_range_mask[:2] = True

    lp_oor_mask = np.zeros(num_actions, dtype=np.bool_)
    lp_oor_mask[:2] = True
    lp_oor_mask[2] = True

    masks[1] = lp_in_range_mask
    masks[2] = lp_oor_mask
    return masks.tolist()


def parse_action_widths(widths_arg: str):
    widths = tuple(int(w.strip()) for w in widths_arg.split(",") if w.strip())
    if not widths:
        raise ValueError("At least one action width is required")
    return widths


def width_action_for_cash(width: int, action_widths) -> int:
    widths = tuple(int(w) for w in action_widths)
    if int(width) not in widths:
        raise ValueError(f"Unsupported v2 cash width: {width}")
    return 1 + widths.index(int(width))


def print_metrics(label, trace_df):
    metrics = trace_metrics(trace_df)
    print(
        f"  {label:<14} PV=${metrics['final_pv']:.0f} "
        f"(PnL=${metrics['pnl']:+.0f}), "
        f"{metrics['cash_pct']:.0f}% cash, "
        f"{metrics['oor_pct']:.0f}% OOR, "
        f"{metrics['trade_count']} trades, "
        f"gross_carry=${metrics['gross_fee_carry_usd']:+.0f}, "
        f"raw_swing=${metrics['raw_swing_pnl_usd']:+.0f}"
    )


def make_env(
    data,
    mode,
    capital,
    seed,
    action_widths=(10, 20),
    randomize_start=False,
    hedge_accounting_mode=HEDGE_ACCOUNTING_DEFAULT,
    min_episode_hours=72,
    max_episode_hours=168,
    cash_start_prob=0.60,
    in_range_start_prob=0.20,
    oor_start_prob=0.20,
    positive_start_indices=(),
    hard_negative_start_indices=(),
    start_idx=None,
    end_idx=None,
    training_reward_mode=TRAINING_REWARD_REALISTIC,
    reward_scale=1.0,
    recenter_cooldown_hours=0.0,
    recenter_emergency_oor_sigma=2.5,
    fee_haircut=1.0,
    active_liquidity_multiplier=1.0,
):
    env_kwargs = _v2_env_kwargs(
        action_widths,
        recenter_cooldown_hours=recenter_cooldown_hours,
        recenter_emergency_oor_sigma=recenter_emergency_oor_sigma,
        fee_haircut=fee_haircut,
        active_liquidity_multiplier=active_liquidity_multiplier,
    )

    def _init():
        env = UniswapV3HedgedThreeHeadEnv(
            data,
            initial_capital_usd=capital,
            mode=mode,
            start_idx=start_idx,
            end_idx=end_idx,
            randomize_start=randomize_start,
            hedge_accounting_mode=hedge_accounting_mode,
            min_episode_hours=min_episode_hours,
            max_episode_hours=max_episode_hours,
            cash_start_prob=cash_start_prob,
            in_range_start_prob=in_range_start_prob,
            oor_start_prob=oor_start_prob,
            positive_start_indices=positive_start_indices,
            hard_negative_start_indices=hard_negative_start_indices,
            training_reward_mode=training_reward_mode,
            reward_scale=reward_scale,
            **env_kwargs,
        )
        env = Monitor(env)
        if seed is not None:
            env.reset(seed=seed)
        return env

    return _init


def compute_balanced_cash_start_sets(
    data,
    args,
    action_widths,
    start_idx=None,
    end_idx=None,
):
    scenario_df, cache_path, built = _build_or_load_profit_scenario_df(
        data=data,
        args=args,
        action_widths=action_widths,
        horizon_hours=args.profit_scan_horizon_hours,
        margin_usd=args.profit_scan_margin_usd,
        start_idx=start_idx,
        end_idx=end_idx,
    )
    positive_mask = scenario_df["positive"] > 0.5
    positive_indices = tuple(int(idx) for idx in scenario_df.loc[positive_mask, "start_idx"].tolist())
    hard_negative_indices = tuple(
        int(idx)
        for idx in scenario_df.loc[
            scenario_df["best_reward_usd"] <= float(args.hard_negative_margin_usd),
            "start_idx",
        ].tolist()
    )
    width_counts = (
        scenario_df.loc[positive_mask, "best_width"].value_counts().sort_index().to_dict()
    )
    print(
        "  cash_start_scenarios="
        f"{cache_path} ({'built' if built else 'loaded'}, "
        f"positive={len(positive_indices)}, hard_negative={len(hard_negative_indices)}, "
        f"positive_width_counts={width_counts})"
    )
    return positive_indices, hard_negative_indices


class AlwaysCashThreeHeadV2Policy:
    def predict(self, obs, return_q=False):
        return type("Pred", (), {"value": 0})()


class PaperPriorThreeHeadV2Policy:
    def __init__(self, action_widths):
        self.action_widths = tuple(int(w) for w in action_widths)
        self._num_actions = three_head_num_actions_for_widths(self.action_widths)

    def predict(self, obs, return_q=False):
        state = (THREE_HEAD_CASH, THREE_HEAD_IN_RANGE, THREE_HEAD_OOR)[
            int(np.argmax(np.asarray(obs[:3], dtype=np.float32)))
        ]
        if state == THREE_HEAD_CASH:
            signal_on = float(obs[PAPER_SIGNAL_IDX]) > 0.5
            if not signal_on:
                value = 0
            else:
                # Pick width with best fee_il_ratio among candidates with hours_to_oor >= 0.03
                best_value = 1  # default: first width
                best_fee_il = -1.0
                for i, w in enumerate(self.action_widths):
                    hours_feat = float(obs[CANDIDATE_FEATURE_START + 2 * i])
                    fee_feat = float(obs[CANDIDATE_FEATURE_START + 2 * i + 1])
                    if hours_feat >= 0.03 and fee_feat > best_fee_il:
                        best_fee_il = fee_feat
                        best_value = width_action_for_cash(w, self.action_widths)
                value = best_value
        elif state == THREE_HEAD_IN_RANGE:
            value = 0
        else:
            value = 0
        num_a = self._num_actions
        q_values = np.linspace(0.0, 1.0, num_a, dtype=np.float32) if return_q else None
        return type("Pred", (), {"value": int(value), "q_values": q_values})()


def build_prefill_policies(prefill_policy_names: Iterable[str], action_widths):
    policies = []
    for name in prefill_policy_names:
        if name == "always_cash":
            policies.append((name, AlwaysCashThreeHeadV2Policy()))
        elif name == "paper_prior":
            policies.append((name, PaperPriorThreeHeadV2Policy(action_widths)))
        else:
            raise ValueError(f"Unsupported v2 prefill policy: {name}")
    return policies


def prefill_three_head_v2_replay_buffer(
    model,
    train_env,
    eval_env,
    data,
    args,
    action_widths,
):
    if args.prefill_transitions <= 0:
        return 0
    policy_names = [name.strip() for name in args.prefill_policies.split(",") if name.strip()]
    if not policy_names:
        return 0
    policies = build_prefill_policies(policy_names, action_widths)
    raw_env = UniswapV3HedgedThreeHeadEnv(
        data,
        initial_capital_usd=args.capital,
        mode="train" if args.start_idx is None and args.end_idx is None else "all",
        start_idx=args.start_idx,
        end_idx=args.end_idx,
        hedge_accounting_mode=args.hedge_accounting_mode,
        training_reward_mode=args.training_reward_mode,
        reward_scale=args.reward_scale,
        **_v2_env_kwargs(
            action_widths,
            recenter_cooldown_hours=args.recenter_cooldown_hours,
            recenter_emergency_oor_sigma=args.recenter_emergency_oor_sigma,
            fee_haircut=args.fee_haircut,
            active_liquidity_multiplier=args.active_liquidity_multiplier,
        ),
    )

    added = 0
    episode_idx = 0
    while added < args.prefill_transitions:
        policy_name, policy = policies[episode_idx % len(policies)]
        obs, _ = raw_env.reset(seed=args.seed + episode_idx)
        terminated = False
        while not terminated and added < args.prefill_transitions:
            pred = policy.predict(obs, return_q=False)
            action = int(pred.value)
            raw_obs_batch = np.asarray([obs], dtype=np.float32)
            train_env.obs_rms.update(raw_obs_batch)
            obs_norm = train_env.normalize_obs(raw_obs_batch)

            next_obs, reward, terminated, truncated, info = raw_env.step(action)
            raw_next_obs_batch = np.asarray([next_obs], dtype=np.float32)
            train_env.obs_rms.update(raw_next_obs_batch)
            next_obs_norm = train_env.normalize_obs(raw_next_obs_batch)

            model.replay_buffer.add(
                obs=obs_norm,
                next_obs=next_obs_norm,
                action=np.asarray([[action]], dtype=np.int64),
                reward=np.asarray([reward], dtype=np.float32),
                done=np.asarray([terminated or truncated], dtype=np.float32),
                infos=[{**info, "prefill_policy": policy_name}],
            )
            obs = next_obs
            added += 1
        episode_idx += 1

    eval_env.obs_rms = copy.deepcopy(train_env.obs_rms)
    return added


def discover_checkpoint_pairs(checkpoint_dir: str, prefix: str):
    pairs = []
    if not os.path.isdir(checkpoint_dir):
        return pairs
    for filename in sorted(os.listdir(checkpoint_dir)):
        if not filename.endswith("_steps.zip") or not filename.startswith(prefix + "_"):
            continue
        model_path = os.path.join(checkpoint_dir, filename)
        vec_path = model_path.replace(".zip", "_vecnormalize.pkl")
        if not os.path.exists(vec_path):
            continue
        step_str = filename.replace(prefix + "_", "").replace("_steps.zip", "")
        try:
            steps = int(step_str)
        except ValueError:
            steps = -1
        pairs.append((steps, model_path, vec_path))
    return pairs


def build_policy(
    model_path: str,
    vec_path: Optional[str],
    data,
    hedge_accounting_mode: str,
    mode: str,
    action_widths=(10, 20),
    start_idx=None,
    end_idx=None,
    recenter_cooldown_hours=0.0,
    recenter_emergency_oor_sigma=2.5,
    fee_haircut=1.0,
    active_liquidity_multiplier=1.0,
):
    num_actions = three_head_num_actions_for_widths(action_widths)
    env_kwargs = _v2_env_kwargs(
        action_widths,
        recenter_cooldown_hours=recenter_cooldown_hours,
        recenter_emergency_oor_sigma=recenter_emergency_oor_sigma,
        fee_haircut=fee_haircut,
        active_liquidity_multiplier=active_liquidity_multiplier,
    )
    return NormalizedDQNPolicy.load(
        model_path=model_path,
        vec_path=vec_path,
        action_values=list(range(num_actions)),
        data=data,
        algo=Q_ALGO_THREE_HEAD_DDQN_DUELING,
        hedge_accounting_mode=hedge_accounting_mode,
        mode=mode,
        vec_env_factory=lambda: UniswapV3HedgedThreeHeadEnv(
            data,
            initial_capital_usd=1000.0,
            mode=mode,
            start_idx=start_idx,
            end_idx=end_idx,
            hedge_accounting_mode=hedge_accounting_mode,
            **env_kwargs,
        ),
    )


def score_checkpoint_windows(
    policy,
    data,
    hedge_accounting_mode: str,
    action_widths,
    train_window: tuple[str, Optional[int], Optional[int]],
    eval_window: tuple[str, Optional[int], Optional[int]],
    test_window: tuple[str, Optional[int], Optional[int]],
    recenter_cooldown_hours=0.0,
    recenter_emergency_oor_sigma=2.5,
    fee_haircut=1.0,
    active_liquidity_multiplier=1.0,
):
    env_kwargs = _v2_env_kwargs(
        action_widths,
        recenter_cooldown_hours=recenter_cooldown_hours,
        recenter_emergency_oor_sigma=recenter_emergency_oor_sigma,
        fee_haircut=fee_haircut,
        active_liquidity_multiplier=active_liquidity_multiplier,
    )
    rows = {}
    for label, (mode, start_idx, end_idx) in {
        "train": train_window,
        "eval": eval_window,
        "test": test_window,
    }.items():
        trace = run_three_head_policy_episode(
            data=data,
            three_head_policy=policy,
            capital=1000.0,
            mode=mode,
            hedge_accounting_mode=hedge_accounting_mode,
            start_idx=start_idx,
            end_idx=end_idx,
            action_widths=tuple(action_widths),
            env_kwargs=env_kwargs,
        )
        metrics = trace_metrics(trace)
        rows[f"{label}_pnl"] = float(metrics["pnl"])
        rows[f"{label}_pv"] = float(metrics["final_pv"])
        rows[f"{label}_cash_pct"] = float(metrics["cash_pct"])
        rows[f"{label}_oor_pct"] = float(metrics["oor_pct"])
        rows[f"{label}_trade_count"] = int(metrics["trade_count"])
    return rows


def score_saved_checkpoints(
    data,
    save_name: str,
    hedge_accounting_mode: str,
    action_widths=(10, 20),
    train_window: tuple[str, Optional[int], Optional[int]] = ("train", None, None),
    eval_window: tuple[str, Optional[int], Optional[int]] = ("eval", None, None),
    test_window: tuple[str, Optional[int], Optional[int]] = ("test", None, None),
    recenter_cooldown_hours=0.0,
    recenter_emergency_oor_sigma=2.5,
    fee_haircut=1.0,
    active_liquidity_multiplier=1.0,
):
    pairs = discover_checkpoint_pairs(f"checkpoints_{save_name}", save_name)
    best_dir_model = os.path.join(f"{save_name}_best", "best_model.zip")
    best_dir_vec = os.path.join(f"{save_name}_best", "best_vecnormalize.pkl")
    if os.path.exists(best_dir_model) and os.path.exists(best_dir_vec):
        pairs.append((-1, best_dir_model, best_dir_vec))
    rows = []
    for steps, model_path, vec_path in pairs:
        policy = build_policy(
            model_path=model_path,
            vec_path=vec_path,
            data=data,
            hedge_accounting_mode=hedge_accounting_mode,
            action_widths=action_widths,
            mode="all" if train_window[1] is not None else "train",
            start_idx=train_window[1],
            end_idx=train_window[2],
            recenter_cooldown_hours=recenter_cooldown_hours,
            recenter_emergency_oor_sigma=recenter_emergency_oor_sigma,
            fee_haircut=fee_haircut,
            active_liquidity_multiplier=active_liquidity_multiplier,
        )
        row = score_checkpoint_windows(
            policy=policy,
            data=data,
            hedge_accounting_mode=hedge_accounting_mode,
            action_widths=action_widths,
            train_window=train_window,
            eval_window=eval_window,
            test_window=test_window,
            recenter_cooldown_hours=recenter_cooldown_hours,
            recenter_emergency_oor_sigma=recenter_emergency_oor_sigma,
            fee_haircut=fee_haircut,
            active_liquidity_multiplier=active_liquidity_multiplier,
        )
        row["steps"] = int(steps)
        row["model_path"] = model_path
        row["vec_path"] = vec_path
        rows.append(row)
    rows.sort(key=lambda row: row["eval_pnl"], reverse=True)
    return rows


def train(args):
    data = prepare_interval_data(args.data_dir, timeframe=args.timeframe)
    action_widths = parse_action_widths(args.action_widths)
    train_start_idx = getattr(args, "start_idx", None)
    train_end_idx = getattr(args, "end_idx", None)
    eval_start_idx = getattr(args, "eval_start_idx", None)
    eval_end_idx = getattr(args, "eval_end_idx", None)
    final_eval_start_idx = getattr(args, "final_eval_start_idx", None)
    final_eval_end_idx = getattr(args, "final_eval_end_idx", None)

    positive_start_indices, hard_negative_start_indices = compute_balanced_cash_start_sets(
        data=data,
        args=args,
        action_widths=action_widths,
        start_idx=train_start_idx,
        end_idx=train_end_idx,
    )

    train_env = DummyVecEnv(
        [
            make_env(
                data=data,
                mode="train" if train_start_idx is None and train_end_idx is None else "all",
                capital=args.capital,
                seed=args.seed,
                action_widths=action_widths,
                randomize_start=True,
                hedge_accounting_mode=args.hedge_accounting_mode,
                min_episode_hours=args.min_episode_hours,
                max_episode_hours=args.max_episode_hours,
                cash_start_prob=args.cash_start_prob,
                in_range_start_prob=args.in_range_start_prob,
                oor_start_prob=args.oor_start_prob,
                positive_start_indices=positive_start_indices,
                hard_negative_start_indices=hard_negative_start_indices,
                start_idx=train_start_idx,
                end_idx=train_end_idx,
                training_reward_mode=args.training_reward_mode,
                reward_scale=args.reward_scale,
                recenter_cooldown_hours=args.recenter_cooldown_hours,
                recenter_emergency_oor_sigma=args.recenter_emergency_oor_sigma,
                fee_haircut=args.fee_haircut,
                active_liquidity_multiplier=args.active_liquidity_multiplier,
            )
        ]
    )
    train_env = VecNormalize(train_env, norm_obs=True, norm_reward=False, clip_obs=10.0)

    eval_env = DummyVecEnv(
        [
            make_env(
                data=data,
                mode="eval" if eval_start_idx is None and eval_end_idx is None else "all",
                capital=args.capital,
                seed=args.seed + 1000,
                action_widths=action_widths,
                randomize_start=False,
                hedge_accounting_mode=args.hedge_accounting_mode,
                min_episode_hours=args.min_episode_hours,
                max_episode_hours=args.max_episode_hours,
                cash_start_prob=1.0,
                in_range_start_prob=0.0,
                oor_start_prob=0.0,
                positive_start_indices=(),
                hard_negative_start_indices=(),
                start_idx=eval_start_idx,
                end_idx=eval_end_idx,
                training_reward_mode=args.training_reward_mode,
                reward_scale=args.reward_scale,
                recenter_cooldown_hours=args.recenter_cooldown_hours,
                recenter_emergency_oor_sigma=args.recenter_emergency_oor_sigma,
                fee_haircut=args.fee_haircut,
                active_liquidity_multiplier=args.active_liquidity_multiplier,
            )
        ]
    )
    eval_env = VecNormalize(eval_env, norm_obs=True, norm_reward=False, clip_obs=10.0)
    eval_env.training = False

    model = ThreeHeadDoubleDuelingDQN(
        "MlpPolicy",
        train_env,
        learning_rate=args.lr,
        buffer_size=args.buffer_size,
        learning_starts=args.learning_starts,
        batch_size=args.batch_size,
        tau=args.tau,
        gamma=args.gamma,
        train_freq=args.train_freq,
        target_update_interval=args.target_update_interval,
        exploration_fraction=args.exploration_fraction,
        exploration_initial_eps=args.exploration_initial_eps,
        exploration_final_eps=args.exploration_final_eps,
        policy_kwargs=dict(
            net_arch=args.net_arch,
            state_action_masks=_v2_policy_state_action_masks(action_widths),
        ),
        verbose=1,
        seed=args.seed,
        tensorboard_log=args.tb_log,
    )

    added_prefill = prefill_three_head_v2_replay_buffer(
        model=model,
        train_env=train_env,
        eval_env=eval_env,
        data=data,
        args=args,
        action_widths=action_widths,
    )

    eval_callback = EvalCallbackWithVecNormalize(
        eval_env,
        best_model_save_path=f"./{args.save_name}_best/",
        log_path=f"./eval_logs_{args.save_name}/",
        eval_freq=args.eval_freq,
        n_eval_episodes=1,
        deterministic=True,
        verbose=1,
    )
    checkpoint_callback = CheckpointCallback(
        save_freq=args.checkpoint_freq,
        save_path=f"./checkpoints_{args.save_name}/",
        name_prefix=args.save_name,
    )
    vec_checkpoint_callback = VecNormalizeCheckpointCallback(
        save_freq=args.checkpoint_freq,
        save_path=f"./checkpoints_{args.save_name}/",
        name_prefix=args.save_name,
    )

    print("\nThree-head Double+Dueling DQN v2")
    print(f"  total_timesteps={args.total_timesteps}, capital=${args.capital}")
    print(f"  gamma={args.gamma}, net_arch={args.net_arch}")
    print(f"  training_reward_mode={args.training_reward_mode}, reward_scale={args.reward_scale}")
    print(f"  hedge_accounting_mode={args.hedge_accounting_mode}")
    print(f"  action_widths={action_widths}")
    print(f"  policy_state_action_masks={_v2_policy_state_action_masks(action_widths)}")
    print(
        "  recenter_cooldown="
        f"{args.recenter_cooldown_hours:.2f}h, "
        f"emergency_oor_sigma={args.recenter_emergency_oor_sigma:.2f}"
    )
    print(
        "  fee_stress="
        f"fee_haircut={args.fee_haircut:.3f}, "
        f"active_liquidity_multiplier={args.active_liquidity_multiplier:.3f}"
    )
    print(
        f"  timeframe={data.timeframe} "
        f"({data.period_seconds:.0f}s bars, {data.periods_per_hour:.0f} bars/hour)"
    )
    print(f"  episode_hours={args.min_episode_hours}-{args.max_episode_hours}")
    print(
        "  state_start_probs="
        f"cash={args.cash_start_prob:.2f}, "
        f"in_range={args.in_range_start_prob:.2f}, "
        f"oor={args.oor_start_prob:.2f}"
    )
    print(
        "  balanced_cash_starts="
        f"positive={len(positive_start_indices)}, "
        f"hard_negative={len(hard_negative_start_indices)}"
    )
    if args.prefill_transitions > 0:
        print(
            f"  replay_prefill={added_prefill} transitions from {args.prefill_policies}"
        )

    model.learn(
        total_timesteps=args.total_timesteps,
        callback=[eval_callback, checkpoint_callback, vec_checkpoint_callback],
        progress_bar=True,
    )

    model.save(args.save_name)
    train_env.save(f"{args.save_name}_vec_normalize.pkl")

    train_window = (
        "train" if train_start_idx is None and train_end_idx is None else "all",
        train_start_idx,
        train_end_idx,
    )
    eval_window = (
        "eval" if eval_start_idx is None and eval_end_idx is None else "all",
        eval_start_idx,
        eval_end_idx,
    )
    test_window = (
        "test" if final_eval_start_idx is None and final_eval_end_idx is None else "all",
        final_eval_start_idx,
        final_eval_end_idx,
    )
    checkpoint_rows = score_saved_checkpoints(
        data=data,
        save_name=args.save_name,
        hedge_accounting_mode=args.hedge_accounting_mode,
        action_widths=action_widths,
        train_window=train_window,
        eval_window=eval_window,
        test_window=test_window,
        recenter_cooldown_hours=args.recenter_cooldown_hours,
        recenter_emergency_oor_sigma=args.recenter_emergency_oor_sigma,
        fee_haircut=args.fee_haircut,
        active_liquidity_multiplier=args.active_liquidity_multiplier,
    )
    checkpoint_scores_path = os.path.join(
        "debug_outputs", f"{args.save_name}_checkpoint_scores.json"
    )
    os.makedirs(os.path.dirname(checkpoint_scores_path), exist_ok=True)
    with open(checkpoint_scores_path, "w") as f:
        json.dump(checkpoint_rows, f, indent=2)

    best_row = checkpoint_rows[0]
    print(
        "\nCheckpoint selection (eval-ranked)"
        f"\n  steps={best_row['steps']}"
        f"\n  train_pnl={best_row['train_pnl']:.2f}"
        f"\n  eval_pnl={best_row['eval_pnl']:.2f}"
        f"\n  test_pnl={best_row['test_pnl']:.2f}"
        f"\n  checkpoint_scores={checkpoint_scores_path}"
    )

    policy = build_policy(
        model_path=best_row["model_path"],
        vec_path=best_row["vec_path"],
        data=data,
        hedge_accounting_mode=args.hedge_accounting_mode,
        action_widths=action_widths,
        mode=test_window[0],
        start_idx=test_window[1],
        end_idx=test_window[2],
        recenter_cooldown_hours=args.recenter_cooldown_hours,
        recenter_emergency_oor_sigma=args.recenter_emergency_oor_sigma,
        fee_haircut=args.fee_haircut,
        active_liquidity_multiplier=args.active_liquidity_multiplier,
    )
    trace = run_three_head_policy_episode(
        data=data,
        three_head_policy=policy,
        capital=args.capital,
        mode=test_window[0],
        hedge_accounting_mode=args.hedge_accounting_mode,
        action_widths=action_widths,
        start_idx=test_window[1],
        end_idx=test_window[2],
        env_kwargs=_v2_env_kwargs(
            action_widths,
            recenter_cooldown_hours=args.recenter_cooldown_hours,
            recenter_emergency_oor_sigma=args.recenter_emergency_oor_sigma,
            fee_haircut=args.fee_haircut,
            active_liquidity_multiplier=args.active_liquidity_multiplier,
        ),
    )
    print("\nThree-head v2 policy evaluation")
    print_metrics("ThreeHeadV2", trace)
    requested = Counter(trace["three_head_action_label"])
    effective = Counter(trace["effective_action"])
    print(f"  Requested: {dict(sorted(requested.items()))}")
    print(f"  Effective: {dict(sorted(effective.items()))}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train realistic 3-head Double+Dueling DQN v2")
    parser.add_argument("--data-dir", default="training_data")
    parser.add_argument("--timeframe", default="1h", help="Model bar size: 1h, 15min, or 5min")
    parser.add_argument("--save-name", default="ddqn_dueling_hedged_three_head_v2")
    parser.add_argument("--tb-log", default="tb_hedged_three_head_v2")
    parser.add_argument("--start-idx", type=int, default=None)
    parser.add_argument("--end-idx", type=int, default=None)
    parser.add_argument("--eval-start-idx", type=int, default=None)
    parser.add_argument("--eval-end-idx", type=int, default=None)
    parser.add_argument("--final-eval-start-idx", type=int, default=None)
    parser.add_argument("--final-eval-end-idx", type=int, default=None)
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
    parser.add_argument("--recenter-cooldown-hours", type=float, default=0.0)
    parser.add_argument("--recenter-emergency-oor-sigma", type=float, default=2.5)
    parser.add_argument("--fee-haircut", type=float, default=1.0)
    parser.add_argument("--active-liquidity-multiplier", type=float, default=1.0)
    parser.add_argument(
        "--hedge-accounting-mode",
        default=HEDGE_ACCOUNTING_CONTINUOUS,
        choices=[HEDGE_ACCOUNTING_IDEALIZED, HEDGE_ACCOUNTING_CONTINUOUS, HEDGE_ACCOUNTING_LEGACY],
    )
    parser.add_argument(
        "--training-reward-mode",
        default=TRAINING_REWARD_REALISTIC,
        choices=[TRAINING_REWARD_REALISTIC, TRAINING_REWARD_FEE_TX_PATIENCE],
    )
    parser.add_argument("--reward-scale", type=float, default=1.0)
    train(parser.parse_args())
