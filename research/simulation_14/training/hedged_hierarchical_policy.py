from dataclasses import dataclass
from typing import Iterable, Optional

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from sb3_contrib import QRDQN
from stable_baselines3 import DQN
from stable_baselines3.common.vec_env import DummyVecEnv, VecNormalize

from kongtrae.training.double_dueling_dqn import DoubleDuelingDQN, DuelingDQN
from kongtrae.training.three_head_dueling_dqn import (
    ThreeHeadDoubleDuelingDQN,
    ThreeHeadDuelingDQN,
)
from kongtrae.training.uniswap_v3_hedged_fee_env import (
    ENTRY_WIDTHS,
    HEDGE_ACCOUNTING_CONTINUOUS,
    HEDGE_ACCOUNTING_DEFAULT,
    GO_CASH_ACTION,
    HOLD_ACTION,
    UniswapV3HedgedFeeEnv,
    conservative_optimal_width_for_vol,
    optimal_width_for_vol,
    width_to_action,
)
from kongtrae.training.uniswap_v3_hedged_hierarchical_env import (
    BOUNDARY_ACTION_WIDTHS,
    BOUNDARY_TO_CASH,
    CASH_OOR_EXIT,
    CASH_OOR_HOLD_OR_STAY,
    IN_RANGE_EXIT,
    IN_RANGE_HOLD,
    N_CASH_OOR_ACTIONS,
    OOR_RECENTER_REQUESTED,
    OOR_RECENTER_SAME,
    THREE_HEAD_ACTION_WIDTHS,
    THREE_HEAD_CASH,
    THREE_HEAD_GO_CASH,
    THREE_HEAD_HOLD,
    THREE_HEAD_IN_RANGE,
    THREE_HEAD_NUM_ACTIONS,
    THREE_HEAD_OOR,
    TRAINING_OBJECTIVE_REALISTIC,
    UniswapV3HedgedCashOOREnv,
    UniswapV3HedgedThreeHeadEnv,
    cash_oor_num_actions,
    cash_oor_action_label,
    cash_oor_action_to_width,
    project_timing_observation,
    boundary_action_to_width,
    boundary_action_label,
    three_head_action_label,
    three_head_action_to_width,
)
from kongtrae.training.hedged_width_action_utils import (
    WIDTH_ACTION_MODE_ABSOLUTE,
    WIDTH_ACTION_MODE_HEURISTIC_DELTA,
    heuristic_width_from_obs,
    width_action_labels,
    width_action_values,
    width_decision_to_width,
)
from kongtrae.training.uniswap_v3_ppo_paper import FEATURE_COLS


TIMING_TO_CASH = 0
TIMING_TO_LP = 1
Q_ALGO_DQN = "dqn"
Q_ALGO_QRDQN = "qrdqn"
Q_ALGO_DUELING = "dueling"
Q_ALGO_DDQN_DUELING = "ddqn_dueling"
Q_ALGO_THREE_HEAD_DUELING = "three_head_dueling"
Q_ALGO_THREE_HEAD_DDQN_DUELING = "three_head_ddqn_dueling"
Q_ALGOS = (
    Q_ALGO_DQN,
    Q_ALGO_QRDQN,
    Q_ALGO_DUELING,
    Q_ALGO_DDQN_DUELING,
    Q_ALGO_THREE_HEAD_DUELING,
    Q_ALGO_THREE_HEAD_DDQN_DUELING,
)


@dataclass
class PolicyPrediction:
    value: int
    q_values: Optional[np.ndarray] = None
    raw_value: Optional[int] = None
    quantiles: Optional[np.ndarray] = None
    selected_quantile_iqr: Optional[float] = None
    selected_quantile_std: Optional[float] = None

    @property
    def q_gap(self) -> float:
        if self.q_values is None or len(self.q_values) < 2:
            return 0.0
        top2 = np.partition(self.q_values, -2)[-2:]
        return float(top2.max() - top2.min())

    @property
    def confidence_score(self) -> float:
        if self.selected_quantile_iqr is None:
            return self.q_gap
        return float(self.q_gap / max(float(self.selected_quantile_iqr), 1e-8))


class NormalizedDQNPolicy:
    """Q-network wrapper with VecNormalize-based observation scaling."""

    def __init__(
        self,
        model,
        obs_rms,
        action_values: Iterable[int],
        action_labels: Optional[Iterable[str]] = None,
        action_decoder=None,
        algo: str = Q_ALGO_DQN,
        timing_width_mode: str = "heuristic",
        timing_fixed_width: int = 10,
    ):
        self.model = model
        self.obs_rms = obs_rms
        self.action_values = list(action_values)
        self.action_labels = list(action_labels) if action_labels is not None else [
            str(v) for v in self.action_values
        ]
        self.action_decoder = action_decoder
        if algo not in Q_ALGOS:
            raise ValueError(f"Unsupported q-policy algo: {algo}")
        self.algo = algo
        self.timing_width_mode = timing_width_mode
        self.timing_fixed_width = int(timing_fixed_width)

    @classmethod
    def load(
        cls,
        model_path: str,
        vec_path: Optional[str],
        action_values: Iterable[int],
        action_labels: Optional[Iterable[str]] = None,
        capital: float = 1000.0,
        data=None,
        mode: str = "test",
        hedge_accounting_mode: str = HEDGE_ACCOUNTING_DEFAULT,
        action_decoder=None,
        algo: str = Q_ALGO_DQN,
        timing_width_mode: str = "heuristic",
        timing_fixed_width: int = 10,
        vec_env_factory=None,
    ):
        if algo == Q_ALGO_DQN:
            model = DQN.load(model_path)
        elif algo == Q_ALGO_QRDQN:
            model = QRDQN.load(model_path)
        elif algo == Q_ALGO_DUELING:
            model = DuelingDQN.load(model_path)
        elif algo == Q_ALGO_DDQN_DUELING:
            model = DoubleDuelingDQN.load(model_path)
        elif algo == Q_ALGO_THREE_HEAD_DUELING:
            model = ThreeHeadDuelingDQN.load(model_path)
        elif algo == Q_ALGO_THREE_HEAD_DDQN_DUELING:
            model = ThreeHeadDoubleDuelingDQN.load(model_path)
        else:
            raise ValueError(f"Unsupported q-policy algo: {algo}")
        obs_rms = None
        if vec_path:
            if data is None:
                raise ValueError("`data` is required when loading VecNormalize stats")
            if vec_env_factory is None:
                vec_env = DummyVecEnv(
                    [
                        lambda: UniswapV3HedgedFeeEnv(
                            data,
                            initial_capital_usd=capital,
                            mode=mode,
                            hedge_accounting_mode=hedge_accounting_mode,
                        )
                    ]
                )
            else:
                vec_env = DummyVecEnv([vec_env_factory])
            vec_env = VecNormalize.load(vec_path, vec_env)
            vec_env.training = False
            vec_env.norm_reward = False
            obs_rms = vec_env.obs_rms
        return cls(
            model=model,
            obs_rms=obs_rms,
            action_values=action_values,
            action_labels=action_labels,
            action_decoder=action_decoder,
            algo=algo,
            timing_width_mode=timing_width_mode,
            timing_fixed_width=timing_fixed_width,
        )

    def normalize_obs(self, obs: np.ndarray) -> np.ndarray:
        if self.obs_rms is None:
            return obs.astype(np.float32)
        return np.clip(
            (obs - self.obs_rms.mean) / np.sqrt(self.obs_rms.var + 1e-8),
            -10.0,
            10.0,
        ).astype(np.float32)

    def predict(self, obs: np.ndarray, return_q: bool = False) -> PolicyPrediction:
        obs_norm = self.normalize_obs(obs)
        obs_tensor = torch.as_tensor(obs_norm.reshape(1, -1), device=self.model.device)
        quantiles = None
        selected_quantile_iqr = None
        selected_quantile_std = None
        if self.algo in (
            Q_ALGO_DQN,
            Q_ALGO_DUELING,
            Q_ALGO_DDQN_DUELING,
            Q_ALGO_THREE_HEAD_DUELING,
            Q_ALGO_THREE_HEAD_DDQN_DUELING,
        ):
            q_values = self.model.q_net(obs_tensor).detach().cpu().numpy()[0]
        elif self.algo == Q_ALGO_QRDQN:
            quantiles = self.model.policy.quantile_net(obs_tensor).detach().cpu().numpy()[0]
            q_values = quantiles.mean(axis=0)
        else:
            raise ValueError(f"Unsupported q-policy algo: {self.algo}")
        action_idx = int(np.argmax(q_values))
        if quantiles is not None:
            selected_quantiles = quantiles[:, action_idx]
            selected_quantile_iqr = float(
                np.quantile(selected_quantiles, 0.75) - np.quantile(selected_quantiles, 0.25)
            )
            selected_quantile_std = float(np.std(selected_quantiles))
        q_copy = q_values.copy() if return_q else None
        raw_value = int(self.action_values[action_idx])
        value = (
            int(self.action_decoder(raw_value, obs))
            if self.action_decoder is not None
            else raw_value
        )
        return PolicyPrediction(
            value=value,
            q_values=q_copy,
            raw_value=raw_value,
            quantiles=quantiles.copy() if return_q and quantiles is not None else None,
            selected_quantile_iqr=selected_quantile_iqr,
            selected_quantile_std=selected_quantile_std,
        )


class TimingMLP(nn.Module):
    def __init__(self, input_dim: int, hidden_sizes: Iterable[int]):
        super().__init__()
        layers = []
        prev_dim = int(input_dim)
        for hidden_dim in hidden_sizes:
            layers.append(nn.Linear(prev_dim, int(hidden_dim)))
            layers.append(nn.ReLU())
            prev_dim = int(hidden_dim)
        layers.append(nn.Linear(prev_dim, 1))
        self.net = nn.Sequential(*layers)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x).squeeze(-1)


class SupervisedTimingPolicy:
    """Torch MLP timing policy trained on forward LP-vs-cash advantage labels."""

    def __init__(
        self,
        model: TimingMLP,
        feature_mean: np.ndarray,
        feature_std: np.ndarray,
        threshold: float = 0.5,
        timing_width_mode: str = "heuristic",
        timing_fixed_width: int = 10,
    ):
        self.model = model.eval()
        self.feature_mean = np.asarray(feature_mean, dtype=np.float32)
        self.feature_std = np.asarray(feature_std, dtype=np.float32)
        self.threshold = float(threshold)
        self.timing_width_mode = timing_width_mode
        self.timing_fixed_width = int(timing_fixed_width)

    @classmethod
    def load(cls, model_path: str):
        payload = torch.load(model_path, map_location="cpu", weights_only=False)
        model = TimingMLP(
            input_dim=int(payload["input_dim"]),
            hidden_sizes=payload["hidden_sizes"],
        )
        model.load_state_dict(payload["state_dict"])
        return cls(
            model=model,
            feature_mean=np.asarray(payload["feature_mean"], dtype=np.float32),
            feature_std=np.asarray(payload["feature_std"], dtype=np.float32),
            threshold=float(payload.get("threshold", 0.5)),
            timing_width_mode=str(payload.get("timing_width_mode", "heuristic")),
            timing_fixed_width=int(payload.get("timing_fixed_width", 10)),
        )

    def save(self, model_path: str) -> None:
        torch.save(
            {
                "state_dict": self.model.state_dict(),
                "input_dim": int(self.feature_mean.shape[0]),
                "hidden_sizes": [
                    int(layer.out_features)
                    for layer in self.model.net
                    if isinstance(layer, nn.Linear)
                ][:-1],
                "feature_mean": self.feature_mean,
                "feature_std": self.feature_std,
                "threshold": float(self.threshold),
                "timing_width_mode": self.timing_width_mode,
                "timing_fixed_width": int(self.timing_fixed_width),
            },
            model_path,
        )

    def normalize_obs(self, obs: np.ndarray) -> np.ndarray:
        return ((obs.astype(np.float32) - self.feature_mean) / self.feature_std).astype(np.float32)

    def predict_proba(self, obs: np.ndarray) -> float:
        obs_norm = self.normalize_obs(obs)
        with torch.no_grad():
            logits = self.model(torch.as_tensor(obs_norm.reshape(1, -1), dtype=torch.float32))
            return float(torch.sigmoid(logits).item())

    def predict(self, obs: np.ndarray, return_q: bool = False) -> PolicyPrediction:
        lp_prob = self.predict_proba(obs)
        cash_prob = 1.0 - lp_prob
        value = TIMING_TO_LP if lp_prob >= self.threshold else TIMING_TO_CASH
        q_values = np.array([cash_prob, lp_prob], dtype=np.float32) if return_q else None
        return PolicyPrediction(
            value=value,
            q_values=q_values,
            raw_value=value,
        )


class HeuristicWidthPolicy:
    """Width heuristic based on current NATR, optionally pinned to a fixed width."""

    width_action_mode = "heuristic"

    def __init__(
        self,
        fixed_width: Optional[int] = None,
        hedge_accounting_mode: str = HEDGE_ACCOUNTING_DEFAULT,
    ):
        self.fixed_width = None if fixed_width is None else int(fixed_width)
        self.hedge_accounting_mode = hedge_accounting_mode

    def predict(self, obs: np.ndarray, return_q: bool = False) -> PolicyPrediction:
        if self.fixed_width is not None:
            width = self.fixed_width
        elif self.hedge_accounting_mode == HEDGE_ACCOUNTING_CONTINUOUS:
            width = conservative_optimal_width_for_vol(float(obs[1]))
        else:
            width = optimal_width_for_vol(float(obs[1]))
        return PolicyPrediction(value=int(width), q_values=None, raw_value=int(width))


class MiddleVolTimingPolicy:
    """Stay in LP only when bb_width is inside a tuned middle-vol band."""

    def __init__(self, low_bb: float, high_bb: float):
        self.low_bb = float(low_bb)
        self.high_bb = float(high_bb)

    def predict(self, obs: np.ndarray, return_q: bool = False) -> PolicyPrediction:
        bb_width = float(obs[2])
        action = TIMING_TO_LP if self.low_bb <= bb_width <= self.high_bb else TIMING_TO_CASH
        return PolicyPrediction(value=int(action), q_values=None, raw_value=int(action))


class AlwaysCashTimingPolicy:
    def predict(self, obs: np.ndarray, return_q: bool = False) -> PolicyPrediction:
        return PolicyPrediction(value=TIMING_TO_CASH, q_values=None, raw_value=TIMING_TO_CASH)


class AlwaysLPTimingPolicy:
    def predict(self, obs: np.ndarray, return_q: bool = False) -> PolicyPrediction:
        return PolicyPrediction(value=TIMING_TO_LP, q_values=None, raw_value=TIMING_TO_LP)


class AlwaysHoldInRangePolicy:
    def predict(self, obs: np.ndarray, return_q: bool = False) -> PolicyPrediction:
        return PolicyPrediction(value=IN_RANGE_HOLD, q_values=None, raw_value=IN_RANGE_HOLD)


class BandBoundaryPolicy:
    """Boundary heuristic: cash outside a vol band, otherwise deploy/recenter heuristic width."""

    def __init__(
        self,
        low_bb: float,
        high_bb: float,
        hedge_accounting_mode: str = HEDGE_ACCOUNTING_DEFAULT,
        fixed_width: Optional[int] = None,
    ):
        self.low_bb = float(low_bb)
        self.high_bb = float(high_bb)
        self.hedge_accounting_mode = hedge_accounting_mode
        self.fixed_width = None if fixed_width is None else int(fixed_width)

    def predict(self, obs: np.ndarray, return_q: bool = False) -> PolicyPrediction:
        bb_width = float(obs[2])
        if not (self.low_bb <= bb_width <= self.high_bb):
            return PolicyPrediction(value=BOUNDARY_TO_CASH, q_values=None, raw_value=BOUNDARY_TO_CASH)
        if self.fixed_width is not None:
            width = self.fixed_width
        elif self.hedge_accounting_mode == HEDGE_ACCOUNTING_CONTINUOUS:
            width = conservative_optimal_width_for_vol(float(obs[1]))
        else:
            width = optimal_width_for_vol(float(obs[1]))
        action = BOUNDARY_ACTION_WIDTHS.index(int(width))
        return PolicyPrediction(value=int(action), q_values=None, raw_value=int(action))


def _three_head_state_from_obs(obs: np.ndarray) -> str:
    state_idx = int(np.argmax(np.asarray(obs[:3], dtype=np.float32)))
    return (THREE_HEAD_CASH, THREE_HEAD_IN_RANGE, THREE_HEAD_OOR)[state_idx]


class ConfidenceGatedWidthPolicy:
    """Fallback to a safe width policy when learned width confidence is too low."""

    def __init__(
        self,
        learned_policy,
        fallback_policy,
        min_q_gap: float = 0.0,
        min_confidence_score: Optional[float] = None,
        max_selected_quantile_iqr: Optional[float] = None,
    ):
        self.learned_policy = learned_policy
        self.fallback_policy = fallback_policy
        self.min_q_gap = float(min_q_gap)
        self.min_confidence_score = (
            None if min_confidence_score is None else float(min_confidence_score)
        )
        self.max_selected_quantile_iqr = (
            None
            if max_selected_quantile_iqr is None
            else float(max_selected_quantile_iqr)
        )
        self.width_action_mode = f"gated_{getattr(learned_policy, 'width_action_mode', 'width')}"

    def predict(self, obs: np.ndarray, return_q: bool = False) -> PolicyPrediction:
        pred = self.learned_policy.predict(obs, return_q=True)
        use_fallback = pred.q_gap < self.min_q_gap
        if (
            not use_fallback
            and self.min_confidence_score is not None
            and pred.confidence_score < self.min_confidence_score
        ):
            use_fallback = True
        if (
            not use_fallback
            and self.max_selected_quantile_iqr is not None
            and pred.selected_quantile_iqr is not None
            and pred.selected_quantile_iqr > self.max_selected_quantile_iqr
        ):
            use_fallback = True
        if not use_fallback:
            return pred
        fallback_pred = self.fallback_policy.predict(obs, return_q=False)
        return PolicyPrediction(
            value=int(fallback_pred.value),
            q_values=pred.q_values if return_q else None,
            raw_value=pred.raw_value,
            quantiles=pred.quantiles if return_q else None,
            selected_quantile_iqr=pred.selected_quantile_iqr,
            selected_quantile_std=pred.selected_quantile_std,
        )


def _policy_name(policy) -> str:
    return policy.__class__.__name__


def _width_from_policy(policy, obs: np.ndarray) -> PolicyPrediction:
    pred = policy.predict(obs, return_q=True)
    if pred.value not in ENTRY_WIDTHS:
        raise ValueError(f"Width policy must return one of {ENTRY_WIDTHS}, got {pred.value}")
    return pred


def load_width_policy(
    model_path: str,
    vec_path: Optional[str],
    capital: float,
    data,
    mode: str,
    hedge_accounting_mode: str,
    width_action_mode: str = WIDTH_ACTION_MODE_ABSOLUTE,
    algo: str = Q_ALGO_DQN,
):
    action_values = width_action_values(width_action_mode)
    action_labels = width_action_labels(width_action_mode)
    action_decoder = None
    if width_action_mode == WIDTH_ACTION_MODE_HEURISTIC_DELTA:
        action_decoder = lambda decision_value, obs: width_decision_to_width(  # noqa: E731
            decision_value,
            obs,
            width_action_mode,
        )
    policy = NormalizedDQNPolicy.load(
        model_path=model_path,
        vec_path=vec_path,
        action_values=action_values,
        action_labels=action_labels,
        data=data,
        capital=capital,
        mode=mode,
        hedge_accounting_mode=hedge_accounting_mode,
        action_decoder=action_decoder,
        algo=algo,
    )
    policy.width_action_mode = width_action_mode
    return policy


def _timing_action_label(value: int) -> str:
    return "lp_next_hour" if int(value) == TIMING_TO_LP else "cash_next_hour"


def _timing_obs_for_policy(policy, env, obs: np.ndarray) -> np.ndarray:
    return project_timing_observation(
        env=env,
        obs=obs,
        width_mode=getattr(policy, "timing_width_mode", "heuristic"),
        fixed_width=getattr(policy, "timing_fixed_width", 10),
    )


def run_hierarchical_policy_episode(
    data,
    timing_policy,
    width_policy,
    capital: float = 1000.0,
    mode: str = "test",
    seed: int = 42,
    hedge_accounting_mode: str = HEDGE_ACCOUNTING_DEFAULT,
) -> pd.DataFrame:
    env = UniswapV3HedgedFeeEnv(
        data,
        initial_capital_usd=capital,
        mode=mode,
        hedge_accounting_mode=hedge_accounting_mode,
    )
    obs, _ = env.reset(seed=seed)
    rows = []

    while True:
        t = env.timestamps[env.idx]
        feat = data.features.get(t, np.zeros(len(FEATURE_COLS), dtype=np.float32))
        price = env._get_price(t)
        position_state = env._position_state(price)
        timing_pred = timing_policy.predict(_timing_obs_for_policy(timing_policy, env, obs), return_q=True)

        width_pred = PolicyPrediction(value=0, q_values=None)
        env_action = HOLD_ACTION
        selected_width = 0

        if position_state == "cash":
            if timing_pred.value == TIMING_TO_LP:
                width_pred = _width_from_policy(width_policy, obs)
                selected_width = width_pred.value
                env_action = width_to_action(selected_width)
            else:
                env_action = HOLD_ACTION
        elif position_state == "lp_in_range":
            env_action = HOLD_ACTION if timing_pred.value == TIMING_TO_LP else GO_CASH_ACTION
        else:  # lp_oor
            if timing_pred.value == TIMING_TO_LP:
                width_pred = _width_from_policy(width_policy, obs)
                selected_width = width_pred.value
                env_action = width_to_action(selected_width)
            else:
                env_action = GO_CASH_ACTION

        next_obs, reward, done, _, info = env.step(env_action)
        rows.append(
            {
                "timestamp": str(t),
                "position_state": position_state,
                "timing_action": int(timing_pred.value),
                "timing_action_label": _timing_action_label(timing_pred.value),
                "timing_q_gap": timing_pred.q_gap,
                "width_selected": int(selected_width),
                "width_raw_decision": int(width_pred.raw_value or 0),
                "width_q_gap": width_pred.q_gap,
                "width_confidence_score": width_pred.confidence_score,
                "width_selected_quantile_iqr": float(width_pred.selected_quantile_iqr or 0.0),
                "width_selected_quantile_std": float(width_pred.selected_quantile_std or 0.0),
                "heuristic_width": int(heuristic_width_from_obs(obs)),
                "env_action": int(env_action),
                "effective_action": info["effective_action"],
                "reward": float(reward),
                "reward_usd": float(info["reward_usd"]),
                "fee_usd": float(info["fee_usd"]),
                "gross_fee_carry_usd": float(info["gross_fee_carry_usd"]),
                "lp_value_change_usd": float(info["lp_value_change_usd"]),
                "hedge_pnl_usd": float(info["hedge_pnl_usd"]),
                "swing_pnl_usd": float(info["swing_pnl_usd"]),
                "raw_lp_value_change_usd": float(info["raw_lp_value_change_usd"]),
                "raw_hedge_pnl_usd": float(info["raw_hedge_pnl_usd"]),
                "raw_swing_pnl_usd": float(info["raw_swing_pnl_usd"]),
                "raw_boundary_il_usd": float(info["raw_boundary_il_usd"]),
                "realized_boundary_pnl_usd": float(info["realized_boundary_pnl_usd"]),
                "pending_boundary_pnl_usd": float(info["pending_boundary_pnl_usd"]),
                "funding_cost_usd": float(info["funding_cost_usd"]),
                "hedged_core_pnl_usd": float(info["hedged_core_pnl_usd"]),
                "net_before_tx_usd": float(info["net_before_tx_usd"]),
                "net_after_tx_usd": float(info["net_after_tx_usd"]),
                "tx_cost_usd": float(info["tx_cost_usd"]),
                "portfolio_value": float(info["portfolio_value"]),
                "close_now_portfolio_value": float(info["close_now_portfolio_value"]),
                "is_cash_after": int(info["is_cash"]),
                "next_position_state": info["next_position_state"],
                "natr_14": float(feat[FEATURE_COLS.index("natr_14")]),
                "bb_width": float(feat[FEATURE_COLS.index("bb_width")]),
                "volume_sma_ratio": float(feat[FEATURE_COLS.index("volume_sma_ratio")]),
                "vol_regime": float(feat[FEATURE_COLS.index("vol_regime")]),
                "timing_policy": _policy_name(timing_policy),
                "width_policy": _policy_name(width_policy),
                "width_action_mode": getattr(width_policy, "width_action_mode", "policy_width"),
                "hedge_accounting_mode": info["hedge_accounting_mode"],
            }
        )
        obs = next_obs
        if done:
            break

    trace_df = pd.DataFrame(rows)
    trace_df.attrs["initial_capital"] = float(capital)
    trace_df.attrs["mode"] = mode
    trace_df.attrs["hedge_accounting_mode"] = hedge_accounting_mode
    return trace_df


def run_state_split_policy_episode(
    data,
    boundary_policy,
    in_range_policy,
    capital: float = 1000.0,
    mode: str = "test",
    seed: int = 42,
    hedge_accounting_mode: str = HEDGE_ACCOUNTING_DEFAULT,
) -> pd.DataFrame:
    env = UniswapV3HedgedFeeEnv(
        data,
        initial_capital_usd=capital,
        mode=mode,
        hedge_accounting_mode=hedge_accounting_mode,
    )
    obs, _ = env.reset(seed=seed)
    rows = []

    while True:
        t = env.timestamps[env.idx]
        feat = data.features.get(t, np.zeros(len(FEATURE_COLS), dtype=np.float32))
        price = env._get_price(t)
        state = env._position_state(price)
        boundary_pred = PolicyPrediction(value=BOUNDARY_TO_CASH, q_values=None, raw_value=BOUNDARY_TO_CASH)
        in_range_pred = PolicyPrediction(value=IN_RANGE_HOLD, q_values=None, raw_value=IN_RANGE_HOLD)
        selected_width = 0

        if state == "lp_in_range":
            in_range_pred = in_range_policy.predict(obs, return_q=True)
            env_action = HOLD_ACTION if int(in_range_pred.value) == IN_RANGE_HOLD else GO_CASH_ACTION
            effective_decision = "hold" if env_action == HOLD_ACTION else "exit_to_cash"
        else:
            boundary_pred = boundary_policy.predict(obs, return_q=True)
            selected_width = boundary_action_to_width(int(boundary_pred.value))
            if state == "cash":
                env_action = HOLD_ACTION if selected_width == 0 else width_to_action(selected_width)
            else:
                env_action = GO_CASH_ACTION if selected_width == 0 else width_to_action(selected_width)
            effective_decision = boundary_action_label(int(boundary_pred.value), state)

        next_obs, reward, done, _, info = env.step(env_action)
        rows.append(
            {
                "timestamp": str(t),
                "position_state": state,
                "boundary_action": int(boundary_pred.value),
                "boundary_q_gap": boundary_pred.q_gap,
                "in_range_action": int(in_range_pred.value),
                "in_range_q_gap": in_range_pred.q_gap,
                "selected_width": int(selected_width),
                "decision_label": effective_decision,
                "env_action": int(env_action),
                "effective_action": info["effective_action"],
                "reward": float(reward),
                "reward_usd": float(info["reward_usd"]),
                "fee_usd": float(info["fee_usd"]),
                "gross_fee_carry_usd": float(info["gross_fee_carry_usd"]),
                "raw_swing_pnl_usd": float(info["raw_swing_pnl_usd"]),
                "raw_boundary_il_usd": float(info["raw_boundary_il_usd"]),
                "funding_cost_usd": float(info["funding_cost_usd"]),
                "tx_cost_usd": float(info["tx_cost_usd"]),
                "portfolio_value": float(info["portfolio_value"]),
                "close_now_portfolio_value": float(
                    info.get("close_now_portfolio_value", env._capital_if_closed_now())
                ),
                "is_cash_after": int(info.get("is_cash", env.is_cash)),
                "next_position_state": info["next_position_state"],
                "natr_14": float(feat[FEATURE_COLS.index("natr_14")]),
                "bb_width": float(feat[FEATURE_COLS.index("bb_width")]),
                "volume_sma_ratio": float(feat[FEATURE_COLS.index("volume_sma_ratio")]),
                "hedge_accounting_mode": info["hedge_accounting_mode"],
            }
        )
        obs = next_obs
        if done:
            break

    trace_df = pd.DataFrame(rows)
    trace_df.attrs["initial_capital"] = float(capital)
    trace_df.attrs["mode"] = mode
    trace_df.attrs["hedge_accounting_mode"] = hedge_accounting_mode
    return trace_df


def run_cash_oor_policy_episode(
    data,
    cash_oor_policy,
    capital: float = 1000.0,
    mode: str = "test",
    seed: int = 42,
    hedge_accounting_mode: str = HEDGE_ACCOUNTING_DEFAULT,
    action_widths=ENTRY_WIDTHS,
    oor_recenter_mode: str = OOR_RECENTER_REQUESTED,
    start_idx=None,
    end_idx=None,
) -> pd.DataFrame:
    env = UniswapV3HedgedCashOOREnv(
        data,
        initial_capital_usd=capital,
        mode=mode,
        start_idx=start_idx,
        end_idx=end_idx,
        hedge_accounting_mode=hedge_accounting_mode,
        training_objective=TRAINING_OBJECTIVE_REALISTIC,
        action_widths=action_widths,
        oor_recenter_mode=oor_recenter_mode,
    )
    obs, _ = env.reset(seed=seed)
    rows = []

    while True:
        t = env.timestamps[env.idx]
        feat = data.features.get(t, np.zeros(len(FEATURE_COLS), dtype=np.float32))
        state = env._position_state(env._get_price(t))
        prediction = PolicyPrediction(value=CASH_OOR_HOLD_OR_STAY, q_values=None, raw_value=0)
        selected_width = 0
        requested_width = 0

        if state in {"cash", "lp_oor"}:
            prediction = cash_oor_policy.predict(obs, return_q=True)
            action_value = int(prediction.value)
            requested_width = cash_oor_action_to_width(action_value, action_widths)
            selected_width = requested_width
            env_action = action_value
            decision_label = cash_oor_action_label(action_value, state, action_widths)
        else:
            env_action = CASH_OOR_HOLD_OR_STAY
            decision_label = "hold"
            action_value = CASH_OOR_HOLD_OR_STAY

        next_obs, reward, done, _, info = env.step(env_action)
        selected_width = int(info.get("selected_width", selected_width))
        rows.append(
            {
                "timestamp": str(t),
                "position_state": state,
                "cash_oor_action": int(action_value),
                "cash_oor_action_label": decision_label,
                "cash_oor_effective_action_label": (
                    "recenter_same_width"
                    if (
                        state == "lp_oor"
                        and action_value >= 2
                        and oor_recenter_mode == OOR_RECENTER_SAME
                    )
                    else decision_label
                ),
                "cash_oor_q_gap": prediction.q_gap,
                "requested_width": int(requested_width),
                "selected_width": int(selected_width),
                "env_action": int(env_action),
                "effective_action": info["effective_action"],
                "reward": float(reward),
                "reward_usd": float(info["reward_usd"]),
                "fee_usd": float(info["fee_usd"]),
                "gross_fee_carry_usd": float(info["gross_fee_carry_usd"]),
                "raw_swing_pnl_usd": float(info["raw_swing_pnl_usd"]),
                "raw_boundary_il_usd": float(info["raw_boundary_il_usd"]),
                "funding_cost_usd": float(info["funding_cost_usd"]),
                "tx_cost_usd": float(info["tx_cost_usd"]),
                "portfolio_value": float(info["portfolio_value"]),
                "close_now_portfolio_value": float(
                    info.get("close_now_portfolio_value", env._capital_if_closed_now())
                ),
                "is_cash_after": int(info.get("is_cash", env.is_cash)),
                "next_position_state": info["next_position_state"],
                "natr_14": float(feat[FEATURE_COLS.index("natr_14")]),
                "bb_width": float(feat[FEATURE_COLS.index("bb_width")]),
                "volume_sma_ratio": float(feat[FEATURE_COLS.index("volume_sma_ratio")]),
                "hedge_accounting_mode": info["hedge_accounting_mode"],
                "oor_recenter_mode": oor_recenter_mode,
            }
        )
        obs = next_obs
        if done:
            break

    trace_df = pd.DataFrame(rows)
    trace_df.attrs["initial_capital"] = float(capital)
    trace_df.attrs["mode"] = mode
    trace_df.attrs["hedge_accounting_mode"] = hedge_accounting_mode
    return trace_df


def run_three_head_policy_episode(
    data,
    three_head_policy,
    capital: float = 1000.0,
    mode: str = "test",
    seed: int = 42,
    hedge_accounting_mode: str = HEDGE_ACCOUNTING_DEFAULT,
    action_widths=THREE_HEAD_ACTION_WIDTHS,
    start_idx=None,
    end_idx=None,
    env_kwargs: Optional[dict] = None,
) -> pd.DataFrame:
    env_kwargs = {} if env_kwargs is None else dict(env_kwargs)
    env_action_widths = env_kwargs.pop("action_widths", action_widths)
    env = UniswapV3HedgedThreeHeadEnv(
        data,
        initial_capital_usd=capital,
        mode=mode,
        start_idx=start_idx,
        end_idx=end_idx,
        hedge_accounting_mode=hedge_accounting_mode,
        action_widths=env_action_widths,
        **env_kwargs,
    )
    obs, _ = env.reset(seed=seed)
    rows = []

    while True:
        t = env.timestamps[env.idx]
        feat = data.features.get(t, np.zeros(len(FEATURE_COLS), dtype=np.float32))
        state = env._position_state(env._get_price(t))
        prediction = three_head_policy.predict(obs, return_q=True)
        action_value = int(prediction.value)
        requested_width = env.requested_three_head_width(action_value, state)

        next_obs, reward, done, _, info = env.step(action_value)
        rows.append(
            {
                "timestamp": str(t),
                "position_state": state,
                "three_head_action": int(action_value),
                "three_head_action_label": env.requested_three_head_action_label(
                    action_value, state
                ),
                "three_head_q_gap": prediction.q_gap,
                "requested_width": int(requested_width),
                "selected_width": int(info.get("selected_width", requested_width)),
                "env_action": int(action_value),
                "applied_action": int(info.get("applied_action", action_value)),
                "applied_action_label": str(
                    info.get(
                        "applied_action_label",
                        env.requested_three_head_action_label(action_value, state),
                    )
                ),
                "effective_action": info["effective_action"],
                "reward": float(reward),
                "reward_usd": float(info["reward_usd"]),
                "fee_usd": float(info["fee_usd"]),
                "gross_fee_carry_usd": float(info["gross_fee_carry_usd"]),
                "lp_value_change_usd": float(info["lp_value_change_usd"]),
                "hedge_pnl_usd": float(info["hedge_pnl_usd"]),
                "swing_pnl_usd": float(info["swing_pnl_usd"]),
                "raw_lp_value_change_usd": float(info["raw_lp_value_change_usd"]),
                "raw_hedge_pnl_usd": float(info["raw_hedge_pnl_usd"]),
                "raw_swing_pnl_usd": float(info["raw_swing_pnl_usd"]),
                "raw_boundary_il_usd": float(info["raw_boundary_il_usd"]),
                "realized_boundary_pnl_usd": float(info["realized_boundary_pnl_usd"]),
                "pending_boundary_pnl_usd": float(info["pending_boundary_pnl_usd"]),
                "funding_cost_usd": float(info["funding_cost_usd"]),
                "hedged_core_pnl_usd": float(info["hedged_core_pnl_usd"]),
                "net_before_tx_usd": float(info["net_before_tx_usd"]),
                "net_after_tx_usd": float(info["net_after_tx_usd"]),
                "tx_cost_usd": float(info["tx_cost_usd"]),
                "portfolio_value": float(info["portfolio_value"]),
                "close_now_portfolio_value": float(info["close_now_portfolio_value"]),
                "is_cash_after": int(info["is_cash"]),
                "next_position_state": info["next_position_state"],
                "natr_14": float(feat[FEATURE_COLS.index("natr_14")]),
                "bb_width": float(feat[FEATURE_COLS.index("bb_width")]),
                "volume_sma_ratio": float(feat[FEATURE_COLS.index("volume_sma_ratio")]),
                "vol_regime": float(feat[FEATURE_COLS.index("vol_regime")]),
                "paper_signal_ratio": (
                    float(obs[3]) if getattr(env, "include_paper_signal_features", False) else 0.0
                ),
                "paper_signal_flag": (
                    float(obs[4]) if getattr(env, "include_paper_signal_features", False) else 0.0
                ),
                "hedge_accounting_mode": info["hedge_accounting_mode"],
            }
        )
        obs = next_obs
        if done:
            break

    trace_df = pd.DataFrame(rows)
    trace_df.attrs["initial_capital"] = float(capital)
    trace_df.attrs["mode"] = mode
    trace_df.attrs["hedge_accounting_mode"] = hedge_accounting_mode
    return trace_df


def run_always_cash_episode(
    data,
    capital: float = 1000.0,
    mode: str = "test",
    seed: int = 42,
    hedge_accounting_mode: str = HEDGE_ACCOUNTING_DEFAULT,
    start_idx=None,
    end_idx=None,
) -> pd.DataFrame:
    env = UniswapV3HedgedFeeEnv(
        data,
        initial_capital_usd=capital,
        mode=mode,
        start_idx=start_idx,
        end_idx=end_idx,
        hedge_accounting_mode=hedge_accounting_mode,
    )
    obs, _ = env.reset(seed=seed)
    rows = []

    while True:
        t = env.timestamps[env.idx]
        feat = data.features.get(t, np.zeros(len(FEATURE_COLS), dtype=np.float32))
        state = env._position_state(env._get_price(t))
        env_action = HOLD_ACTION if state == "cash" else GO_CASH_ACTION
        decision_label = "stay_cash" if state == "cash" else "exit_to_cash"
        next_obs, reward, done, _, info = env.step(env_action)
        rows.append(
            {
                "timestamp": str(t),
                "position_state": state,
                "decision_label": decision_label,
                "env_action": int(env_action),
                "effective_action": info["effective_action"],
                "reward": float(reward),
                "reward_usd": float(info["reward_usd"]),
                "fee_usd": float(info["fee_usd"]),
                "gross_fee_carry_usd": float(info["gross_fee_carry_usd"]),
                "raw_swing_pnl_usd": float(info["raw_swing_pnl_usd"]),
                "raw_boundary_il_usd": float(info["raw_boundary_il_usd"]),
                "funding_cost_usd": float(info["funding_cost_usd"]),
                "tx_cost_usd": float(info["tx_cost_usd"]),
                "portfolio_value": float(info["portfolio_value"]),
                "close_now_portfolio_value": float(info["close_now_portfolio_value"]),
                "is_cash_after": int(info["is_cash"]),
                "next_position_state": info["next_position_state"],
                "natr_14": float(feat[FEATURE_COLS.index("natr_14")]),
                "bb_width": float(feat[FEATURE_COLS.index("bb_width")]),
                "volume_sma_ratio": float(feat[FEATURE_COLS.index("volume_sma_ratio")]),
                "hedge_accounting_mode": info["hedge_accounting_mode"],
            }
        )
        obs = next_obs
        if done:
            break

    trace_df = pd.DataFrame(rows)
    trace_df.attrs["initial_capital"] = float(capital)
    trace_df.attrs["mode"] = mode
    trace_df.attrs["hedge_accounting_mode"] = hedge_accounting_mode
    return trace_df


def run_paper_threshold_policy_episode(
    data,
    train_start_idx: int,
    train_end_idx: int,
    capital: float = 1000.0,
    mode: str = "test",
    seed: int = 42,
    hedge_accounting_mode: str = HEDGE_ACCOUNTING_DEFAULT,
    start_idx=None,
    end_idx=None,
    fixed_width: int = 4,
) -> pd.DataFrame:
    env = UniswapV3HedgedFeeEnv(
        data,
        initial_capital_usd=capital,
        mode=mode,
        start_idx=start_idx,
        end_idx=end_idx,
        hedge_accounting_mode=hedge_accounting_mode,
    )
    obs, _ = env.reset(seed=seed)
    bb_history = [
        float(
            data.features.get(
                data.timestamps[idx], np.zeros(len(FEATURE_COLS), dtype=np.float32)
            )[FEATURE_COLS.index("bb_width")]
        )
        for idx in range(int(train_start_idx), int(train_end_idx))
    ]
    rows = []

    while True:
        t = env.timestamps[env.idx]
        feat = data.features.get(t, np.zeros(len(FEATURE_COLS), dtype=np.float32))
        state = env._position_state(env._get_price(t))
        bb_width = float(feat[FEATURE_COLS.index("bb_width")])
        threshold = float(np.median(bb_history)) if bb_history else bb_width
        deploy_signal = bb_width > threshold

        if deploy_signal:
            if state == "cash":
                env_action = width_to_action(fixed_width)
                decision_label = f"enter_w{fixed_width}"
            elif state == "lp_in_range":
                env_action = HOLD_ACTION
                decision_label = "hold"
            else:
                env_action = width_to_action(fixed_width)
                decision_label = f"recenter_w{fixed_width}"
        else:
            env_action = HOLD_ACTION if state == "cash" else GO_CASH_ACTION
            decision_label = "stay_cash" if state == "cash" else "exit_to_cash"

        next_obs, reward, done, _, info = env.step(env_action)
        rows.append(
            {
                "timestamp": str(t),
                "position_state": state,
                "decision_label": decision_label,
                "deploy_signal": int(deploy_signal),
                "bb_width_threshold": threshold,
                "env_action": int(env_action),
                "effective_action": info["effective_action"],
                "reward": float(reward),
                "reward_usd": float(info["reward_usd"]),
                "fee_usd": float(info["fee_usd"]),
                "gross_fee_carry_usd": float(info["gross_fee_carry_usd"]),
                "raw_swing_pnl_usd": float(info["raw_swing_pnl_usd"]),
                "raw_boundary_il_usd": float(info["raw_boundary_il_usd"]),
                "funding_cost_usd": float(info["funding_cost_usd"]),
                "tx_cost_usd": float(info["tx_cost_usd"]),
                "portfolio_value": float(info["portfolio_value"]),
                "close_now_portfolio_value": float(info["close_now_portfolio_value"]),
                "is_cash_after": int(info["is_cash"]),
                "next_position_state": info["next_position_state"],
                "natr_14": float(feat[FEATURE_COLS.index("natr_14")]),
                "bb_width": bb_width,
                "volume_sma_ratio": float(feat[FEATURE_COLS.index("volume_sma_ratio")]),
                "hedge_accounting_mode": info["hedge_accounting_mode"],
            }
        )
        bb_history.append(bb_width)
        obs = next_obs
        if done:
            break

    trace_df = pd.DataFrame(rows)
    trace_df.attrs["initial_capital"] = float(capital)
    trace_df.attrs["mode"] = mode
    trace_df.attrs["hedge_accounting_mode"] = hedge_accounting_mode
    return trace_df


def tune_middle_vol_timing_policy(
    data,
    capital: float = 1000.0,
    seed: int = 42,
    low_grid: Optional[Iterable[float]] = None,
    high_grid: Optional[Iterable[float]] = None,
    hedge_accounting_mode: str = HEDGE_ACCOUNTING_DEFAULT,
    width_policy=None,
):
    train_env = UniswapV3HedgedFeeEnv(
        data,
        initial_capital_usd=capital,
        mode="train",
        hedge_accounting_mode=hedge_accounting_mode,
    )
    train_timestamps = train_env.timestamps
    bb_series = np.array(
        [
            float(data.features.get(t, np.zeros(len(FEATURE_COLS), dtype=np.float32))[FEATURE_COLS.index("bb_width")])
            for t in train_timestamps
        ],
        dtype=np.float64,
    )

    if low_grid is None:
        low_grid = np.quantile(bb_series, [0.0, 0.1, 0.2, 0.3, 0.4])
    if high_grid is None:
        high_grid = np.quantile(bb_series, [0.6, 0.7, 0.8, 0.9, 1.0])

    if width_policy is None:
        width_policy = HeuristicWidthPolicy()
    best = None
    for low_bb in low_grid:
        for high_bb in high_grid:
            if float(low_bb) >= float(high_bb):
                continue
            timing_policy = MiddleVolTimingPolicy(low_bb=low_bb, high_bb=high_bb)
            trace = run_hierarchical_policy_episode(
                data=data,
                timing_policy=timing_policy,
                width_policy=width_policy,
                capital=capital,
                mode="train",
                seed=seed,
                hedge_accounting_mode=hedge_accounting_mode,
            )
            final_pv = float(trace["portfolio_value"].iloc[-1])
            candidate = {
                "low_bb": float(low_bb),
                "high_bb": float(high_bb),
                "final_pv": final_pv,
                "cash_pct": float(trace["is_cash_after"].mean()),
            }
            if best is None or candidate["final_pv"] > best["final_pv"]:
                best = candidate

    if best is None:
        raise RuntimeError("Failed to tune middle-vol timing baseline")
    return best


def _infer_initial_capital(trace_df: pd.DataFrame) -> float:
    attr_capital = trace_df.attrs.get("initial_capital")
    if attr_capital is not None:
        return float(attr_capital)
    if len(trace_df) == 0:
        return 0.0
    if {"portfolio_value", "reward_usd"}.issubset(trace_df.columns):
        return float(trace_df["portfolio_value"].iloc[0] - trace_df["reward_usd"].iloc[0])
    if "portfolio_value" in trace_df.columns:
        return float(trace_df["portfolio_value"].iloc[0])
    return 0.0


def trace_metrics(trace_df: pd.DataFrame) -> dict:
    initial_capital = _infer_initial_capital(trace_df)
    trade_mask = trace_df["effective_action"].str.startswith(("enter_w", "recenter_w", "exit_to_cash"))
    gross_fee_carry = (
        float(trace_df["gross_fee_carry_usd"].sum())
        if "gross_fee_carry_usd" in trace_df.columns
        else float(
            trace_df.get("fee_usd", pd.Series(dtype=float)).sum()
            - trace_df.get("funding_cost_usd", pd.Series(dtype=float)).sum()
            - trace_df.get("tx_cost_usd", pd.Series(dtype=float)).sum()
        )
    )
    raw_boundary_last = (
        float(trace_df["raw_boundary_il_usd"].iloc[-1])
        if "raw_boundary_il_usd" in trace_df.columns and len(trace_df) > 0
        else 0.0
    )
    raw_boundary_max_abs = (
        float(trace_df["raw_boundary_il_usd"].abs().max())
        if "raw_boundary_il_usd" in trace_df.columns and len(trace_df) > 0
        else 0.0
    )
    raw_swing_total = (
        float(trace_df["raw_swing_pnl_usd"].sum())
        if "raw_swing_pnl_usd" in trace_df.columns and len(trace_df) > 0
        else 0.0
    )
    hedge_accounting_mode = (
        trace_df.attrs.get("hedge_accounting_mode")
        or (
            str(trace_df["hedge_accounting_mode"].iloc[0])
            if "hedge_accounting_mode" in trace_df.columns and len(trace_df) > 0
            else ""
        )
    )
    return {
        "final_pv": float(trace_df["portfolio_value"].iloc[-1]),
        "pnl": float(trace_df["portfolio_value"].iloc[-1] - initial_capital),
        "initial_capital": initial_capital,
        "cash_pct": float(trace_df["is_cash_after"].mean() * 100.0),
        "oor_pct": float((trace_df["position_state"] == "lp_oor").mean() * 100.0),
        "trade_count": int(trade_mask.sum()),
        "enter_count": int(trace_df["effective_action"].str.startswith("enter_w").sum()),
        "recenter_count": int(trace_df["effective_action"].str.startswith("recenter_w").sum()),
        "exit_count": int(trace_df["effective_action"].eq("exit_to_cash").sum()),
        "gross_fee_carry_usd": gross_fee_carry,
        "raw_swing_pnl_usd": raw_swing_total,
        "raw_boundary_il_last_usd": raw_boundary_last,
        "raw_boundary_il_abs_max_usd": raw_boundary_max_abs,
        "hedge_accounting_mode": hedge_accounting_mode,
    }
