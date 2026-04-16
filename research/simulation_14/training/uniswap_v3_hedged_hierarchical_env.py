"""
Hierarchical hedged environments built on top of the hourly hedged fee env.

Stage 1: binary hourly timing
  - action 0 = cash_next_hour
  - action 1 = lp_next_hour

Stage 2: event-driven width selection
  - action space chooses one of the supported entry widths
  - a frozen timing policy controls hold/exit decisions between width boundaries
"""

import bisect
import math
from typing import Optional, Sequence

import numpy as np
from gymnasium import spaces

from kongtrae.training.uniswap_v3_hedged_fee_env import (
    ENTRY_WIDTHS,
    GO_CASH_ACTION,
    HEDGE_ACCOUNTING_CONTINUOUS,
    HOLD_ACTION,
    TRAINING_REWARD_FEE_TX_PATIENCE,
    TRAINING_REWARD_REALISTIC,
    UniswapV3HedgedFeeEnv,
    conservative_optimal_width_for_vol,
    optimal_width_for_vol,
    width_to_action,
)
from kongtrae.training.uniswap_v3_ppo_paper import FEATURE_COLS, tick_to_price
from kongtrae.training.hedged_width_action_utils import (
    WIDTH_ACTION_MODE_ABSOLUTE,
    WIDTH_ACTION_MODES,
    heuristic_width_from_obs,
    width_action_index_to_value,
    width_action_values,
    width_decision_to_width,
)


TIMING_TO_CASH = 0
TIMING_TO_LP = 1
IN_RANGE_HOLD = 0
IN_RANGE_EXIT = 1
BOUNDARY_TO_CASH = 0
BOUNDARY_ACTION_WIDTHS = (0,) + tuple(ENTRY_WIDTHS)
CASH_OOR_HOLD_OR_STAY = 0
CASH_OOR_EXIT = 1
N_CASH_OOR_ACTIONS = 2 + len(ENTRY_WIDTHS)
TRAINING_OBJECTIVE_REALISTIC = "realistic"
TRAINING_OBJECTIVE_FEE_TX_SHAPED = "fee_tx_shaped"
OOR_RECENTER_REQUESTED = "requested_width"
OOR_RECENTER_SAME = "same_width"
THREE_HEAD_CASH = "cash"
THREE_HEAD_IN_RANGE = "lp_in_range"
THREE_HEAD_OOR = "lp_oor"
THREE_HEAD_STATES = (THREE_HEAD_CASH, THREE_HEAD_IN_RANGE, THREE_HEAD_OOR)
THREE_HEAD_CASH_STAY = 0
THREE_HEAD_HOLD = 0
THREE_HEAD_GO_CASH = 1
# Legacy constants kept for backward compat — prefer the generic helpers below.
THREE_HEAD_CASH_ENTER_W10 = 1
THREE_HEAD_CASH_ENTER_W20 = 2
THREE_HEAD_CASH_ENTER_W40 = 3
THREE_HEAD_CASH_MASKED = 4
THREE_HEAD_RECENTER_W10 = 2
THREE_HEAD_RECENTER_W20 = 3
THREE_HEAD_RECENTER_W40 = 4
THREE_HEAD_NUM_ACTIONS = 5  # legacy default; env computes dynamically
THREE_HEAD_ACTION_WIDTHS = (10, 20, 40)
THREE_HEAD_V2_ACTION_WIDTHS = (10, 20)


def three_head_num_actions_for_widths(action_widths: Sequence[int]) -> int:
    """Compute action space size: hold/stay + go_cash/enter[0] + ... + enter/recenter[N-1]."""
    return 2 + len(action_widths)


def build_three_head_masks(action_widths: Sequence[int]) -> np.ndarray:
    """Build (3, num_actions) state-action masks for N widths."""
    n = three_head_num_actions_for_widths(action_widths)
    # Cash: stay(0) + enter_w[0..N-1](1..N) valid; last slot masked
    cash_mask = np.zeros(n, dtype=np.bool_)
    cash_mask[: 1 + len(action_widths)] = True
    # LP in-range / OOR: hold(0) + exit(1) + recenter_w[0..N-1](2..N+1) all valid
    lp_mask = np.ones(n, dtype=np.bool_)
    return np.array([cash_mask, lp_mask, lp_mask])

ADDITIVE_COMPONENT_KEYS = (
    "lp_value_change_usd",
    "hedge_pnl_usd",
    "swing_pnl_usd",
    "raw_lp_value_change_usd",
    "raw_hedge_pnl_usd",
    "raw_swing_pnl_usd",
    "realized_boundary_pnl_usd",
    "fee_usd",
    "funding_cost_usd",
    "hedged_core_pnl_usd",
    "gross_fee_carry_usd",
    "net_before_tx_usd",
    "net_after_tx_usd",
    "tx_cost_usd",
    "swap_fee_cost_usd",
    "mev_cost_usd",
    "reward_usd",
)


def boundary_action_to_width(action: int) -> int:
    action_int = int(action)
    if action_int < 0 or action_int >= len(BOUNDARY_ACTION_WIDTHS):
        raise ValueError(f"Boundary action out of range: {action_int}")
    return int(BOUNDARY_ACTION_WIDTHS[action_int])


def width_to_boundary_action(width: int) -> int:
    width_int = int(width)
    if width_int not in BOUNDARY_ACTION_WIDTHS:
        raise ValueError(f"Unsupported boundary width: {width_int}")
    return int(BOUNDARY_ACTION_WIDTHS.index(width_int))


def boundary_action_label(action: int, state: str) -> str:
    width = boundary_action_to_width(action)
    if width == 0:
        return "stay_cash" if state == "cash" else "exit_to_cash"
    return f"enter_w{width}" if state == "cash" else f"recenter_w{width}"


def cash_oor_num_actions(action_widths=ENTRY_WIDTHS) -> int:
    return 2 + len(tuple(action_widths))


def cash_oor_action_to_width(action: int, action_widths=ENTRY_WIDTHS) -> int:
    widths = tuple(int(w) for w in action_widths)
    action_int = int(action)
    if action_int < 0 or action_int >= cash_oor_num_actions(widths):
        raise ValueError(f"Cash/OOR action out of range: {action_int}")
    if action_int < 2:
        return 0
    return int(widths[action_int - 2])


def width_to_cash_oor_action(width: int, action_widths=ENTRY_WIDTHS) -> int:
    widths = tuple(int(w) for w in action_widths)
    width_int = int(width)
    if width_int not in widths:
        raise ValueError(f"Unsupported cash/OOR width: {width_int}")
    return 2 + widths.index(width_int)


def cash_oor_action_label(action: int, state: str, action_widths=ENTRY_WIDTHS) -> str:
    action_int = int(action)
    if state == "cash":
        if action_int in {CASH_OOR_HOLD_OR_STAY, CASH_OOR_EXIT}:
            return "stay_cash"
        return f"enter_w{cash_oor_action_to_width(action_int, action_widths)}"
    if state == "lp_oor":
        if action_int == CASH_OOR_HOLD_OR_STAY:
            return "hold_oor"
        if action_int == CASH_OOR_EXIT:
            return "exit_to_cash"
        return f"recenter_w{cash_oor_action_to_width(action_int, action_widths)}"
    raise ValueError(f"Unsupported state for cash/OOR action label: {state}")


def three_head_state_one_hot(state: str) -> np.ndarray:
    if state not in THREE_HEAD_STATES:
        raise ValueError(f"Unsupported three-head state: {state}")
    one_hot = np.zeros(len(THREE_HEAD_STATES), dtype=np.float32)
    one_hot[THREE_HEAD_STATES.index(state)] = 1.0
    return one_hot


def three_head_action_to_width(
    action: int,
    state: str,
    action_widths: Sequence[int] = THREE_HEAD_ACTION_WIDTHS,
) -> int:
    widths = tuple(int(w) for w in action_widths)
    action_int = int(action)
    num_actions = three_head_num_actions_for_widths(widths)
    if action_int < 0 or action_int >= num_actions:
        raise ValueError(f"Three-head action out of range: {action_int}")
    if state == THREE_HEAD_CASH:
        # Actions 1..len(widths) map to widths[0..N-1]
        idx = action_int - 1
        if 0 <= idx < len(widths):
            return int(widths[idx])
        return 0
    if state in {THREE_HEAD_IN_RANGE, THREE_HEAD_OOR}:
        # Actions 2..1+len(widths) map to widths[0..N-1]
        idx = action_int - 2
        if 0 <= idx < len(widths):
            return int(widths[idx])
        return 0
    raise ValueError(f"Unsupported state for three-head action mapping: {state}")


def width_to_three_head_cash_action(
    width: int,
    action_widths: Sequence[int] = THREE_HEAD_ACTION_WIDTHS,
) -> int:
    widths = tuple(int(w) for w in action_widths)
    w = int(width)
    if w not in widths:
        raise ValueError(f"Unsupported cash-entry width: {width}")
    return 1 + widths.index(w)


def width_to_three_head_recenter_action(
    width: int,
    action_widths: Sequence[int] = THREE_HEAD_ACTION_WIDTHS,
) -> int:
    widths = tuple(int(w) for w in action_widths)
    w = int(width)
    if w not in widths:
        raise ValueError(f"Unsupported recenter width: {width}")
    return 2 + widths.index(w)


def compute_expanding_median(values: np.ndarray) -> np.ndarray:
    sorted_vals: list[float] = []
    medians = np.zeros_like(values, dtype=np.float32)
    for idx, value in enumerate(np.asarray(values, dtype=np.float32)):
        bisect.insort(sorted_vals, float(value))
        n = idx + 1
        mid = n // 2
        if n % 2 == 1:
            medians[idx] = float(sorted_vals[mid])
        else:
            medians[idx] = float(0.5 * (sorted_vals[mid - 1] + sorted_vals[mid]))
    return medians


def three_head_action_label(
    action: int,
    state: str,
    action_widths: Sequence[int] = THREE_HEAD_ACTION_WIDTHS,
) -> str:
    action_int = int(action)
    num_actions = three_head_num_actions_for_widths(action_widths)
    if state == THREE_HEAD_CASH:
        if action_int == THREE_HEAD_CASH_STAY:
            return "stay_cash"
        if action_int >= 1 + len(tuple(action_widths)):
            return "masked_cash_slot"
        return f"enter_w{three_head_action_to_width(action_int, state, action_widths)}"
    if state == THREE_HEAD_IN_RANGE:
        if action_int == THREE_HEAD_HOLD:
            return "hold"
        if action_int == THREE_HEAD_GO_CASH:
            return "go_cash"
        return f"recenter_w{three_head_action_to_width(action_int, state, action_widths)}"
    if state == THREE_HEAD_OOR:
        if action_int == THREE_HEAD_HOLD:
            return "hold_oor"
        if action_int == THREE_HEAD_GO_CASH:
            return "go_cash"
        return f"recenter_w{three_head_action_to_width(action_int, state, action_widths)}"
    raise ValueError(f"Unsupported state for three-head action label: {state}")


def projected_entry_features_for_width(
    env: UniswapV3HedgedFeeEnv,
    width: int,
    full_features: Optional[np.ndarray] = None,
) -> tuple[float, float]:
    """Live-observable projected entry economics for a candidate width."""
    if env.idx >= len(env.timestamps):
        return 0.0, 0.0
    if full_features is None:
        full_features = env.hourly_data.features.get(
            env.timestamps[env.idx], np.zeros(len(FEATURE_COLS), dtype=np.float32)
        )
    sigma_hourly = max(float(full_features[FEATURE_COLS.index("natr_14")]), 1e-6)
    volume_sma_ratio = float(full_features[FEATURE_COLS.index("volume_sma_ratio")])
    width_normalized = max(float(width) / 40.0, 0.01)
    half_width_ticks = (float(width) * env.tick_spacing) / 2.0
    half_width_frac = math.exp(half_width_ticks * math.log(1.0001)) - 1.0
    sigma_actual = sigma_hourly / 1.3
    expected_hours_to_oor = min(
        (half_width_frac ** 2) / max(sigma_actual ** 2, 1e-12),
        500.0,
    )
    fee_il_ratio = min(
        10.0,
        volume_sma_ratio
        * env.pool_fee
        / max(sigma_hourly ** 2 * width_normalized, 1e-10),
    )
    return expected_hours_to_oor / 100.0, fee_il_ratio


def select_timing_width(
    obs: np.ndarray,
    hedge_accounting_mode: str,
    width_mode: str = "heuristic",
    fixed_width: int = 10,
) -> int:
    if width_mode not in {"heuristic", "fixed"}:
        raise ValueError("width_mode must be 'heuristic' or 'fixed'")
    if width_mode == "fixed":
        return int(fixed_width)
    if hedge_accounting_mode == HEDGE_ACCOUNTING_CONTINUOUS:
        return int(conservative_optimal_width_for_vol(float(obs[1])))
    return int(optimal_width_for_vol(float(obs[1])))


def project_timing_observation(
    env: UniswapV3HedgedFeeEnv,
    obs: np.ndarray,
    width_mode: str = "heuristic",
    fixed_width: int = 10,
) -> np.ndarray:
    """Project cash-state timing features for the LP that stage 1 would enter."""
    if env.idx >= len(env.timestamps):
        return obs

    price = env._get_price(env.timestamps[env.idx])
    if env._position_state(price) != "cash":
        return obs

    projected_width = select_timing_width(
        obs=obs,
        hedge_accounting_mode=env.hedge_accounting_mode,
        width_mode=width_mode,
        fixed_width=fixed_width,
    )
    width_normalized = projected_width / 40.0
    full_features = env.hourly_data.features.get(env.timestamps[env.idx])
    if full_features is None:
        return obs

    sigma_hourly = max(float(full_features[FEATURE_COLS.index("natr_14")]), 1e-6)
    half_width_ticks = (projected_width * env.tick_spacing) / 2.0
    dist_to_boundary_sigma = min(5.0, (half_width_ticks * 0.0001) / sigma_hourly)
    half_width_frac = math.exp((projected_width * env.tick_spacing / 2.0) * math.log(1.0001)) - 1.0
    sigma_actual = sigma_hourly / 1.3
    expected_hours_to_oor = min(
        (half_width_frac ** 2) / max(sigma_actual ** 2, 1e-12),
        500.0,
    )
    volume_sma_ratio = float(full_features[FEATURE_COLS.index("volume_sma_ratio")])
    fee_il_ratio = min(
        10.0,
        volume_sma_ratio
        * env.pool_fee
        / max(sigma_hourly ** 2 * max(width_normalized, 0.01), 1e-10),
    )

    obs = obs.copy()
    pos_start = obs.shape[0] - 12
    obs[pos_start + 0] = width_normalized
    obs[pos_start + 1] = 1.0
    obs[pos_start + 2] = dist_to_boundary_sigma
    obs[pos_start + 3] = 0.0
    obs[pos_start + 4] = expected_hours_to_oor / 100.0
    obs[pos_start + 5] = fee_il_ratio
    obs[pos_start + 10] = 0.0
    obs[pos_start + 11] = 1.0
    return obs

class UniswapV3HedgedTimingEnv(UniswapV3HedgedFeeEnv):
    """Binary hourly timing env with heuristic or fixed width on LP decisions."""

    def __init__(
        self,
        *args,
        width_mode: str = "heuristic",
        fixed_width: int = 10,
        randomize_start: bool = False,
        min_episode_hours: int = 500,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        if width_mode not in {"heuristic", "fixed"}:
            raise ValueError("width_mode must be 'heuristic' or 'fixed'")
        self.width_mode = width_mode
        self.fixed_width = fixed_width
        self.randomize_start = randomize_start
        self.min_episode_hours = max(int(min_episode_hours), 1)
        self._base_action_space = spaces.Discrete(10)
        self.action_space = spaces.Discrete(2)

    def _select_width(self, obs: np.ndarray) -> int:
        return select_timing_width(
            obs=obs,
            hedge_accounting_mode=self.hedge_accounting_mode,
            width_mode=self.width_mode,
            fixed_width=self.fixed_width,
        )

    def _get_obs(self):
        return project_timing_observation(
            env=self,
            obs=super()._get_obs(),
            width_mode=self.width_mode,
            fixed_width=self.fixed_width,
        )

    def _step_base_action(self, env_action: int):
        current_action_space = self.action_space
        self.action_space = self._base_action_space
        try:
            return super().step(env_action)
        finally:
            self.action_space = current_action_space

    def reset(self, seed=None, options=None):
        obs, info = super().reset(seed=seed, options=options)
        if self.randomize_start and self.n_steps > self.min_episode_hours:
            max_start = max(self.n_steps - self.min_episode_hours, 0)
            self.idx = int(self.np_random.integers(0, max_start + 1))
            self._set_cash_state(self.initial_capital)
            obs = self._get_obs()
        return obs, info

    def step(self, action):
        action_int = int(action)
        if action_int not in (TIMING_TO_CASH, TIMING_TO_LP):
            raise ValueError(f"Timing action out of range: {action_int}")

        if self.idx >= self.n_steps:
            return self._get_obs(), 0.0, True, False, {}

        price = self._get_price(self.timestamps[self.idx])
        position_state = self._position_state(price)
        obs = self._get_obs()
        selected_width = 0

        if position_state == "cash":
            if action_int == TIMING_TO_LP:
                selected_width = self._select_width(obs)
                env_action = width_to_action(selected_width)
            else:
                env_action = HOLD_ACTION
        elif position_state == "lp_in_range":
            env_action = HOLD_ACTION if action_int == TIMING_TO_LP else GO_CASH_ACTION
        else:  # lp_oor
            if action_int == TIMING_TO_LP:
                selected_width = self._select_width(obs)
                env_action = width_to_action(selected_width)
            else:
                env_action = GO_CASH_ACTION

        next_obs, reward, terminated, truncated, info = self._step_base_action(env_action)
        info.update(
            {
                "timing_action": action_int,
                "timing_action_label": (
                    "lp_next_hour" if action_int == TIMING_TO_LP else "cash_next_hour"
                ),
                "decision_state": position_state,
                "selected_width": selected_width,
                "width_mode": self.width_mode,
            }
        )
        return next_obs, reward, terminated, truncated, info


class UniswapV3HedgedWidthEnv(UniswapV3HedgedFeeEnv):
    """Event-driven width env controlled by a frozen hourly timing policy."""

    def __init__(
        self,
        *args,
        timing_policy,
        randomize_start: bool = False,
        min_episode_hours: int = 500,
        max_reset_attempts: int = 32,
        reward_mode: str = "per_decision_hour",
        width_action_mode: str = WIDTH_ACTION_MODE_ABSOLUTE,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.timing_policy = timing_policy
        self.randomize_start = randomize_start
        self.min_episode_hours = max(int(min_episode_hours), 1)
        self.max_reset_attempts = max(int(max_reset_attempts), 1)
        if reward_mode not in {"total", "per_decision_hour"}:
            raise ValueError("reward_mode must be 'total' or 'per_decision_hour'")
        if width_action_mode not in WIDTH_ACTION_MODES:
            raise ValueError(
                f"width_action_mode must be one of {WIDTH_ACTION_MODES}, got {width_action_mode}"
            )
        self.reward_mode = reward_mode
        self.width_action_mode = width_action_mode
        self._base_action_space = spaces.Discrete(10)
        self.action_space = spaces.Discrete(len(width_action_values(self.width_action_mode)))
        self._terminal_after_reset = False

    def _predict_timing_action(self, obs: np.ndarray) -> int:
        obs_for_timing = project_timing_observation(
            env=self,
            obs=obs,
            width_mode=getattr(self.timing_policy, "timing_width_mode", "heuristic"),
            fixed_width=getattr(self.timing_policy, "timing_fixed_width", 10),
        )
        prediction = self.timing_policy.predict(obs_for_timing, return_q=False)
        if hasattr(prediction, "value"):
            return int(prediction.value)
        if isinstance(prediction, tuple):
            return int(prediction[0])
        return int(prediction)

    def _step_base_action(self, env_action: int):
        current_action_space = self.action_space
        self.action_space = self._base_action_space
        try:
            return super().step(env_action)
        finally:
            self.action_space = current_action_space

    def _zero_components(self) -> dict:
        return {
            "lp_value_change_usd": 0.0,
            "hedge_pnl_usd": 0.0,
            "swing_pnl_usd": 0.0,
            "raw_lp_value_change_usd": 0.0,
            "raw_hedge_pnl_usd": 0.0,
            "raw_swing_pnl_usd": 0.0,
            "raw_boundary_il_usd": 0.0,
            "realized_boundary_pnl_usd": 0.0,
            "pending_boundary_pnl_usd": 0.0,
            "fee_usd": 0.0,
            "funding_cost_usd": 0.0,
            "hedged_core_pnl_usd": 0.0,
            "gross_fee_carry_usd": 0.0,
            "net_before_tx_usd": 0.0,
            "net_after_tx_usd": 0.0,
            "tx_cost_usd": 0.0,
            "swap_fee_cost_usd": 0.0,
            "mev_cost_usd": 0.0,
            "reward_usd": 0.0,
        }

    def _add_components(self, totals: dict, info: dict) -> None:
        for key in ADDITIVE_COMPONENT_KEYS:
            totals[key] += float(info.get(key, 0.0))
        totals["pending_boundary_pnl_usd"] = float(info.get("pending_boundary_pnl_usd", 0.0))
        totals["raw_boundary_il_usd"] = float(info.get("raw_boundary_il_usd", 0.0))

    def _merge_component_totals(self, totals: dict, updates: dict) -> None:
        for key in ADDITIVE_COMPONENT_KEYS:
            totals[key] += float(updates.get(key, 0.0))
        totals["pending_boundary_pnl_usd"] = float(
            updates.get("pending_boundary_pnl_usd", totals["pending_boundary_pnl_usd"])
        )
        totals["raw_boundary_il_usd"] = float(
            updates.get("raw_boundary_il_usd", totals["raw_boundary_il_usd"])
        )

    def _current_state(self) -> str:
        if self.idx >= self.n_steps:
            return "terminal"
        price = self._get_price(self.timestamps[self.idx])
        return self._position_state(price)

    def _fast_forward_cash_to_entry_boundary(self) -> dict:
        hours_fast_forwarded = 0
        while self.idx < self.n_steps:
            if self._current_state() != "cash":
                return {
                    "terminated": False,
                    "hours_fast_forwarded": hours_fast_forwarded,
                    "decision_state": self._current_state(),
                }
            obs = self._get_obs()
            timing_action = self._predict_timing_action(obs)
            if timing_action == TIMING_TO_LP:
                return {
                    "terminated": False,
                    "hours_fast_forwarded": hours_fast_forwarded,
                    "decision_state": "cash",
                }
            _, _, terminated, _, _ = self._step_base_action(HOLD_ACTION)
            hours_fast_forwarded += 1
            if terminated:
                break
        return {
            "terminated": True,
            "hours_fast_forwarded": hours_fast_forwarded,
            "decision_state": "terminal",
        }

    def _roll_stint_until_next_width_boundary(self) -> dict:
        totals = self._zero_components()
        hours = 0

        while self.idx < self.n_steps:
            state = self._current_state()
            if state == "cash":
                return {
                    "terminated": False,
                    "hours": hours,
                    "stint_end_reason": "cash_boundary",
                    "next_decision_state": "cash",
                    "components": totals,
                }

            obs = self._get_obs()
            timing_action = self._predict_timing_action(obs)

            if state == "lp_in_range":
                env_action = HOLD_ACTION if timing_action == TIMING_TO_LP else GO_CASH_ACTION
            else:  # lp_oor
                if timing_action == TIMING_TO_LP:
                    return {
                        "terminated": False,
                        "hours": hours,
                        "stint_end_reason": "oor_boundary",
                        "next_decision_state": "lp_oor",
                        "components": totals,
                    }
                env_action = GO_CASH_ACTION

            _, _, terminated, _, info = self._step_base_action(env_action)
            self._add_components(totals, info)
            hours += 1

            if terminated:
                return {
                    "terminated": True,
                    "hours": hours,
                    "stint_end_reason": "terminal",
                    "next_decision_state": "terminal",
                    "components": totals,
                }

            if env_action == GO_CASH_ACTION:
                return {
                    "terminated": False,
                    "hours": hours,
                    "stint_end_reason": "cash_exit",
                    "next_decision_state": "cash",
                    "components": totals,
                }

        return {
            "terminated": True,
            "hours": hours,
            "stint_end_reason": "terminal",
            "next_decision_state": "terminal",
            "components": totals,
        }

    def reset(self, seed=None, options=None):
        attempts = self.max_reset_attempts if self.randomize_start else 1
        self._terminal_after_reset = False

        for attempt in range(attempts):
            obs, info = super().reset(seed=seed if attempt == 0 else None, options=options)
            if self.randomize_start and self.n_steps > self.min_episode_hours:
                max_start = max(self.n_steps - self.min_episode_hours, 0)
                self.idx = int(self.np_random.integers(0, max_start + 1))
                self._set_cash_state(self.initial_capital)

            ff = self._fast_forward_cash_to_entry_boundary()
            if not ff["terminated"]:
                return self._get_obs(), ff

        self._terminal_after_reset = True
        message = (
            "Width env found no cash->LP or OOR->recenter boundary under the frozen timing policy"
        )
        if self.randomize_start:
            message += f" after {attempts} reset attempts"
        raise RuntimeError(message)

    def step(self, action):
        if self._terminal_after_reset or self.idx >= self.n_steps:
            return self._get_obs(), 0.0, True, False, {"decision_state": "terminal"}

        decision_state = self._current_state()
        if decision_state not in {"cash", "lp_oor"}:
            raise RuntimeError(
                f"Width env must only act on cash or OOR boundaries, got {decision_state}"
            )

        obs_before = self._get_obs()
        width_decision_value = width_action_index_to_value(action, self.width_action_mode)
        heuristic_width = heuristic_width_from_obs(obs_before)
        width = width_decision_to_width(
            width_decision_value,
            obs_before,
            self.width_action_mode,
        )
        env_action = width_to_action(width)
        _, _, terminated, _, info = self._step_base_action(env_action)

        totals = self._zero_components()
        self._add_components(totals, info)
        total_hours = 1
        decision_hours = 1
        fast_forward_cash_hours = 0
        stint_end_reason = "terminal" if terminated else "post_width_hour"
        next_decision_state = self._current_state() if not terminated else "terminal"

        if not terminated:
            roll = self._roll_stint_until_next_width_boundary()
            self._merge_component_totals(totals, roll["components"])
            total_hours += int(roll["hours"])
            decision_hours += int(roll["hours"])
            terminated = bool(roll["terminated"])
            stint_end_reason = roll["stint_end_reason"]
            next_decision_state = roll["next_decision_state"]

            if not terminated and next_decision_state == "cash":
                ff = self._fast_forward_cash_to_entry_boundary()
                fast_forward_cash_hours = int(ff["hours_fast_forwarded"])
                total_hours += fast_forward_cash_hours
                terminated = bool(ff["terminated"])
                next_decision_state = ff["decision_state"]
                if not terminated:
                    stint_end_reason = "cash_reentry_boundary"
                else:
                    stint_end_reason = "terminal"

        reward_usd_total = float(totals["reward_usd"])
        reward_usd_per_decision_hour = reward_usd_total / max(float(decision_hours), 1.0)
        training_reward_usd = (
            reward_usd_total
            if self.reward_mode == "total"
            else reward_usd_per_decision_hour
        )
        reward = float(training_reward_usd / self._reward_denom())
        info_out = {
            "decision_state": decision_state,
            "selected_width": width,
            "selected_width_index": int(action),
            "width_decision_value": int(width_decision_value),
            "heuristic_width": int(heuristic_width),
            "next_decision_state": next_decision_state,
            "decision_hours": decision_hours,
            "fast_forward_cash_hours": fast_forward_cash_hours,
            "stint_hours": total_hours,
            "stint_end_reason": stint_end_reason,
            "reward_mode": self.reward_mode,
            "width_action_mode": self.width_action_mode,
            "training_reward_usd": training_reward_usd,
            "reward_usd_per_decision_hour": reward_usd_per_decision_hour,
            "hedge_accounting_mode": self.hedge_accounting_mode,
            "portfolio_value": self.get_portfolio_value(),
            "reward": reward,
            **totals,
        }
        return self._get_obs(), reward, terminated, False, info_out


class UniswapV3HedgedThreeHeadEnv(UniswapV3HedgedFeeEnv):
    """One-model env with explicit cash, in-range, and OOR hourly decisions."""

    def __init__(
        self,
        *args,
        randomize_start: bool = False,
        min_episode_hours: int = 72,
        max_episode_hours: Optional[int] = None,
        action_widths: Sequence[int] = THREE_HEAD_ACTION_WIDTHS,
        allow_in_range_recenter: bool = True,
        oor_recenter_same_width_only: bool = False,
        include_paper_signal_features: bool = False,
        cash_start_prob: float = 0.60,
        in_range_start_prob: float = 0.20,
        oor_start_prob: float = 0.20,
        positive_start_indices: Optional[Sequence[int]] = None,
        hard_negative_start_indices: Optional[Sequence[int]] = None,
        reward_scale: float = 1.0,
        **kwargs,
    ):
        if "training_reward_mode" not in kwargs:
            kwargs["training_reward_mode"] = TRAINING_REWARD_REALISTIC
        super().__init__(*args, **kwargs)
        self.reward_scale = float(reward_scale)
        self.randomize_start = bool(randomize_start)
        self.min_episode_hours = max(int(min_episode_hours), 1)
        self.max_episode_hours = (
            self.min_episode_hours
            if max_episode_hours is None
            else max(int(max_episode_hours), self.min_episode_hours)
        )
        self.action_widths = tuple(int(w) for w in action_widths)
        if not self.action_widths:
            raise ValueError("Three-head env requires at least 1 entry width")
        self.allow_in_range_recenter = bool(allow_in_range_recenter)
        self.oor_recenter_same_width_only = bool(oor_recenter_same_width_only)
        self.include_paper_signal_features = bool(include_paper_signal_features)
        weights = np.array(
            [float(cash_start_prob), float(in_range_start_prob), float(oor_start_prob)],
            dtype=np.float64,
        )
        if np.any(weights < 0) or float(weights.sum()) <= 0.0:
            raise ValueError("Start-state probabilities must be non-negative and sum to > 0")
        self.start_state_probs = tuple((weights / weights.sum()).tolist())
        self.positive_start_indices = tuple(
            sorted(
                {
                    int(idx)
                    for idx in (positive_start_indices or ())
                    if 0 <= int(idx) < self.n_steps
                }
            )
        )
        self.hard_negative_start_indices = tuple(
            sorted(
                {
                    int(idx)
                    for idx in (hard_negative_start_indices or ())
                    if 0 <= int(idx) < self.n_steps
                }
            )
        )
        self._base_action_space = spaces.Discrete(10)
        self.base_state_dim = int(self.state_dim)
        self.decision_state_dim = len(THREE_HEAD_STATES)
        self.paper_feature_dim = 2 if self.include_paper_signal_features else 0
        self.candidate_entry_feature_dim = 2 * len(self.action_widths)
        self.state_dim = (
            self.decision_state_dim
            + self.paper_feature_dim
            + self.candidate_entry_feature_dim
            + self.base_state_dim
        )
        self.observation_space = spaces.Box(
            low=-np.inf,
            high=np.inf,
            shape=(self.state_dim,),
            dtype=np.float32,
        )
        self._num_actions = three_head_num_actions_for_widths(self.action_widths)
        self.action_space = spaces.Discrete(self._num_actions)
        self.state_action_masks = build_three_head_masks(self.action_widths)
        if not self.allow_in_range_recenter and self.oor_recenter_same_width_only:
            # Restricted mode: in-range only hold/exit; OOR only hold/exit/recenter-same
            lp_ir_mask = np.zeros(self._num_actions, dtype=np.bool_)
            lp_ir_mask[:2] = True  # hold + exit only
            lp_oor_mask = np.zeros(self._num_actions, dtype=np.bool_)
            lp_oor_mask[:2] = True  # hold + exit
            lp_oor_mask[2] = True  # recenter slot 0 (same-width sentinel)
            self.state_action_masks[THREE_HEAD_STATES.index(THREE_HEAD_IN_RANGE)] = lp_ir_mask
            self.state_action_masks[THREE_HEAD_STATES.index(THREE_HEAD_OOR)] = lp_oor_mask
        self._episode_end_idx = self.n_steps
        self._prepare_paper_signal_features()

    def _prepare_paper_signal_features(self) -> None:
        bb_idx = FEATURE_COLS.index("bb_width")
        bb_values = np.asarray(
            [
                float(
                    self.hourly_data.features.get(
                        t, np.zeros(len(FEATURE_COLS), dtype=np.float32)
                    )[bb_idx]
                )
                for t in self.timestamps
            ],
            dtype=np.float32,
        )
        medians = np.maximum(compute_expanding_median(bb_values), 1e-6)
        self._bb_width_values = bb_values
        self._bb_width_expanding_median = medians
        self._bb_width_ratio = np.clip(bb_values / medians, 0.0, 10.0).astype(np.float32)
        self._bb_width_signal = (bb_values > medians).astype(np.float32)

    def _step_base_action(self, env_action: int):
        current_action_space = self.action_space
        self.action_space = self._base_action_space
        try:
            return super().step(env_action)
        finally:
            self.action_space = current_action_space

    def _zero_components(self) -> dict:
        return {
            "lp_value_change_usd": 0.0,
            "hedge_pnl_usd": 0.0,
            "swing_pnl_usd": 0.0,
            "raw_lp_value_change_usd": 0.0,
            "raw_hedge_pnl_usd": 0.0,
            "raw_swing_pnl_usd": 0.0,
            "raw_boundary_il_usd": 0.0,
            "realized_boundary_pnl_usd": 0.0,
            "pending_boundary_pnl_usd": 0.0,
            "fee_usd": 0.0,
            "funding_cost_usd": 0.0,
            "hedged_core_pnl_usd": 0.0,
            "gross_fee_carry_usd": 0.0,
            "net_before_tx_usd": 0.0,
            "net_after_tx_usd": 0.0,
            "tx_cost_usd": 0.0,
            "swap_fee_cost_usd": 0.0,
            "mev_cost_usd": 0.0,
            "reward_usd": 0.0,
        }

    def _add_components(self, totals: dict, info: dict) -> None:
        for key in ADDITIVE_COMPONENT_KEYS:
            totals[key] += float(info.get(key, 0.0))
        totals["pending_boundary_pnl_usd"] = float(info.get("pending_boundary_pnl_usd", 0.0))
        totals["raw_boundary_il_usd"] = float(info.get("raw_boundary_il_usd", 0.0))

    def _current_state(self) -> str:
        if self.idx >= min(self.n_steps, self._episode_end_idx):
            return "terminal"
        return self._position_state(self._get_price(self.timestamps[self.idx]))

    def _sample_episode_horizon(self) -> int:
        if not self.randomize_start:
            return self.n_steps
        if self.max_episode_hours <= self.min_episode_hours:
            return self.min_episode_hours
        return int(self.np_random.integers(self.min_episode_hours, self.max_episode_hours + 1))

    def _set_episode_window(self, start_idx: int) -> None:
        horizon = self._sample_episode_horizon()
        self._episode_end_idx = min(self.n_steps, int(start_idx) + int(horizon))

    def _sample_cash_start_idx(self, max_start: int) -> tuple[int, bool, bool]:
        eligible_positive = [idx for idx in self.positive_start_indices if idx <= max_start]
        eligible_negative = [idx for idx in self.hard_negative_start_indices if idx <= max_start]
        use_positive = False
        use_negative = False
        if eligible_positive and eligible_negative:
            use_positive = bool(float(self.np_random.random()) < 0.5)
            use_negative = not use_positive
        elif eligible_positive:
            use_positive = True
        elif eligible_negative:
            use_negative = True

        if use_positive:
            idx = int(eligible_positive[int(self.np_random.integers(0, len(eligible_positive)))])
            return idx, True, False
        if use_negative:
            idx = int(eligible_negative[int(self.np_random.integers(0, len(eligible_negative)))])
            return idx, False, True
        return int(self.np_random.integers(0, max_start + 1)), False, False

    def _initialize_historical_position_state(
        self,
        target_idx: int,
        desired_state: str,
        max_attempts: int = 32,
    ) -> bool:
        target_idx = int(target_idx)
        if desired_state not in {THREE_HEAD_IN_RANGE, THREE_HEAD_OOR} or target_idx <= 0:
            return False

        snapshot = self.get_state_snapshot()
        max_lookback = min(
            target_idx,
            max(self.max_episode_hours * 2, self.min_episode_hours),
        )
        if max_lookback <= 0:
            return False

        for _ in range(max_attempts):
            width = int(self.action_widths[int(self.np_random.integers(0, len(self.action_widths)))])
            lookback = int(self.np_random.integers(1, max_lookback + 1))
            entry_idx = max(0, target_idx - lookback)

            self.load_state_snapshot(snapshot)
            self.idx = entry_idx
            self._set_cash_state(self.initial_capital)
            entry_price = self._get_price(self.timestamps[self.idx])
            if not self._open_position(self.initial_capital, entry_price, width):
                continue

            terminated = False
            while self.idx < target_idx:
                _, _, terminated, _, _ = self._step_base_action(HOLD_ACTION)
                if terminated:
                    break

            if terminated or self.idx != target_idx:
                continue

            current_state = self._position_state(self._get_price(self.timestamps[self.idx]))
            if current_state != desired_state:
                continue
            if self.position_entry_idx >= self.idx:
                continue
            return True

        self.load_state_snapshot(snapshot)
        return False

    def _explicit_exit_to_cash_components(self, price_t0: float, raw_boundary_before: float) -> dict:
        capital_before_cost = self._capital_if_closed_now(price_t0)
        swap_frac = self._compute_exit_swap_fraction(price_t0)
        tx_cost, swap_fee_cost, mev_cost = self._compute_trade_costs(
            capital_before_cost, swap_frac
        )
        self._set_cash_state(capital_before_cost - tx_cost)
        return self._with_pnl_breakdown(
            {
                "lp_value_change_usd": 0.0,
                "hedge_pnl_usd": 0.0,
                "swing_pnl_usd": 0.0,
                "raw_boundary_il_usd": raw_boundary_before,
                "realized_boundary_pnl_usd": raw_boundary_before,
                "pending_boundary_pnl_usd": 0.0,
                "fee_usd": 0.0,
                "funding_cost_usd": 0.0,
                "tx_cost_usd": float(tx_cost),
                "swap_fee_cost_usd": float(swap_fee_cost),
                "mev_cost_usd": float(mev_cost),
            }
        )

    def _explicit_recenter_components(
        self,
        price_t0: float,
        price_t1: float,
        target_width: int,
        raw_boundary_before: float,
    ) -> dict:
        capital_before_cost = self._capital_if_closed_now(price_t0)
        old_lower_price, old_upper_price = self._lp_bounds_prices()
        new_lower_tick, new_upper_tick = self._compute_position_bounds(price_t0, target_width)
        new_lower_price = tick_to_price(new_lower_tick)
        new_upper_price = tick_to_price(new_upper_tick)
        swap_frac = self._compute_swap_fraction(
            price_t0,
            old_lower_price,
            old_upper_price,
            self.liquidity,
            new_lower_price,
            new_upper_price,
        )
        return self._enter_or_recenter_components(
            price_t0=price_t0,
            price_t1=price_t1,
            target_width=target_width,
            capital_before_cost=capital_before_cost,
            swap_frac=swap_frac,
            realized_boundary_pnl=raw_boundary_before,
            raw_boundary_il_usd=raw_boundary_before,
        )

    def _valid_action_mask_for_state(self, state: str) -> np.ndarray:
        return self.state_action_masks[THREE_HEAD_STATES.index(state)].copy()

    def _safe_default_action(self, state: str) -> int:
        if state == THREE_HEAD_CASH:
            return THREE_HEAD_CASH_STAY
        return THREE_HEAD_HOLD

    def _paper_signal_features(self) -> np.ndarray:
        if not self.include_paper_signal_features:
            return np.zeros(0, dtype=np.float32)
        local_idx = min(self.idx, len(self._bb_width_ratio) - 1)
        return np.asarray(
            [
                self._bb_width_ratio[local_idx],
                self._bb_width_signal[local_idx],
            ],
            dtype=np.float32,
        )

    def requested_three_head_width(self, action: int, state: str) -> int:
        action_int = int(action)
        if state == THREE_HEAD_CASH:
            return three_head_action_to_width(action_int, state, self.action_widths)
        if state == THREE_HEAD_OOR and self.oor_recenter_same_width_only:
            # Action 2 = recenter slot; in same-width mode, reuse current width
            if action_int == 2 and self.has_lp:
                return int(self.lp_width_ticks / self.tick_spacing)
            return 0
        if state == THREE_HEAD_IN_RANGE and not self.allow_in_range_recenter:
            return 0
        return three_head_action_to_width(action_int, state, self.action_widths)

    def requested_three_head_action_label(self, action: int, state: str) -> str:
        action_int = int(action)
        # Check if this is the masked cash slot (last action for cash state)
        if state == THREE_HEAD_CASH and action_int >= 1 + len(self.action_widths):
            return "masked_cash_slot"
        valid_mask = self._valid_action_mask_for_state(state)
        if not valid_mask[action_int]:
            return "masked_invalid_action"
        if state == THREE_HEAD_CASH:
            if action_int == THREE_HEAD_CASH_STAY:
                return "stay_cash"
            return f"enter_w{self.requested_three_head_width(action_int, state)}"
        if state == THREE_HEAD_IN_RANGE:
            if action_int == THREE_HEAD_HOLD:
                return "hold"
            if action_int == THREE_HEAD_GO_CASH:
                return "go_cash"
            return f"recenter_w{self.requested_three_head_width(action_int, state)}"
        if state == THREE_HEAD_OOR:
            if action_int == THREE_HEAD_HOLD:
                return "hold_oor"
            if action_int == THREE_HEAD_GO_CASH:
                return "go_cash"
            if self.oor_recenter_same_width_only:
                return "recenter_same_width"
            return f"recenter_w{self.requested_three_head_width(action_int, state)}"
        raise ValueError(f"Unsupported state for three-head action label: {state}")

    def _get_obs(self):
        if self.idx >= len(self.timestamps):
            return np.zeros(self.state_dim, dtype=np.float32)
        state = self._position_state(self._get_price(self.timestamps[self.idx]))
        base_obs = UniswapV3HedgedFeeEnv._get_obs(self)
        full_features = self.hourly_data.features.get(
            self.timestamps[self.idx], np.zeros(len(FEATURE_COLS), dtype=np.float32)
        )
        candidate_features = []
        for width in self.action_widths:
            hours_to_oor, fee_il_ratio = projected_entry_features_for_width(
                self,
                width=width,
                full_features=full_features,
            )
            candidate_features.extend([hours_to_oor, fee_il_ratio])
        return np.concatenate(
            [
                three_head_state_one_hot(state),
                self._paper_signal_features(),
                np.asarray(candidate_features, dtype=np.float32),
                base_obs,
            ]
        )

    def reset(self, seed=None, options=None):
        obs, info = super().reset(seed=seed, options=options)
        requested_start_state = THREE_HEAD_CASH
        initialized_start_state = THREE_HEAD_CASH
        used_positive_start = False
        used_hard_negative_start = False

        if self.randomize_start and self.n_steps > self.min_episode_hours:
            max_start = max(self.n_steps - self.min_episode_hours, 0)
            requested_start_state = str(
                self.np_random.choice(THREE_HEAD_STATES, p=self.start_state_probs)
            )
            if requested_start_state == THREE_HEAD_CASH:
                target_idx, used_positive_start, used_hard_negative_start = self._sample_cash_start_idx(
                    max_start
                )
                self.idx = int(target_idx)
                self._set_cash_state(self.initial_capital)
                initialized_start_state = THREE_HEAD_CASH
            else:
                target_idx = int(self.np_random.integers(0, max_start + 1))
                self.idx = int(target_idx)
                self._set_cash_state(self.initial_capital)
                initialized = self._initialize_historical_position_state(
                    target_idx=target_idx,
                    desired_state=requested_start_state,
                )
                initialized_start_state = (
                    requested_start_state if initialized else THREE_HEAD_CASH
                )
                if not initialized:
                    self.idx = int(target_idx)
                    self._set_cash_state(self.initial_capital)

        self._set_episode_window(self.idx)
        obs = self._get_obs()
        info = {
            **info,
            "requested_start_state": requested_start_state,
            "initialized_start_state": initialized_start_state,
            "used_positive_start": used_positive_start,
            "used_hard_negative_start": used_hard_negative_start,
        }
        return obs, info

    def step(self, action):
        if self.idx >= min(self.n_steps, self._episode_end_idx):
            return self._get_obs(), 0.0, True, False, {"decision_state": "terminal"}

        action_int = int(action)
        if action_int < 0 or action_int >= self._num_actions:
            raise ValueError(f"Three-head action out of range: {action_int}")

        t0 = self.timestamps[self.idx]
        t1 = self.timestamps[self.idx + 1]
        price_t0 = self._get_price(t0)
        price_t1 = self._get_price(t1)
        decision_state = self._position_state(price_t0)
        valid_action_mask = self._valid_action_mask_for_state(decision_state)
        masked_invalid_action = not bool(valid_action_mask[action_int])
        applied_action = (
            self._safe_default_action(decision_state) if masked_invalid_action else action_int
        )
        requested_width = self.requested_three_head_width(applied_action, decision_state)
        raw_boundary_before = float(self._current_boundary_pnl(price_t0))

        if decision_state == THREE_HEAD_CASH:
            if requested_width > 0:
                effective_action = f"enter_w{requested_width}"
                components = self._enter_or_recenter_components(
                    price_t0=price_t0,
                    price_t1=price_t1,
                    target_width=requested_width,
                    capital_before_cost=self.actual_capital,
                    swap_frac=0.5,
                    realized_boundary_pnl=0.0,
                )
            else:
                effective_action = "stay_cash"
                components = self._with_pnl_breakdown(
                    {
                        "lp_value_change_usd": 0.0,
                        "hedge_pnl_usd": 0.0,
                        "swing_pnl_usd": 0.0,
                        "raw_boundary_il_usd": 0.0,
                        "realized_boundary_pnl_usd": 0.0,
                        "pending_boundary_pnl_usd": 0.0,
                        "fee_usd": 0.0,
                        "funding_cost_usd": 0.0,
                        "tx_cost_usd": 0.0,
                        "swap_fee_cost_usd": 0.0,
                        "mev_cost_usd": 0.0,
                    }
                )
        elif decision_state == THREE_HEAD_IN_RANGE:
            if applied_action == THREE_HEAD_HOLD:
                effective_action = "hold"
                components = self._lp_hour_components(price_t0, price_t1)
            elif applied_action == THREE_HEAD_GO_CASH:
                effective_action = "exit_to_cash"
                components = self._explicit_exit_to_cash_components(price_t0, raw_boundary_before)
            else:
                effective_action = f"recenter_w{requested_width}"
                components = self._explicit_recenter_components(
                    price_t0=price_t0,
                    price_t1=price_t1,
                    target_width=requested_width,
                    raw_boundary_before=raw_boundary_before,
                )
        else:  # lp_oor
            if applied_action == THREE_HEAD_HOLD:
                effective_action = "hold_oor"
                components = self._lp_hour_components(price_t0, price_t1)
            elif applied_action == THREE_HEAD_GO_CASH:
                effective_action = "exit_to_cash"
                components = self._explicit_exit_to_cash_components(price_t0, raw_boundary_before)
            else:
                effective_action = (
                    "recenter_same_width"
                    if self.oor_recenter_same_width_only
                    else f"recenter_w{requested_width}"
                )
                components = self._explicit_recenter_components(
                    price_t0=price_t0,
                    price_t1=price_t1,
                    target_width=requested_width,
                    raw_boundary_before=raw_boundary_before,
                )

        self.idx += 1
        terminated = self.idx >= min(self.n_steps, self._episode_end_idx)
        if terminated and not self.is_cash and self.has_lp:
            terminal_realization = float(self._current_boundary_pnl(price_t1))
            if self._uses_legacy_boundary_il() and abs(terminal_realization) > 0.0:
                components["realized_boundary_pnl_usd"] = (
                    float(components.get("realized_boundary_pnl_usd", 0.0))
                    + terminal_realization
                )
                components["pending_boundary_pnl_usd"] = 0.0
                components = self._with_pnl_breakdown(components)
            if not self._uses_legacy_boundary_il():
                components["raw_boundary_il_usd"] = float(
                    components.get("raw_boundary_il_usd", terminal_realization)
                )
                components = self._with_pnl_breakdown(components)
            terminal_capital = (
                self._capital_if_closed_now(price_t1)
                if self._uses_legacy_boundary_il()
                else self.get_portfolio_value()
            )
            self._set_cash_state(terminal_capital)

        training_reward_usd = self._training_reward_usd(
            position_state=decision_state,
            effective_action=effective_action,
            components=components,
        )
        reward = float(training_reward_usd / self._reward_denom()) * self.reward_scale
        next_state = "terminal" if terminated else self._position_state(price_t1)
        info = {
            "decision_state": decision_state,
            "requested_action": action_int,
            "requested_action_label": self.requested_three_head_action_label(
                action_int, decision_state
            ),
            "requested_width": int(requested_width),
            "selected_width": int(requested_width),
            "masked_invalid_action": bool(masked_invalid_action),
            "masked_cash_action": bool(
                decision_state == THREE_HEAD_CASH and masked_invalid_action
            ),
            "applied_action": int(applied_action),
            "applied_action_label": self.requested_three_head_action_label(
                applied_action, decision_state
            ),
            "effective_action": effective_action,
            "next_position_state": next_state,
            "price": price_t1,
            "hedge_accounting_mode": self.hedge_accounting_mode,
            "training_reward_mode": self.training_reward_mode,
            "portfolio_value": self.get_portfolio_value(),
            "close_now_portfolio_value": self._capital_if_closed_now(price_t1),
            "pending_boundary_pnl": float(self.pending_boundary_pnl),
            "is_cash": self.is_cash,
            "width": self.lp_width_ticks if self.has_lp else 0,
            "in_range": next_state == THREE_HEAD_IN_RANGE,
            **components,
            "training_reward_usd": float(training_reward_usd),
            "reward": reward,
            "state_action_mask": valid_action_mask.astype(np.int8),
        }
        return self._get_obs(), reward, terminated, False, info


class UniswapV3HedgedBoundaryEnv(UniswapV3HedgedFeeEnv):
    """Boundary DQN env: on cash/OOR boundaries choose cash or a width."""

    def __init__(
        self,
        *args,
        in_range_policy,
        randomize_start: bool = False,
        min_episode_hours: int = 500,
        reward_mode: str = "per_decision_hour",
        training_objective: str = TRAINING_OBJECTIVE_REALISTIC,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.in_range_policy = in_range_policy
        self.randomize_start = randomize_start
        self.min_episode_hours = max(int(min_episode_hours), 1)
        if reward_mode not in {"total", "per_decision_hour"}:
            raise ValueError("reward_mode must be 'total' or 'per_decision_hour'")
        if training_objective not in {
            TRAINING_OBJECTIVE_REALISTIC,
            TRAINING_OBJECTIVE_FEE_TX_SHAPED,
        }:
            raise ValueError(
                "training_objective must be 'realistic' or 'fee_tx_shaped'"
            )
        self.reward_mode = reward_mode
        self.training_objective = training_objective
        self._base_action_space = spaces.Discrete(10)
        self.action_space = spaces.Discrete(len(BOUNDARY_ACTION_WIDTHS))

    def _step_base_action(self, env_action: int):
        current_action_space = self.action_space
        self.action_space = self._base_action_space
        try:
            return super().step(env_action)
        finally:
            self.action_space = current_action_space

    def _zero_components(self) -> dict:
        return {
            "lp_value_change_usd": 0.0,
            "hedge_pnl_usd": 0.0,
            "swing_pnl_usd": 0.0,
            "raw_lp_value_change_usd": 0.0,
            "raw_hedge_pnl_usd": 0.0,
            "raw_swing_pnl_usd": 0.0,
            "raw_boundary_il_usd": 0.0,
            "realized_boundary_pnl_usd": 0.0,
            "pending_boundary_pnl_usd": 0.0,
            "fee_usd": 0.0,
            "funding_cost_usd": 0.0,
            "hedged_core_pnl_usd": 0.0,
            "gross_fee_carry_usd": 0.0,
            "net_before_tx_usd": 0.0,
            "net_after_tx_usd": 0.0,
            "tx_cost_usd": 0.0,
            "swap_fee_cost_usd": 0.0,
            "mev_cost_usd": 0.0,
            "reward_usd": 0.0,
        }

    def _add_components(self, totals: dict, info: dict) -> None:
        for key in ADDITIVE_COMPONENT_KEYS:
            totals[key] += float(info.get(key, 0.0))
        totals["pending_boundary_pnl_usd"] = float(info.get("pending_boundary_pnl_usd", 0.0))
        totals["raw_boundary_il_usd"] = float(info.get("raw_boundary_il_usd", 0.0))

    def _merge_component_totals(self, totals: dict, updates: dict) -> None:
        for key in ADDITIVE_COMPONENT_KEYS:
            totals[key] += float(updates.get(key, 0.0))
        totals["pending_boundary_pnl_usd"] = float(
            updates.get("pending_boundary_pnl_usd", totals["pending_boundary_pnl_usd"])
        )
        totals["raw_boundary_il_usd"] = float(
            updates.get("raw_boundary_il_usd", totals["raw_boundary_il_usd"])
        )

    def _current_state(self) -> str:
        if self.idx >= self.n_steps:
            return "terminal"
        return self._position_state(self._get_price(self.timestamps[self.idx]))

    def _predict_in_range_action(self, obs: np.ndarray) -> int:
        prediction = self.in_range_policy.predict(obs, return_q=False)
        if hasattr(prediction, "value"):
            return int(prediction.value)
        if isinstance(prediction, tuple):
            return int(prediction[0])
        return int(prediction)

    def _roll_until_boundary(self) -> dict:
        totals = self._zero_components()
        hours = 0
        while self.idx < self.n_steps:
            state = self._current_state()
            if state != "lp_in_range":
                return {
                    "terminated": False,
                    "hours": hours,
                    "next_decision_state": state,
                    "components": totals,
                }
            obs = self._get_obs()
            action = self._predict_in_range_action(obs)
            env_action = HOLD_ACTION if action == IN_RANGE_HOLD else GO_CASH_ACTION
            _, _, terminated, _, info = self._step_base_action(env_action)
            self._add_components(totals, info)
            hours += 1
            if terminated:
                return {
                    "terminated": True,
                    "hours": hours,
                    "next_decision_state": "terminal",
                    "components": totals,
                }
        return {
            "terminated": True,
            "hours": hours,
            "next_decision_state": "terminal",
            "components": totals,
        }

    def reset(self, seed=None, options=None):
        obs, info = super().reset(seed=seed, options=options)
        if self.randomize_start and self.n_steps > self.min_episode_hours:
            max_start = max(self.n_steps - self.min_episode_hours, 0)
            self.idx = int(self.np_random.integers(0, max_start + 1))
            self._set_cash_state(self.initial_capital)
            obs = self._get_obs()
        return obs, info

    def step(self, action):
        if self.idx >= self.n_steps:
            return self._get_obs(), 0.0, True, False, {"decision_state": "terminal"}

        decision_state = self._current_state()
        if decision_state not in {"cash", "lp_oor"}:
            raise RuntimeError(
                f"Boundary env must act on cash or OOR states, got {decision_state}"
            )

        width = boundary_action_to_width(action)
        if decision_state == "cash":
            env_action = HOLD_ACTION if width == 0 else width_to_action(width)
        else:
            env_action = GO_CASH_ACTION if width == 0 else width_to_action(width)

        _, _, terminated, _, info = self._step_base_action(env_action)
        totals = self._zero_components()
        self._add_components(totals, info)
        total_hours = 1
        next_decision_state = self._current_state() if not terminated else "terminal"

        if not terminated and next_decision_state == "lp_in_range":
            roll = self._roll_until_boundary()
            self._merge_component_totals(totals, roll["components"])
            total_hours += int(roll["hours"])
            terminated = bool(roll["terminated"])
            next_decision_state = roll["next_decision_state"]

        reward_usd_total = float(totals["reward_usd"])
        if self.training_objective == TRAINING_OBJECTIVE_FEE_TX_SHAPED:
            reward_usd_total = float(totals["fee_usd"] - totals["tx_cost_usd"])
        training_reward_usd = (
            reward_usd_total
            if self.reward_mode == "total"
            else reward_usd_total / max(float(total_hours), 1.0)
        )
        reward = float(training_reward_usd / self._reward_denom())
        info_out = {
            "decision_state": decision_state,
            "selected_width": width,
            "boundary_action_label": boundary_action_label(action, decision_state),
            "stint_hours": total_hours,
            "next_decision_state": next_decision_state,
            "reward_mode": self.reward_mode,
            "training_objective": self.training_objective,
            "training_reward_usd": training_reward_usd,
            "hedge_accounting_mode": self.hedge_accounting_mode,
            "portfolio_value": self.get_portfolio_value(),
            "reward": reward,
            **totals,
        }
        return self._get_obs(), reward, terminated, False, info_out


class UniswapV3HedgedCashOOREnv(UniswapV3HedgedFeeEnv):
    """Cash/OOR DQN env: choose stay/hold, exit, or width with in-range fixed to hold."""

    def __init__(
        self,
        *args,
        randomize_start: bool = False,
        min_episode_hours: int = 72,
        max_episode_hours: Optional[int] = None,
        oor_start_prob: float = 0.0,
        oor_start_mode: str = "historical",
        oor_recenter_mode: str = OOR_RECENTER_REQUESTED,
        action_widths=ENTRY_WIDTHS,
        reward_mode: str = "per_decision_hour",
        training_objective: str = TRAINING_OBJECTIVE_REALISTIC,
        oor_hold_grace_hours: int = 0,
        oor_hold_penalty_usd: float = 0.0,
        profitable_start_prob: float = 0.0,
        profitable_start_indices: Optional[Sequence[int]] = None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.randomize_start = randomize_start
        self.min_episode_hours = max(int(min_episode_hours), 1)
        self.max_episode_hours = (
            self.min_episode_hours
            if max_episode_hours is None
            else max(int(max_episode_hours), self.min_episode_hours)
        )
        self.oor_start_prob = float(np.clip(oor_start_prob, 0.0, 1.0))
        if oor_start_mode not in {"historical", "synthetic"}:
            raise ValueError("oor_start_mode must be 'historical' or 'synthetic'")
        self.oor_start_mode = oor_start_mode
        if oor_recenter_mode not in {OOR_RECENTER_REQUESTED, OOR_RECENTER_SAME}:
            raise ValueError("oor_recenter_mode must be 'requested_width' or 'same_width'")
        self.oor_recenter_mode = oor_recenter_mode
        self.action_widths = tuple(int(w) for w in action_widths)
        if not self.action_widths:
            raise ValueError("action_widths must contain at least one width")
        if reward_mode not in {"total", "per_decision_hour"}:
            raise ValueError("reward_mode must be 'total' or 'per_decision_hour'")
        if training_objective not in {
            TRAINING_OBJECTIVE_REALISTIC,
            TRAINING_OBJECTIVE_FEE_TX_SHAPED,
        }:
            raise ValueError(
                "training_objective must be 'realistic' or 'fee_tx_shaped'"
            )
        self.oor_hold_grace_hours = max(int(oor_hold_grace_hours), 0)
        self.oor_hold_penalty_usd = max(float(oor_hold_penalty_usd), 0.0)
        self.profitable_start_prob = float(np.clip(profitable_start_prob, 0.0, 1.0))
        self.profitable_start_indices = tuple(
            sorted(
                {
                    int(idx)
                    for idx in (profitable_start_indices or ())
                    if 0 <= int(idx) < self.n_steps
                }
            )
        )
        self.reward_mode = reward_mode
        self.training_objective = training_objective
        self._base_action_space = spaces.Discrete(10)
        self.base_state_dim = int(self.state_dim)
        self.candidate_entry_feature_dim = 2 * len(self.action_widths)
        self.state_dim = self.base_state_dim + self.candidate_entry_feature_dim
        self.observation_space = spaces.Box(
            low=-np.inf,
            high=np.inf,
            shape=(self.state_dim,),
            dtype=np.float32,
        )
        self.action_space = spaces.Discrete(cash_oor_num_actions(self.action_widths))
        self._episode_end_idx = self.n_steps

    def _step_base_action(self, env_action: int):
        current_action_space = self.action_space
        self.action_space = self._base_action_space
        try:
            return super().step(env_action)
        finally:
            self.action_space = current_action_space

    def _zero_components(self) -> dict:
        return {
            "lp_value_change_usd": 0.0,
            "hedge_pnl_usd": 0.0,
            "swing_pnl_usd": 0.0,
            "raw_lp_value_change_usd": 0.0,
            "raw_hedge_pnl_usd": 0.0,
            "raw_swing_pnl_usd": 0.0,
            "raw_boundary_il_usd": 0.0,
            "realized_boundary_pnl_usd": 0.0,
            "pending_boundary_pnl_usd": 0.0,
            "fee_usd": 0.0,
            "funding_cost_usd": 0.0,
            "hedged_core_pnl_usd": 0.0,
            "gross_fee_carry_usd": 0.0,
            "net_before_tx_usd": 0.0,
            "net_after_tx_usd": 0.0,
            "tx_cost_usd": 0.0,
            "swap_fee_cost_usd": 0.0,
            "mev_cost_usd": 0.0,
            "reward_usd": 0.0,
        }

    def _add_components(self, totals: dict, info: dict) -> None:
        for key in ADDITIVE_COMPONENT_KEYS:
            totals[key] += float(info.get(key, 0.0))
        totals["pending_boundary_pnl_usd"] = float(info.get("pending_boundary_pnl_usd", 0.0))
        totals["raw_boundary_il_usd"] = float(info.get("raw_boundary_il_usd", 0.0))

    def _merge_component_totals(self, totals: dict, updates: dict) -> None:
        for key in ADDITIVE_COMPONENT_KEYS:
            totals[key] += float(updates.get(key, 0.0))
        totals["pending_boundary_pnl_usd"] = float(
            updates.get("pending_boundary_pnl_usd", totals["pending_boundary_pnl_usd"])
        )
        totals["raw_boundary_il_usd"] = float(
            updates.get("raw_boundary_il_usd", totals["raw_boundary_il_usd"])
        )

    def _current_state(self) -> str:
        if self.idx >= min(self.n_steps, self._episode_end_idx):
            return "terminal"
        return self._position_state(self._get_price(self.timestamps[self.idx]))

    def _sample_episode_horizon(self) -> int:
        if not self.randomize_start:
            return self.n_steps
        if self.max_episode_hours <= self.min_episode_hours:
            return self.min_episode_hours
        return int(self.np_random.integers(self.min_episode_hours, self.max_episode_hours + 1))

    def _set_episode_window(self, start_idx: int) -> None:
        horizon = self._sample_episode_horizon()
        self._episode_end_idx = min(self.n_steps, int(start_idx) + int(horizon))

    def _initialize_synthetic_oor_state(self) -> None:
        width = int(self.action_widths[int(self.np_random.integers(0, len(self.action_widths)))])
        current_price = self._get_price(self.timestamps[self.idx])
        half_width_ticks = (width * self.tick_spacing) / 2.0
        half_width_frac = math.exp(half_width_ticks * math.log(1.0001)) - 1.0
        direction = 1.0 if float(self.np_random.random()) < 0.5 else -1.0
        center_price = current_price / max(1.0 + direction * half_width_frac * 1.4, 1e-6)
        self._open_position(self.initial_capital, center_price, width)
        max_age = max(min(self.idx, self.max_episode_hours), 1)
        age = int(self.np_random.integers(1, max_age + 1))
        self.position_entry_idx = max(0, self.idx - age)

    def _initialize_historical_oor_state(self, target_idx: int, max_attempts: int = 32) -> bool:
        """
        Build an OOR state by replaying a historical LP path into the target hour.

        This exposes the agent to OOR situations that have already accrued the
        carry/swing path that led there, instead of synthetic "free" OOR states.
        """
        target_idx = int(target_idx)
        if target_idx <= 0:
            return False

        snapshot = self.get_state_snapshot()
        max_lookback = min(
            target_idx,
            max(self.max_episode_hours * 2, self.min_episode_hours),
        )
        if max_lookback <= 0:
            return False

        for _ in range(max_attempts):
            width = int(self.action_widths[int(self.np_random.integers(0, len(self.action_widths)))])
            lookback = int(self.np_random.integers(1, max_lookback + 1))
            entry_idx = max(0, target_idx - lookback)

            self.load_state_snapshot(snapshot)
            self.idx = entry_idx
            self._set_cash_state(self.initial_capital)
            entry_price = self._get_price(self.timestamps[self.idx])
            if not self._open_position(self.initial_capital, entry_price, width):
                continue

            terminated = False
            while self.idx < target_idx:
                _, _, terminated, _, _ = self._step_base_action(HOLD_ACTION)
                if terminated:
                    break

            if terminated or self.idx != target_idx:
                continue

            current_price = self._get_price(self.timestamps[self.idx])
            if self._position_state(current_price) != "lp_oor":
                continue
            if self.position_entry_idx >= self.idx:
                continue
            return True

        self.load_state_snapshot(snapshot)
        return False

    def _roll_in_range_until_boundary(self) -> dict:
        totals = self._zero_components()
        hours = 0
        while self.idx < min(self.n_steps, self._episode_end_idx):
            state = self._current_state()
            if state != "lp_in_range":
                return {
                    "terminated": False,
                    "hours": hours,
                    "next_decision_state": state,
                    "components": totals,
                }
            _, _, terminated, _, info = self._step_base_action(HOLD_ACTION)
            self._add_components(totals, info)
            hours += 1
            if terminated:
                return {
                    "terminated": True,
                    "hours": hours,
                    "next_decision_state": "terminal",
                    "components": totals,
                }
        return {
            "terminated": True,
            "hours": hours,
            "next_decision_state": "terminal",
            "components": totals,
        }

    def _get_obs(self):
        if self.idx >= len(self.timestamps):
            return np.zeros(self.state_dim, dtype=np.float32)
        base_obs = UniswapV3HedgedFeeEnv._get_obs(self)
        full_features = self.hourly_data.features.get(
            self.timestamps[self.idx], np.zeros(len(FEATURE_COLS), dtype=np.float32)
        )
        candidate_features = []
        for width in self.action_widths:
            hours_to_oor, fee_il_ratio = projected_entry_features_for_width(
                self,
                width=width,
                full_features=full_features,
            )
            candidate_features.extend([hours_to_oor, fee_il_ratio])
        return np.concatenate(
            [np.asarray(candidate_features, dtype=np.float32), base_obs]
        )

    def reset(self, seed=None, options=None):
        obs, info = super().reset(seed=seed, options=options)
        used_profitable_start = False
        if self.randomize_start and self.n_steps > self.min_episode_hours:
            max_start = max(self.n_steps - self.min_episode_hours, 0)
            eligible_profitable = [
                idx for idx in self.profitable_start_indices if idx <= max_start
            ]
            if (
                eligible_profitable
                and float(self.np_random.random()) < self.profitable_start_prob
            ):
                choice_idx = int(self.np_random.integers(0, len(eligible_profitable)))
                self.idx = int(eligible_profitable[choice_idx])
                used_profitable_start = True
            else:
                self.idx = int(self.np_random.integers(0, max_start + 1))
            self._set_cash_state(self.initial_capital)
        target_idx = int(self.idx)
        if (
            self.randomize_start
            and target_idx < self.n_steps
            and float(self.np_random.random()) < self.oor_start_prob
            and not used_profitable_start
        ):
            initialized = False
            if self.oor_start_mode == "historical":
                initialized = self._initialize_historical_oor_state(target_idx)
            if not initialized:
                self.idx = target_idx
                self._set_cash_state(self.initial_capital)
                self._initialize_synthetic_oor_state()
        self._set_episode_window(self.idx)
        obs = self._get_obs()
        info = {
            **info,
            "used_profitable_start": used_profitable_start,
            "profitable_start_prob": self.profitable_start_prob,
        }
        return obs, info

    def step(self, action):
        if self.idx >= min(self.n_steps, self._episode_end_idx):
            return self._get_obs(), 0.0, True, False, {"decision_state": "terminal"}

        action_int = int(action)
        if action_int < 0 or action_int >= cash_oor_num_actions(self.action_widths):
            raise ValueError(f"Cash/OOR action out of range: {action_int}")

        decision_state = self._current_state()
        if decision_state not in {"cash", "lp_oor"}:
            raise RuntimeError(
                f"Cash/OOR env must act on cash or OOR states, got {decision_state}"
            )
        hours_in_position_before = max(int(self.idx - self.position_entry_idx), 0)

        requested_width = cash_oor_action_to_width(action_int, self.action_widths)
        width = requested_width
        if decision_state == "cash":
            env_action = HOLD_ACTION if action_int < 2 else width_to_action(width)
        else:
            if action_int == CASH_OOR_HOLD_OR_STAY:
                env_action = HOLD_ACTION
            elif action_int == CASH_OOR_EXIT:
                env_action = GO_CASH_ACTION
            else:
                if (
                    self.oor_recenter_mode == OOR_RECENTER_SAME
                    and self.has_lp
                    and self.lp_width_ticks > 0
                ):
                    width = int(self.lp_width_ticks / self.tick_spacing)
                env_action = width_to_action(width)

        _, _, terminated, _, info = self._step_base_action(env_action)
        totals = self._zero_components()
        self._add_components(totals, info)
        total_hours = 1
        next_decision_state = self._current_state() if not terminated else "terminal"

        if not terminated and next_decision_state == "lp_in_range":
            roll = self._roll_in_range_until_boundary()
            self._merge_component_totals(totals, roll["components"])
            total_hours += int(roll["hours"])
            terminated = bool(roll["terminated"])
            next_decision_state = roll["next_decision_state"]

        reward_usd_total = float(totals["reward_usd"])
        oor_hold_penalty_applied = 0.0
        if self.training_objective == TRAINING_OBJECTIVE_FEE_TX_SHAPED:
            reward_usd_total = float(totals["fee_usd"] - totals["tx_cost_usd"])
            if (
                decision_state == "lp_oor"
                and info["effective_action"] == "hold_oor"
                and hours_in_position_before >= self.oor_hold_grace_hours
            ):
                oor_hold_penalty_applied = float(self.oor_hold_penalty_usd)
                reward_usd_total -= oor_hold_penalty_applied
        training_reward_usd = (
            reward_usd_total
            if self.reward_mode == "total"
            else reward_usd_total / max(float(total_hours), 1.0)
        )
        reward = float(training_reward_usd / self._reward_denom())
        info_out = {
            "decision_state": decision_state,
            "requested_width": requested_width,
            "selected_width": width,
            "cash_oor_action": action_int,
            "cash_oor_action_label": cash_oor_action_label(action_int, decision_state, self.action_widths),
            "cash_oor_effective_action_label": (
                "recenter_same_width"
                if (
                    decision_state == "lp_oor"
                    and action_int >= 2
                    and self.oor_recenter_mode == OOR_RECENTER_SAME
                )
                else cash_oor_action_label(action_int, decision_state, self.action_widths)
            ),
            "effective_action": info["effective_action"],
            "stint_hours": total_hours,
            "next_decision_state": next_decision_state,
            "next_position_state": info.get("next_position_state", next_decision_state),
            "reward_mode": self.reward_mode,
            "training_objective": self.training_objective,
            "oor_recenter_mode": self.oor_recenter_mode,
            "oor_hold_grace_hours": self.oor_hold_grace_hours,
            "oor_hold_penalty_usd": self.oor_hold_penalty_usd,
            "oor_hold_penalty_applied_usd": oor_hold_penalty_applied,
            "episode_end_idx": int(self._episode_end_idx),
            "action_widths": self.action_widths,
            "training_reward_usd": training_reward_usd,
            "hedge_accounting_mode": self.hedge_accounting_mode,
            "used_profitable_start": False,
            "portfolio_value": self.get_portfolio_value(),
            "reward": reward,
            **totals,
        }
        return self._get_obs(), reward, terminated, False, info_out


class UniswapV3HedgedInRangeEnv(UniswapV3HedgedFeeEnv):
    """In-range DQN env: decide hold vs exit while boundary policy handles cash/OOR."""

    def __init__(
        self,
        *args,
        boundary_policy,
        randomize_start: bool = False,
        min_episode_hours: int = 500,
        max_reset_attempts: int = 32,
        reward_mode: str = "per_decision_hour",
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.boundary_policy = boundary_policy
        self.randomize_start = randomize_start
        self.min_episode_hours = max(int(min_episode_hours), 1)
        self.max_reset_attempts = max(int(max_reset_attempts), 1)
        if reward_mode not in {"total", "per_decision_hour"}:
            raise ValueError("reward_mode must be 'total' or 'per_decision_hour'")
        self.reward_mode = reward_mode
        self._base_action_space = spaces.Discrete(10)
        self.action_space = spaces.Discrete(2)
        self._terminal_after_reset = False

    def _step_base_action(self, env_action: int):
        current_action_space = self.action_space
        self.action_space = self._base_action_space
        try:
            return super().step(env_action)
        finally:
            self.action_space = current_action_space

    def _zero_components(self) -> dict:
        return {
            "lp_value_change_usd": 0.0,
            "hedge_pnl_usd": 0.0,
            "swing_pnl_usd": 0.0,
            "raw_lp_value_change_usd": 0.0,
            "raw_hedge_pnl_usd": 0.0,
            "raw_swing_pnl_usd": 0.0,
            "raw_boundary_il_usd": 0.0,
            "realized_boundary_pnl_usd": 0.0,
            "pending_boundary_pnl_usd": 0.0,
            "fee_usd": 0.0,
            "funding_cost_usd": 0.0,
            "hedged_core_pnl_usd": 0.0,
            "gross_fee_carry_usd": 0.0,
            "net_before_tx_usd": 0.0,
            "net_after_tx_usd": 0.0,
            "tx_cost_usd": 0.0,
            "swap_fee_cost_usd": 0.0,
            "mev_cost_usd": 0.0,
            "reward_usd": 0.0,
        }

    def _add_components(self, totals: dict, info: dict) -> None:
        for key in ADDITIVE_COMPONENT_KEYS:
            totals[key] += float(info.get(key, 0.0))
        totals["pending_boundary_pnl_usd"] = float(info.get("pending_boundary_pnl_usd", 0.0))
        totals["raw_boundary_il_usd"] = float(info.get("raw_boundary_il_usd", 0.0))

    def _merge_component_totals(self, totals: dict, updates: dict) -> None:
        for key in ADDITIVE_COMPONENT_KEYS:
            totals[key] += float(updates.get(key, 0.0))
        totals["pending_boundary_pnl_usd"] = float(
            updates.get("pending_boundary_pnl_usd", totals["pending_boundary_pnl_usd"])
        )
        totals["raw_boundary_il_usd"] = float(
            updates.get("raw_boundary_il_usd", totals["raw_boundary_il_usd"])
        )

    def _current_state(self) -> str:
        if self.idx >= self.n_steps:
            return "terminal"
        return self._position_state(self._get_price(self.timestamps[self.idx]))

    def _predict_boundary_action(self, obs: np.ndarray) -> int:
        prediction = self.boundary_policy.predict(obs, return_q=False)
        if hasattr(prediction, "value"):
            return int(prediction.value)
        if isinstance(prediction, tuple):
            return int(prediction[0])
        return int(prediction)

    def _fast_forward_to_in_range(self) -> dict:
        totals = self._zero_components()
        hours = 0
        while self.idx < self.n_steps:
            state = self._current_state()
            if state == "lp_in_range":
                return {
                    "terminated": False,
                    "hours": hours,
                    "next_decision_state": "lp_in_range",
                    "components": totals,
                }
            if state == "terminal":
                break
            obs = self._get_obs()
            boundary_action = self._predict_boundary_action(obs)
            width = boundary_action_to_width(boundary_action)
            if state == "cash":
                env_action = HOLD_ACTION if width == 0 else width_to_action(width)
            else:
                env_action = GO_CASH_ACTION if width == 0 else width_to_action(width)
            _, _, terminated, _, info = self._step_base_action(env_action)
            self._add_components(totals, info)
            hours += 1
            if terminated:
                return {
                    "terminated": True,
                    "hours": hours,
                    "next_decision_state": "terminal",
                    "components": totals,
                }
        return {
            "terminated": True,
            "hours": hours,
            "next_decision_state": "terminal",
            "components": totals,
        }

    def reset(self, seed=None, options=None):
        attempts = self.max_reset_attempts if self.randomize_start else 1
        self._terminal_after_reset = False
        for attempt in range(attempts):
            obs, info = super().reset(seed=seed if attempt == 0 else None, options=options)
            if self.randomize_start and self.n_steps > self.min_episode_hours:
                max_start = max(self.n_steps - self.min_episode_hours, 0)
                self.idx = int(self.np_random.integers(0, max_start + 1))
                self._set_cash_state(self.initial_capital)
            ff = self._fast_forward_to_in_range()
            if not ff["terminated"]:
                return self._get_obs(), ff
        self._terminal_after_reset = True
        raise RuntimeError("In-range env found no in-range decision point under boundary policy")

    def step(self, action):
        if self._terminal_after_reset or self.idx >= self.n_steps:
            return self._get_obs(), 0.0, True, False, {"decision_state": "terminal"}

        decision_state = self._current_state()
        if decision_state != "lp_in_range":
            raise RuntimeError(f"In-range env must act on lp_in_range, got {decision_state}")

        env_action = HOLD_ACTION if int(action) == IN_RANGE_HOLD else GO_CASH_ACTION
        _, _, terminated, _, info = self._step_base_action(env_action)
        totals = self._zero_components()
        self._add_components(totals, info)
        total_hours = 1
        next_decision_state = self._current_state() if not terminated else "terminal"

        if not terminated and next_decision_state != "lp_in_range":
            ff = self._fast_forward_to_in_range()
            self._merge_component_totals(totals, ff["components"])
            total_hours += int(ff["hours"])
            terminated = bool(ff["terminated"])
            next_decision_state = ff["next_decision_state"]

        reward_usd_total = float(totals["reward_usd"])
        training_reward_usd = (
            reward_usd_total
            if self.reward_mode == "total"
            else reward_usd_total / max(float(total_hours), 1.0)
        )
        reward = float(training_reward_usd / self._reward_denom())
        info_out = {
            "decision_state": decision_state,
            "in_range_action": int(action),
            "in_range_action_label": "hold" if int(action) == IN_RANGE_HOLD else "exit_to_cash",
            "stint_hours": total_hours,
            "next_decision_state": next_decision_state,
            "reward_mode": self.reward_mode,
            "training_reward_usd": training_reward_usd,
            "hedge_accounting_mode": self.hedge_accounting_mode,
            "portfolio_value": self.get_portfolio_value(),
            "reward": reward,
            **totals,
        }
        return self._get_obs(), reward, terminated, False, info_out
