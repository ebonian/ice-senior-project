"""
Hourly Uniswap v3 hedged fee extraction environment.

This variant supports three hedge-accounting modes:

  idealized_perfect:
    Live-trading approximation for a perfectly swing-neutral hedge. LP boundary
    IL is diagnostic-only. Reward and capital come from the combined LP+hedge
    book: fee minus funding minus transaction costs.

  continuous_delta_hedged:
    More realistic production approximation for a continuously delta-hedged LP
    book with no explicit hedge execution frictions. Reward and capital come
    from:

      fee + raw_swing_pnl - funding - transaction_costs

    where `raw_swing_pnl = lp_value_change + hedge_pnl` is the residual after
    an actively rehedged perp hedge along the intrahour swap path. Boundary IL
    remains diagnostic-only.

  legacy_boundary_il:
    Comparison mode that books boundary IL explicitly via
    `realized_boundary_pnl_usd`.

Price direction is therefore not a predictive feature. Under
`continuous_delta_hedged`, LP inventory swings are recognized through the
intrahour actively hedged residual path rather than a single hourly open/close
delta approximation.

Hourly decision problem:

  1. Should capital be in LP or cash right now?
  2. If entering/recentering, which width best monetizes current volatility?

Action space: Discrete(10)
  0 = HOLD / STAY_CASH
  1 = GO_CASH
  2..9 = ENTER / RECENTER at widths [W2, W4, W6, W10, W15, W20, W30, W40]

State-dependent action semantics:
  - CASH:        0/1 stay cash, 2..9 enter at selected width
  - LP in-range: 0 hold, 1 exit to cash, 2..9 alias to hold
  - LP OOR:      0 hold OOR, 1 exit to cash, 2..9 recenter at selected width

Reward is normalized by initial capital:

  idealized_perfect:
    reward = (fee - funding - tx_cost) / K0

  continuous_delta_hedged:
    reward = (fee + raw_swing_pnl - funding - tx_cost) / K0

  legacy_boundary_il:
    reward = (realized_boundary_pnl + fee - funding - tx_cost) / K0

where:
  - `fee - funding - tx_cost` is recognized immediately each hour
  - `realized_boundary_pnl` is zero on ordinary hold hours
  - `raw_boundary_il_usd` is always diagnostic-only
  - `pending_boundary_pnl` is only active in `legacy_boundary_il`
  - `raw_swing_pnl` is recognized directly only in `continuous_delta_hedged`

To keep reward timing consistent, every LP exposure action at index `idx`
earns the fee bucket for `idx + 1`, matching the price move from
`price[idx] -> price[idx + 1]`. This avoids overlapping fee attribution across
entry and subsequent hold steps.
"""

import math
from typing import Optional

import gymnasium as gym
import numpy as np
from gymnasium import spaces

from kongtrae.training.uniswap_v3_ppo_paper import (
    FEATURE_COLS,
    HourlyData,
    MAX_TICK,
    MIN_TICK,
    UniswapV3PaperEnv,
    price_to_tick,
    tick_to_price,
)

# Volatility-only feature set for a permanently hedged LP.
VOL_FEATURE_INDICES = [
    FEATURE_COLS.index("atr_14"),
    FEATURE_COLS.index("natr_14"),
    FEATURE_COLS.index("bb_width"),
    FEATURE_COLS.index("volume_sma_ratio"),
    FEATURE_COLS.index("adx_14"),
    FEATURE_COLS.index("vol_regime"),
]
N_VOL_FEATURES = len(VOL_FEATURE_INDICES)

# Width catalog. `0` is a sentinel only; it is not a width-selection action.
HEDGED_WIDTH_SET = [0, 2, 4, 6, 10, 15, 20, 30, 40]
ENTRY_WIDTHS = HEDGED_WIDTH_SET[1:]

HOLD_ACTION = 0
GO_CASH_ACTION = 1
N_POSITION_FEATURES = 12
HEDGE_ACCOUNTING_IDEALIZED = "idealized_perfect"
HEDGE_ACCOUNTING_CONTINUOUS = "continuous_delta_hedged"
HEDGE_ACCOUNTING_LEGACY = "legacy_boundary_il"
HEDGE_ACCOUNTING_DEFAULT = HEDGE_ACCOUNTING_CONTINUOUS
HEDGE_ACCOUNTING_MODES = (
    HEDGE_ACCOUNTING_IDEALIZED,
    HEDGE_ACCOUNTING_CONTINUOUS,
    HEDGE_ACCOUNTING_LEGACY,
)
TRAINING_REWARD_REALISTIC = "realistic"
TRAINING_REWARD_FEE_TX_PATIENCE = "fee_tx_patience_shaped"
TRAINING_REWARD_DEFAULT = TRAINING_REWARD_REALISTIC
TRAINING_REWARD_MODES = (
    TRAINING_REWARD_REALISTIC,
    TRAINING_REWARD_FEE_TX_PATIENCE,
)


def width_to_action(width: int) -> int:
    """Map a positive width to its discrete enter/recenter action id."""
    if width not in ENTRY_WIDTHS:
        raise ValueError(f"Width must be one of {ENTRY_WIDTHS}, got {width}")
    return HEDGED_WIDTH_SET.index(width) + 1


def action_to_width(action: int) -> int:
    """Map a discrete action id to width, returning 0 for non-width actions."""
    action_int = int(action)
    if action_int < 2:
        return 0
    if action_int > len(ENTRY_WIDTHS) + 1:
        raise ValueError(f"Action out of range: {action_int}")
    return HEDGED_WIDTH_SET[action_int - 1]


def action_to_label(action: int) -> str:
    """Human-readable label for requested actions."""
    action_int = int(action)
    if action_int == HOLD_ACTION:
        return "hold_or_stay_cash"
    if action_int == GO_CASH_ACTION:
        return "go_cash"
    return f"width_{action_to_width(action_int)}"


class UniswapV3HedgedFeeEnv(UniswapV3PaperEnv):
    """
    Hedged hourly LP environment with explicit cash state and width persistence.

    Observation (18-dim):
      6 vol features + 12 position features
      Position features:
        - width_normalized
        - in_range
        - dist_to_boundary_sigma
        - hours_since_rebalance
        - expected_hours_to_oor
        - fee_il_ratio
        - realized_vol_6h
        - intra_hour_rvol
        - book_capital_ratio
        - net_carry_ratio
        - time_in_range_last_hour
        - is_cash
    """

    metadata = {"render_modes": []}

    def __init__(
        self,
        hourly_data: HourlyData,
        initial_capital_usd: float = 1000.0,
        gas_cost_usd: float = 0.03,
        mev_slippage_pct: float = 0.0001,
        hedge_funding_rate_annual: float = 0.048,
        hedge_accounting_mode: str = HEDGE_ACCOUNTING_DEFAULT,
        training_reward_mode: str = TRAINING_REWARD_DEFAULT,
        fee_haircut: float = 1.0,
        active_liquidity_multiplier: float = 1.0,
        mode: str = "train",
        train_ratio: float = 0.8,
        val_ratio: float = 0.1,
        start_idx: Optional[int] = None,
        end_idx: Optional[int] = None,
    ):
        super().__init__(
            hourly_data=hourly_data,
            initial_capital_usd=initial_capital_usd,
            gas_cost_usd=gas_cost_usd,
            mev_slippage_pct=mev_slippage_pct,
            min_tick_width=1,
            max_tick_width=40,
            hold_threshold=0.5,
            burn_threshold=0.0,
            mode=mode,
            train_ratio=train_ratio,
            val_ratio=val_ratio,
            start_idx=start_idx,
            end_idx=end_idx,
            hedge_funding_rate_annual=hedge_funding_rate_annual,
            hedge_enabled=True,
            fee_haircut=fee_haircut,
            active_liquidity_multiplier=active_liquidity_multiplier,
        )
        if hedge_accounting_mode not in HEDGE_ACCOUNTING_MODES:
            raise ValueError(
                f"hedge_accounting_mode must be one of {HEDGE_ACCOUNTING_MODES}, "
                f"got {hedge_accounting_mode}"
            )
        if training_reward_mode not in TRAINING_REWARD_MODES:
            raise ValueError(
                f"training_reward_mode must be one of {TRAINING_REWARD_MODES}, "
                f"got {training_reward_mode}"
            )

        self.state_dim = N_VOL_FEATURES + N_POSITION_FEATURES
        self.observation_space = spaces.Box(
            low=-np.inf,
            high=np.inf,
            shape=(self.state_dim,),
            dtype=np.float32,
        )
        self.action_space = spaces.Discrete(10)
        self.is_cash = True
        self.hedge_accounting_mode = hedge_accounting_mode
        self.training_reward_mode = training_reward_mode

    def reset(self, seed=None, options=None):
        gym.Env.reset(self, seed=seed)
        self._reset_state()
        self._reset_boundary_ledgers()
        self.is_cash = True
        return self._get_obs(), {}

    def get_state_snapshot(self) -> dict:
        return {
            "idx": int(self.idx),
            "actual_capital": float(self.actual_capital),
            "is_cash": bool(self.is_cash),
            "has_lp": bool(self.has_lp),
            "liquidity": float(self.liquidity),
            "lp_lower_tick": self.lp_lower_tick,
            "lp_upper_tick": self.lp_upper_tick,
            "lp_width_ticks": int(self.lp_width_ticks),
            "entry_price": None if self.entry_price is None else float(self.entry_price),
            "initial_value_usd": None if self.initial_value_usd is None else float(self.initial_value_usd),
            "position_entry_idx": int(self.position_entry_idx),
            "accumulated_fees": float(self.accumulated_fees),
            "accumulated_swing_pnl": float(self.accumulated_swing_pnl),
            "pending_boundary_pnl": float(self.pending_boundary_pnl),
            "accrued_funding_cost": float(self.accrued_funding_cost),
            "cumulative_hedge_pnl": float(self.cumulative_hedge_pnl),
            "entry_reference_token0": float(self.entry_reference_token0),
            "entry_reference_token1": float(self.entry_reference_token1),
        }

    def load_state_snapshot(self, snapshot: dict) -> None:
        self.idx = int(snapshot["idx"])
        self.actual_capital = float(snapshot["actual_capital"])
        self.is_cash = bool(snapshot["is_cash"])
        self.has_lp = bool(snapshot["has_lp"])
        self.liquidity = float(snapshot["liquidity"])
        self.lp_lower_tick = snapshot["lp_lower_tick"]
        self.lp_upper_tick = snapshot["lp_upper_tick"]
        self.lp_width_ticks = int(snapshot["lp_width_ticks"])
        self.entry_price = snapshot["entry_price"]
        self.initial_value_usd = snapshot["initial_value_usd"]
        self.position_entry_idx = int(snapshot["position_entry_idx"])
        self.accumulated_fees = float(snapshot["accumulated_fees"])
        self.accumulated_swing_pnl = float(snapshot["accumulated_swing_pnl"])
        self.pending_boundary_pnl = float(snapshot["pending_boundary_pnl"])
        self.accrued_funding_cost = float(snapshot["accrued_funding_cost"])
        self.cumulative_hedge_pnl = float(snapshot["cumulative_hedge_pnl"])
        self.entry_reference_token0 = float(snapshot["entry_reference_token0"])
        self.entry_reference_token1 = float(snapshot["entry_reference_token1"])
        self._sync_hedge_ledger()

    def _reward_denom(self) -> float:
        return max(self.initial_capital, 1.0)

    def _uses_legacy_boundary_il(self) -> bool:
        return self.hedge_accounting_mode == HEDGE_ACCOUNTING_LEGACY

    def _uses_continuous_delta_hedged(self) -> bool:
        return self.hedge_accounting_mode == HEDGE_ACCOUNTING_CONTINUOUS

    def _reset_boundary_ledgers(self) -> None:
        self.accumulated_fees = 0.0
        self.accumulated_swing_pnl = 0.0
        self.pending_boundary_pnl = 0.0
        self.accrued_funding_cost = 0.0
        self.cumulative_hedge_pnl = 0.0
        self.entry_reference_token0 = 0.0
        self.entry_reference_token1 = 0.0

    def _lp_bounds_prices(self) -> tuple[float, float]:
        if self.lp_lower_tick is None or self.lp_upper_tick is None:
            raise RuntimeError("LP bounds requested without an active LP position")
        return tick_to_price(self.lp_lower_tick), tick_to_price(self.lp_upper_tick)

    def _sync_hedge_ledger(self) -> None:
        if self.hedge_enabled:
            recognized_swing = 0.0
            if self._uses_legacy_boundary_il():
                recognized_swing = float(self.pending_boundary_pnl)
            elif self._uses_continuous_delta_hedged():
                recognized_swing = float(self.accumulated_swing_pnl)
            self.cumulative_hedge_pnl = recognized_swing - float(self.accrued_funding_cost)
        else:
            self.cumulative_hedge_pnl = 0.0

    def _net_carry_value(self) -> float:
        return float(self.accumulated_fees - self.accrued_funding_cost)

    def _recognized_swing_value(self) -> float:
        if self._uses_continuous_delta_hedged():
            return float(self.accumulated_swing_pnl)
        return 0.0

    def _realized_book_value(self) -> float:
        if self.is_cash or not self.has_lp or self.lp_lower_tick is None:
            return self.actual_capital
        return max(
            self.actual_capital + self._net_carry_value() + self._recognized_swing_value(),
            0.0,
        )

    def _capital_if_closed_now(self, price: Optional[float] = None) -> float:
        if self.is_cash or not self.has_lp or self.lp_lower_tick is None:
            return self.actual_capital
        if self._uses_legacy_boundary_il():
            return max(self._realized_book_value() + self._current_boundary_pnl(price), 0.0)
        return self._realized_book_value()

    def _portfolio_value_at_price(self, price: float) -> float:
        return self._realized_book_value()

    def get_portfolio_value(self) -> float:
        return self._realized_book_value()

    def _position_state(self, price: float) -> str:
        if self.is_cash or not self.has_lp or self.lp_lower_tick is None:
            return "cash"
        lp_lower_price, lp_upper_price = self._lp_bounds_prices()
        return "lp_in_range" if lp_lower_price <= price <= lp_upper_price else "lp_oor"

    def _compute_token0_value_fraction(
        self,
        price: float,
        lower_price: float,
        upper_price: float,
        liquidity: float,
    ) -> float:
        """Token0 value fraction of an LP position at a given price."""
        if liquidity <= 0 or price <= 0:
            return 0.0
        if price <= lower_price:
            return 1.0
        if price >= upper_price:
            return 0.0

        sqrt_p = math.sqrt(price)
        sqrt_pl = math.sqrt(lower_price)
        sqrt_pu = math.sqrt(upper_price)
        amount0 = liquidity * (1.0 / sqrt_p - 1.0 / sqrt_pu)
        amount1 = liquidity * (sqrt_p - sqrt_pl)
        total_value = amount0 * price + amount1
        if total_value <= 0:
            return 0.0
        return min(max((amount0 * price) / total_value, 0.0), 1.0)

    def _compute_position_amounts(
        self,
        price: float,
        lower_price: float,
        upper_price: float,
        liquidity: float,
    ) -> tuple[float, float]:
        """Token amounts currently embedded in a v3 position."""
        if liquidity <= 0 or price <= 0:
            return 0.0, 0.0

        sqrt_p = math.sqrt(price)
        sqrt_pl = math.sqrt(lower_price)
        sqrt_pu = math.sqrt(upper_price)

        if price <= lower_price:
            return liquidity * (1.0 / sqrt_pl - 1.0 / sqrt_pu), 0.0
        if price >= upper_price:
            return 0.0, liquidity * (sqrt_pu - sqrt_pl)
        return (
            liquidity * (1.0 / sqrt_p - 1.0 / sqrt_pu),
            liquidity * (sqrt_p - sqrt_pl),
        )

    def _current_boundary_pnl(self, price: Optional[float] = None) -> float:
        """
        Current unrealized boundary PnL if the active LP were closed now.

        This is the LP value minus the value of the entry inventory benchmark,
        both evaluated at the same current price.
        """
        if self.is_cash or not self.has_lp or self.lp_lower_tick is None or self.liquidity <= 0:
            return 0.0
        if price is None:
            if self.idx < len(self.timestamps):
                price = self._get_price(self.timestamps[self.idx])
            else:
                price = self.entry_price
        if price is None or price <= 0:
            return 0.0

        lower_price, upper_price = self._lp_bounds_prices()
        lp_value = self._compute_position_value(price, lower_price, upper_price, self.liquidity)
        entry_inventory_value = (
            float(self.entry_reference_token0) * price + float(self.entry_reference_token1)
        )
        return float(lp_value - entry_inventory_value)

    def _refresh_pending_boundary(self, price: Optional[float] = None) -> float:
        if self._uses_legacy_boundary_il():
            self.pending_boundary_pnl = float(self._current_boundary_pnl(price))
        else:
            self.pending_boundary_pnl = 0.0
        self._sync_hedge_ledger()
        return float(self.pending_boundary_pnl)

    def _compute_exit_swap_fraction(self, price: float) -> float:
        """Fraction of LP notional that must be swapped into cash on exit."""
        if self.is_cash or not self.has_lp or self.lp_lower_tick is None:
            return 0.0
        lp_lower_price, lp_upper_price = self._lp_bounds_prices()
        return self._compute_token0_value_fraction(
            price, lp_lower_price, lp_upper_price, self.liquidity
        )

    def _compute_trade_costs(self, notional: float, swap_frac: float) -> tuple[float, float, float]:
        """Gas + swap fee + MEV/slippage cost for a trade."""
        capped_swap_frac = min(max(float(swap_frac), 0.0), 1.0)
        base_notional = max(float(notional), 0.0)
        swap_fee_cost = capped_swap_frac * self.pool_fee * base_notional
        mev_cost = capped_swap_frac * self.mev_slippage_pct * base_notional
        tx_cost = self.gas_cost_usd + swap_fee_cost + mev_cost
        return tx_cost, swap_fee_cost, mev_cost

    def _set_cash_state(self, capital: float):
        self.actual_capital = max(float(capital), 0.0)
        self.is_cash = True
        self.has_lp = False
        self.liquidity = 0.0
        self.lp_lower_tick = None
        self.lp_upper_tick = None
        self.lp_width_ticks = 0
        self.entry_price = None
        self.initial_value_usd = None
        self.position_entry_idx = self.idx
        self._reset_boundary_ledgers()

    def _open_position(self, deployable_capital: float, price: float, width: int) -> bool:
        """Open a fresh LP position at the current price."""
        if deployable_capital <= 0 or price <= 0 or width not in ENTRY_WIDTHS:
            self._set_cash_state(deployable_capital)
            return False

        lower_tick, upper_tick = self._compute_position_bounds(price, width)
        lower_price = tick_to_price(lower_tick)
        upper_price = tick_to_price(upper_tick)
        value_per_L = self._compute_value_per_L(price, lower_price, upper_price)
        if value_per_L <= 0:
            self._set_cash_state(deployable_capital)
            return False

        self.actual_capital = float(deployable_capital)
        self.is_cash = False
        self.has_lp = True
        self.liquidity = self.actual_capital / value_per_L
        self.lp_lower_tick = lower_tick
        self.lp_upper_tick = upper_tick
        self.lp_width_ticks = width * self.tick_spacing
        self.entry_price = price
        self.initial_value_usd = self.actual_capital
        self.position_entry_idx = self.idx
        self._reset_boundary_ledgers()
        self.entry_reference_token0, self.entry_reference_token1 = self._compute_position_amounts(
            price, lower_price, upper_price, self.liquidity
        )
        return True

    def _with_pnl_breakdown(self, components: dict) -> dict:
        """Attach reward-facing and diagnostic hedge-accounting fields."""
        enriched = dict(components)
        raw_lp_value_change = float(
            enriched.get("raw_lp_value_change_usd", enriched.get("lp_value_change_usd", 0.0))
        )
        raw_hedge_pnl = float(
            enriched.get("raw_hedge_pnl_usd", enriched.get("hedge_pnl_usd", 0.0))
        )
        raw_swing_pnl = float(
            enriched.get(
                "raw_swing_pnl_usd",
                raw_lp_value_change + raw_hedge_pnl,
            )
        )
        raw_boundary_il = float(
            enriched.get(
                "raw_boundary_il_usd",
                enriched.get("pending_boundary_pnl_usd", 0.0),
            )
        )
        realized_boundary = float(enriched.get("realized_boundary_pnl_usd", 0.0))
        pending_boundary = float(enriched.get("pending_boundary_pnl_usd", 0.0))
        fee = float(enriched.get("fee_usd", 0.0))
        funding_cost = float(enriched.get("funding_cost_usd", 0.0))
        tx_cost = float(enriched.get("tx_cost_usd", 0.0))
        gross_fee_carry = fee - funding_cost - tx_cost

        if self._uses_legacy_boundary_il():
            hedged_core_pnl = realized_boundary - funding_cost
            net_before_tx = hedged_core_pnl + fee
            net_after_tx = net_before_tx - tx_cost
        elif self._uses_continuous_delta_hedged():
            realized_boundary = 0.0
            pending_boundary = 0.0
            hedged_core_pnl = raw_swing_pnl - funding_cost
            net_before_tx = hedged_core_pnl + fee
            net_after_tx = net_before_tx - tx_cost
        else:
            realized_boundary = 0.0
            pending_boundary = 0.0
            hedged_core_pnl = -funding_cost
            net_before_tx = fee - funding_cost
            net_after_tx = gross_fee_carry

        enriched["raw_lp_value_change_usd"] = raw_lp_value_change
        enriched["raw_hedge_pnl_usd"] = raw_hedge_pnl
        enriched["raw_swing_pnl_usd"] = raw_swing_pnl
        enriched["raw_boundary_il_usd"] = raw_boundary_il
        if self._uses_legacy_boundary_il() or self._uses_continuous_delta_hedged():
            enriched["lp_value_change_usd"] = raw_lp_value_change
            enriched["hedge_pnl_usd"] = raw_hedge_pnl
            enriched["swing_pnl_usd"] = raw_swing_pnl
        else:
            enriched["lp_value_change_usd"] = 0.0
            enriched["hedge_pnl_usd"] = 0.0
            enriched["swing_pnl_usd"] = 0.0
        enriched["realized_boundary_pnl_usd"] = realized_boundary
        enriched["pending_boundary_pnl_usd"] = pending_boundary
        enriched["hedged_core_pnl_usd"] = float(hedged_core_pnl)
        enriched["gross_fee_carry_usd"] = float(gross_fee_carry)
        enriched["net_before_tx_usd"] = float(net_before_tx)
        enriched["net_after_tx_usd"] = float(net_after_tx)
        enriched["reward_usd"] = float(net_after_tx)
        return enriched

    def _compute_lp_hour_raw(self, price_t0: float, price_t1: float) -> dict:
        if self.is_cash or not self.has_lp or self.lp_lower_tick is None or self.liquidity <= 0:
            return {
                "lp_value_change_usd": 0.0,
                "hedge_pnl_usd": 0.0,
                "swing_pnl_usd": 0.0,
                "fee_usd": 0.0,
                "funding_cost_usd": 0.0,
            }

        lp_lower_price, lp_upper_price = self._lp_bounds_prices()
        fee_hour_idx = min(self.idx + 1, len(self.timestamps) - 1)
        fee = self._compute_fee(
            price_t0,
            price_t1,
            self.liquidity,
            lp_lower_price,
            lp_upper_price,
            fee_hour_idx=fee_hour_idx,
        )
        value_t0 = self._compute_position_value(
            price_t0, lp_lower_price, lp_upper_price, self.liquidity
        )
        value_t1 = self._compute_position_value(
            price_t1, lp_lower_price, lp_upper_price, self.liquidity
        )
        lp_value_change = value_t1 - value_t0
        hedge_pnl, funding_cost = self._compute_active_hedge_hour(
            price_t0=price_t0,
            price_t1=price_t1,
            lower_price=lp_lower_price,
            upper_price=lp_upper_price,
            liquidity=self.liquidity,
            hedge_hour_idx=fee_hour_idx,
        )
        return {
            "lp_value_change_usd": float(lp_value_change),
            "hedge_pnl_usd": float(hedge_pnl),
            "swing_pnl_usd": float(lp_value_change + hedge_pnl),
            "fee_usd": float(fee),
            "funding_cost_usd": float(funding_cost),
        }

    def _compute_active_hedge_hour(
        self,
        price_t0: float,
        price_t1: float,
        lower_price: float,
        upper_price: float,
        liquidity: float,
        hedge_hour_idx: Optional[int] = None,
    ) -> tuple[float, float]:
        """Approximate an actively rehedged perp hedge over the observed swap path."""
        hour_idx = hedge_hour_idx if hedge_hour_idx is not None else self.idx
        t_hour = self.timestamps[hour_idx]
        swap_prices = (
            self.hourly_data.swap_prices_per_hour.get(t_hour, None)
            if self.hourly_data.swap_prices_per_hour is not None
            else None
        )
        swap_times = (
            self.hourly_data.swap_time_seconds_per_hour.get(t_hour, None)
            if getattr(self.hourly_data, "swap_time_seconds_per_hour", None) is not None
            else None
        )

        if swap_prices is None or len(swap_prices) == 0:
            return self._compute_hour_hedge(
                price_t0, price_t1, lower_price, upper_price, liquidity
            )

        lower_tick = price_to_tick(lower_price)
        upper_tick = price_to_tick(upper_price)
        key = (int(hour_idx), int(lower_tick), int(upper_tick))
        cache = self.hourly_data._active_hedge_cache
        cached = cache.get(key)

        if cached is None:
            hedge_pnl_per_l = 0.0
            funding_per_l = 0.0
            prev_price = float(price_t0)
            prev_time_seconds = 0.0
            period_seconds = float(getattr(self.hourly_data, "period_seconds", 3600.0))

            for j, swap_price in enumerate(np.asarray(swap_prices, dtype=np.float64)):
                cur_price = float(swap_price)
                delta_unit = self._compute_lp_delta(prev_price, lower_price, upper_price, 1.0)
                hedge_pnl_per_l += -delta_unit * (cur_price - prev_price)

                if self.hedge_enabled and swap_times is not None and j < len(swap_times):
                    cur_time_seconds = float(
                        min(max(swap_times[j], prev_time_seconds), period_seconds)
                    )
                    dt_hours = max(cur_time_seconds - prev_time_seconds, 0.0) / 3600.0
                    funding_per_l += abs(delta_unit * prev_price) * self._funding_hr * dt_hours
                    prev_time_seconds = cur_time_seconds

                prev_price = cur_price

            if self.hedge_enabled:
                if swap_times is not None:
                    delta_unit = self._compute_lp_delta(prev_price, lower_price, upper_price, 1.0)
                    dt_hours = max(period_seconds - prev_time_seconds, 0.0) / 3600.0
                    funding_per_l += abs(delta_unit * prev_price) * self._funding_hr * dt_hours
                else:
                    open_delta_unit = self._compute_lp_delta(price_t0, lower_price, upper_price, 1.0)
                    funding_per_l = (
                        abs(open_delta_unit * price_t0)
                        * self._funding_hr
                        * (period_seconds / 3600.0)
                    )

            cached = (float(hedge_pnl_per_l), float(funding_per_l))
            cache[key] = cached

        hedge_pnl_per_l, funding_per_l = cached
        return float(liquidity * hedge_pnl_per_l), float(liquidity * funding_per_l)

    def _apply_lp_hour_flows(self, raw_components: dict, price_t1: float) -> float:
        self.accumulated_fees += float(raw_components.get("fee_usd", 0.0))
        if self._uses_continuous_delta_hedged():
            self.accumulated_swing_pnl += float(raw_components.get("swing_pnl_usd", 0.0))
        self.accrued_funding_cost += float(raw_components.get("funding_cost_usd", 0.0))
        self._sync_hedge_ledger()
        return self._refresh_pending_boundary(price_t1)

    def _lp_hour_components(self, price_t0: float, price_t1: float) -> dict:
        """Apply one LP hour under the selected hedge-accounting mode."""
        raw = self._compute_lp_hour_raw(price_t0, price_t1)
        pending_boundary = self._apply_lp_hour_flows(raw, price_t1)
        return self._with_pnl_breakdown(
            {
                "lp_value_change_usd": raw["lp_value_change_usd"],
                "hedge_pnl_usd": raw["hedge_pnl_usd"],
                "swing_pnl_usd": raw["swing_pnl_usd"],
                "raw_boundary_il_usd": float(self._current_boundary_pnl(price_t1)),
                "realized_boundary_pnl_usd": 0.0,
                "pending_boundary_pnl_usd": float(pending_boundary),
                "fee_usd": raw["fee_usd"],
                "funding_cost_usd": raw["funding_cost_usd"],
                "tx_cost_usd": 0.0,
                "swap_fee_cost_usd": 0.0,
                "mev_cost_usd": 0.0,
            }
        )

    def _training_reward_usd(
        self,
        position_state: str,
        effective_action: str,
        components: dict,
    ) -> float:
        if self.training_reward_mode == TRAINING_REWARD_REALISTIC:
            return float(components.get("reward_usd", 0.0))

        fee_usd = float(components.get("fee_usd", 0.0))
        tx_cost_usd = float(components.get("tx_cost_usd", 0.0))

        if effective_action == "hold" and position_state == "lp_in_range":
            return fee_usd
        if effective_action == "hold_oor":
            return 0.0
        if effective_action == "stay_cash":
            return 0.0
        if effective_action.startswith(("enter_w", "recenter_w", "recenter_same")):
            return fee_usd - tx_cost_usd
        if effective_action == "exit_to_cash":
            return -tx_cost_usd
        return 0.0

    def _enter_or_recenter_components(
        self,
        price_t0: float,
        price_t1: float,
        target_width: int,
        capital_before_cost: float,
        swap_frac: float,
        realized_boundary_pnl: float = 0.0,
        raw_boundary_il_usd: Optional[float] = None,
    ) -> dict:
        """Open/recenter a position and score the immediately following hour."""
        tx_cost, swap_fee_cost, mev_cost = self._compute_trade_costs(
            capital_before_cost, swap_frac
        )
        deployable_capital = max(capital_before_cost - tx_cost, 0.0)
        opened = self._open_position(deployable_capital, price_t0, target_width)

        components = {
            "lp_value_change_usd": 0.0,
            "hedge_pnl_usd": 0.0,
            "swing_pnl_usd": 0.0,
            "raw_boundary_il_usd": float(raw_boundary_il_usd or 0.0),
            "realized_boundary_pnl_usd": float(realized_boundary_pnl),
            "pending_boundary_pnl_usd": 0.0,
            "fee_usd": 0.0,
            "funding_cost_usd": 0.0,
            "tx_cost_usd": float(tx_cost),
            "swap_fee_cost_usd": float(swap_fee_cost),
            "mev_cost_usd": float(mev_cost),
        }
        if opened:
            lp_components = self._lp_hour_components(price_t0, price_t1)
            for key in (
                "lp_value_change_usd",
                "hedge_pnl_usd",
                "swing_pnl_usd",
                "fee_usd",
                "funding_cost_usd",
                "pending_boundary_pnl_usd",
            ):
                components[key] = lp_components[key]
            if raw_boundary_il_usd is None:
                components["raw_boundary_il_usd"] = lp_components["raw_boundary_il_usd"]
        return self._with_pnl_breakdown(components)

    def _get_obs(self):
        if self.idx >= len(self.timestamps):
            return np.zeros(self.state_dim, dtype=np.float32)

        t = self.timestamps[self.idx]
        price = self._get_price(t)
        full_features = self.hourly_data.features.get(
            t, np.zeros(len(FEATURE_COLS), dtype=np.float32)
        )
        vol_features = np.array(
            [full_features[i] for i in VOL_FEATURE_INDICES],
            dtype=np.float32,
        )

        natr = float(full_features[FEATURE_COLS.index("natr_14")])
        sigma_period = max(natr, 1e-6)
        period_hours = float(getattr(self, "period_hours", 1.0))
        periods_per_hour = float(getattr(self, "periods_per_hour", 1.0))
        position_state = self._position_state(price)
        is_cash = 1.0 if position_state == "cash" else 0.0

        if position_state != "cash" and self.lp_lower_tick is not None:
            lp_lower_price, lp_upper_price = self._lp_bounds_prices()
            in_range = 1.0 if position_state == "lp_in_range" else 0.0
            width_normalized = self.lp_width_ticks / (40 * self.tick_spacing)

            tick = price_to_tick(price)
            if in_range > 0.5:
                dist_ticks = min(
                    abs(tick - self.lp_lower_tick),
                    abs(self.lp_upper_tick - tick),
                )
                dist_sigma = (dist_ticks * 0.0001) / sigma_period
                dist_to_boundary_sigma = min(5.0, dist_sigma)
            else:
                if tick < self.lp_lower_tick:
                    dist_ticks = self.lp_lower_tick - tick
                else:
                    dist_ticks = tick - self.lp_upper_tick
                dist_sigma = (dist_ticks * 0.0001) / sigma_period
                dist_to_boundary_sigma = -min(5.0, dist_sigma)

            half_width_frac = math.exp((self.lp_width_ticks / 2) * math.log(1.0001)) - 1.0
            sigma_actual = sigma_period / 1.3
            expected_periods_to_oor = (half_width_frac ** 2) / max(sigma_actual ** 2, 1e-12)
            expected_hours_to_oor = expected_periods_to_oor * period_hours
            expected_hours_to_oor = min(expected_hours_to_oor, 500.0)

            vol_sma = float(full_features[FEATURE_COLS.index("volume_sma_ratio")])
            fee_il_ratio = min(
                10.0,
                vol_sma * self.pool_fee / max(sigma_period ** 2 * max(width_normalized, 0.01), 1e-10),
            )
            hours = (self.idx - self.position_entry_idx) * period_hours
            hours_since_rebalance = math.log1p(max(hours, 0)) / math.log(169.0)

            book_capital_ratio = self.get_portfolio_value() / max(self.initial_capital, 1.0)
            net_carry_ratio = self._net_carry_value() / max(self.initial_capital, 1.0)

            time_in_range = 0.0
            if self.hourly_data.swap_ticks_per_hour is not None and self.idx > 0:
                t_prev = self.timestamps[self.idx - 1]
                prev_ticks = self.hourly_data.swap_ticks_per_hour.get(t_prev, None)
                if prev_ticks is not None and len(prev_ticks) > 0:
                    time_in_range = float(
                        np.mean(
                            (prev_ticks >= self.lp_lower_tick)
                            & (prev_ticks <= self.lp_upper_tick)
                        )
                    )
        else:
            width_normalized = 0.0
            in_range = 0.0
            dist_to_boundary_sigma = 0.0
            expected_hours_to_oor = 0.0
            fee_il_ratio = 0.0
            hours_since_rebalance = 0.0
            book_capital_ratio = self.get_portfolio_value() / max(self.initial_capital, 1.0)
            net_carry_ratio = 0.0
            time_in_range = 0.0

        lookback_steps = max(int(round(6 * periods_per_hour)), 1)
        if self.idx >= lookback_steps:
            recent_returns = []
            for j in range(1, lookback_steps + 1):
                p_prev = self._get_price(self.timestamps[self.idx - j])
                p_cur = self._get_price(self.timestamps[self.idx - j + 1])
                if p_prev > 0:
                    recent_returns.append((p_cur - p_prev) / p_prev)
            realized_vol_6h = float(np.std(recent_returns)) if recent_returns else 0.0
        else:
            realized_vol_6h = 0.0

        if self.hourly_data.hourly_high is not None and self.hourly_data.hourly_low is not None:
            high = self.hourly_data.hourly_high.get(t, price)
            low = self.hourly_data.hourly_low.get(t, price)
            intra_hour_rvol = (high - low) / max(price, 1e-10)
        else:
            intra_hour_rvol = 0.0

        position_features = np.array(
            [
                width_normalized,
                in_range,
                dist_to_boundary_sigma,
                hours_since_rebalance,
                expected_hours_to_oor / 100.0,
                fee_il_ratio,
                realized_vol_6h,
                intra_hour_rvol,
                book_capital_ratio,
                net_carry_ratio,
                time_in_range,
                is_cash,
            ],
            dtype=np.float32,
        )
        return np.concatenate([vol_features, position_features])

    def step(self, action):
        if self.idx >= self.n_steps:
            return self._get_obs(), 0.0, True, False, {}

        action_int = int(action)
        if action_int < 0 or action_int >= self.action_space.n:
            raise ValueError(f"Action out of range: {action_int}")

        t0 = self.timestamps[self.idx]
        t1 = self.timestamps[self.idx + 1]
        price_t0 = self._get_price(t0)
        price_t1 = self._get_price(t1)
        position_state = self._position_state(price_t0)
        requested_width = action_to_width(action_int)
        effective_action = "stay_cash"
        raw_boundary_before = float(self._current_boundary_pnl(price_t0))

        if position_state == "cash":
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
                components = self._with_pnl_breakdown({
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
                })
        elif position_state == "lp_in_range":
            if action_int == GO_CASH_ACTION:
                effective_action = "exit_to_cash"
                realized_boundary = raw_boundary_before
                capital_before_cost = self._capital_if_closed_now(price_t0)
                swap_frac = self._compute_exit_swap_fraction(price_t0)
                tx_cost, swap_fee_cost, mev_cost = self._compute_trade_costs(
                    capital_before_cost, swap_frac
                )
                self._set_cash_state(capital_before_cost - tx_cost)
                components = self._with_pnl_breakdown({
                    "lp_value_change_usd": 0.0,
                    "hedge_pnl_usd": 0.0,
                    "swing_pnl_usd": 0.0,
                    "raw_boundary_il_usd": raw_boundary_before,
                    "realized_boundary_pnl_usd": realized_boundary,
                    "pending_boundary_pnl_usd": 0.0,
                    "fee_usd": 0.0,
                    "funding_cost_usd": 0.0,
                    "tx_cost_usd": float(tx_cost),
                    "swap_fee_cost_usd": float(swap_fee_cost),
                    "mev_cost_usd": float(mev_cost),
                })
            else:
                effective_action = "hold"
                components = self._lp_hour_components(price_t0, price_t1)
        else:  # lp_oor
            if action_int == GO_CASH_ACTION:
                effective_action = "exit_to_cash"
                realized_boundary = raw_boundary_before
                capital_before_cost = self._capital_if_closed_now(price_t0)
                swap_frac = self._compute_exit_swap_fraction(price_t0)
                tx_cost, swap_fee_cost, mev_cost = self._compute_trade_costs(
                    capital_before_cost, swap_frac
                )
                self._set_cash_state(capital_before_cost - tx_cost)
                components = self._with_pnl_breakdown({
                    "lp_value_change_usd": 0.0,
                    "hedge_pnl_usd": 0.0,
                    "swing_pnl_usd": 0.0,
                    "raw_boundary_il_usd": raw_boundary_before,
                    "realized_boundary_pnl_usd": realized_boundary,
                    "pending_boundary_pnl_usd": 0.0,
                    "fee_usd": 0.0,
                    "funding_cost_usd": 0.0,
                    "tx_cost_usd": float(tx_cost),
                    "swap_fee_cost_usd": float(swap_fee_cost),
                    "mev_cost_usd": float(mev_cost),
                })
            elif requested_width > 0:
                effective_action = f"recenter_w{requested_width}"
                realized_boundary = raw_boundary_before
                capital_before_cost = self._capital_if_closed_now(price_t0)
                old_lower_price, old_upper_price = self._lp_bounds_prices()
                new_lower_tick, new_upper_tick = self._compute_position_bounds(
                    price_t0, requested_width
                )
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
                components = self._enter_or_recenter_components(
                    price_t0=price_t0,
                    price_t1=price_t1,
                    target_width=requested_width,
                    capital_before_cost=capital_before_cost,
                    swap_frac=swap_frac,
                    realized_boundary_pnl=realized_boundary,
                    raw_boundary_il_usd=raw_boundary_before,
                )
            else:
                effective_action = "hold_oor"
                components = self._lp_hour_components(price_t0, price_t1)

        self.idx += 1
        terminated = self.idx >= self.n_steps
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
            position_state=position_state,
            effective_action=effective_action,
            components=components,
        )
        reward = float(training_reward_usd / self._reward_denom())
        next_price = price_t1
        next_state = "terminal" if terminated else self._position_state(next_price)

        info = {
            "requested_action": action_int,
            "requested_action_label": action_to_label(action_int),
            "requested_width": requested_width,
            "effective_action": effective_action,
            "position_state": position_state,
            "next_position_state": next_state,
            "price": next_price,
            "hedge_accounting_mode": self.hedge_accounting_mode,
            "training_reward_mode": self.training_reward_mode,
            "portfolio_value": self.get_portfolio_value(),
            "close_now_portfolio_value": self._capital_if_closed_now(next_price),
            "pending_boundary_pnl": float(self.pending_boundary_pnl),
            "is_cash": self.is_cash,
            "width": self.lp_width_ticks if self.has_lp else 0,
            "in_range": next_state == "lp_in_range",
            **components,
            "training_reward_usd": float(training_reward_usd),
            "reward": reward,
        }
        return self._get_obs(), reward, terminated, False, info


def optimal_width_for_vol(natr_14: float) -> int:
    """Map current NATR-14 to a width from the supported discrete set."""
    if natr_14 <= 0:
        return 4
    if natr_14 < 0.005:
        return 2
    if natr_14 < 0.007:
        return 4
    if natr_14 < 0.010:
        return 6
    if natr_14 < 0.013:
        return 10
    if natr_14 < 0.018:
        return 15
    if natr_14 < 0.025:
        return 20
    return 40


def conservative_optimal_width_for_vol(natr_14: float) -> int:
    """Wider width prior used when raw swing is recognized in reward."""
    if natr_14 <= 0:
        return 10
    if natr_14 < 0.005:
        return 6
    if natr_14 < 0.007:
        return 10
    if natr_14 < 0.010:
        return 15
    if natr_14 < 0.013:
        return 20
    if natr_14 < 0.018:
        return 30
    return 40


def should_deploy(bb_width: float, bb_threshold: float = 0.038) -> bool:
    """Simple timing rule used as an analytical baseline."""
    return bb_width > bb_threshold
