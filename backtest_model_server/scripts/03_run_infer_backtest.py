"""
Phase 3-4 — Core backtest simulation loop (realistic simulation_14 economics).

Replays the model server against historical data using the reference_date parameter.
For each hourly step: build InferRequest → POST /infer/{strategy} → simulate portfolio
using per-swap fee computation, continuous delta hedging, and v3 position math.

Fee model ported from simulation_14/training/uniswap_v3_ppo_paper.py:
  fee_j = swap_amount[j] × pool_fee × liquidity_share × in_range_fraction
  where liquidity_share = L_ours_raw / (L_pool + L_ours_raw)

Hedge PnL from simulation_14/training/uniswap_v3_hedged_fee_env.py:
  Active rehedging along intra-hour swap path with perp funding cost.

Usage (from backtest_model_server/):
    python scripts/03_run_infer_backtest.py
    python scripts/03_run_infer_backtest.py --config config/backtest_config.yaml
    python scripts/03_run_infer_backtest.py --resume  # resume from last saved step

Output:
    results/inference_log.csv    per-step HTTP observability
    results/trace_df.parquet     simulation trace (input to 04_compute_metrics.py)

Notes:
  - reference_date requests bypass the model server B2 cache; each call triggers a fresh
    B2 download.  For a 31-day × 24h backtest expect ~25-38 min total (sequential).
  - Use --resume to continue an interrupted run without re-fetching completed steps.
  - Set MODEL_API_KEY env var or api_key in config for authenticated servers.
"""

import sys
import os
import csv
import json
import time
import math
import re
import logging
import argparse
from pathlib import Path
from datetime import date, datetime, timedelta
from typing import Optional

import yaml
import requests
import pandas as pd
import numpy as np

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
BASE_DIR   = SCRIPT_DIR.parent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def load_config(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def parse_config_date(value, field_name: str) -> datetime:
    """Parse YAML date/datetime/string values into datetime."""
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(
                f"Invalid {field_name} '{value}' (expected ISO format YYYY-MM-DD)"
            ) from exc
    raise TypeError(
        f"Invalid {field_name} type {type(value).__name__} (expected str/date/datetime)"
    )


# ===========================================================================
# Uniswap V3 math (ported from simulation_14/uniswap_v3_ppo_paper.py)
# ===========================================================================

def price_to_tick(price: float) -> int:
    """Convert human-readable price to tick: i = floor(log(p) / log(1.0001))"""
    if price <= 0:
        return 0
    return int(math.floor(math.log(price) / math.log(1.0001)))


def tick_to_price(tick: int) -> float:
    """Convert tick to human-readable price: p(i) = 1.0001^i"""
    return math.pow(1.0001, tick)


def human_tick_to_v3_tick(human_tick: int, decimals0: int, decimals1: int) -> int:
    """Convert human-price tick to v3-core raw-price tick."""
    offset = int(round((decimals0 - decimals1) * math.log(10) / math.log(1.0001)))
    return human_tick - offset


def v3_tick_to_human_tick(v3_tick: int, decimals0: int, decimals1: int) -> int:
    """Convert v3-core raw-price tick to human-price tick."""
    offset = int(round((decimals0 - decimals1) * math.log(10) / math.log(1.0001)))
    return v3_tick + offset


def _tick_in_range_fraction(tick_before: int, tick_after: int,
                            lp_lower_tick: int, lp_upper_tick: int) -> float:
    """Fraction of a swap's tick span within the LP range [lp_lower, lp_upper]."""
    if tick_before == tick_after:
        return 1.0 if lp_lower_tick <= tick_before <= lp_upper_tick else 0.0
    total_ticks = abs(tick_after - tick_before)
    lo = min(tick_before, tick_after)
    hi = max(tick_before, tick_after)
    overlap_lo = max(lo, lp_lower_tick)
    overlap_hi = min(hi, lp_upper_tick)
    if overlap_hi <= overlap_lo:
        return 0.0
    return (overlap_hi - overlap_lo) / total_ticks


def compute_position_value(price: float, price_lower: float,
                           price_upper: float, L: float) -> float:
    """
    LP position value V(p) from Equation 15.
    V = L * (2√p - p/√p_u - √p_l) when p ∈ [p_l, p_u]
    """
    if L <= 0 or price <= 0:
        return 0.0
    sqrt_p  = math.sqrt(price)
    sqrt_pl = math.sqrt(price_lower)
    sqrt_pu = math.sqrt(price_upper)
    if price <= price_lower:
        x = L * (1.0 / sqrt_pl - 1.0 / sqrt_pu)
        return x * price
    elif price >= price_upper:
        y = L * (sqrt_pu - sqrt_pl)
        return y
    else:
        return L * (2.0 * sqrt_p - price / sqrt_pu - sqrt_pl)


def compute_lp_delta(price: float, price_lower: float,
                     price_upper: float, L: float) -> float:
    """
    ETH delta of LP position at given price (token0 amount if closed).
    v3-core: getAmount0Delta.
    """
    if L <= 0 or price <= 0:
        return 0.0
    sqrt_p  = math.sqrt(price)
    sqrt_pl = math.sqrt(price_lower)
    sqrt_pu = math.sqrt(price_upper)
    if price <= price_lower:
        return L * (1.0 / sqrt_pl - 1.0 / sqrt_pu)
    elif price >= price_upper:
        return 0.0
    else:
        return L * (1.0 / sqrt_p - 1.0 / sqrt_pu)


def compute_liquidity_from_capital(capital: float, price: float,
                                   price_lower: float, price_upper: float) -> float:
    """Compute liquidity L from deployable capital at current price."""
    if capital <= 0 or price <= 0:
        return 0.0
    value_per_unit_L = compute_position_value(price, price_lower, price_upper, 1.0)
    if value_per_unit_L <= 0:
        return 0.0
    return capital / value_per_unit_L


def compute_swap_fraction(price: float, old_lower: float, old_upper: float,
                          new_lower: float, new_upper: float) -> float:
    """Fraction of capital needing a swap on rebalance (0.5 for first deploy)."""
    sqrt_p = math.sqrt(max(price, 1e-30))

    def x_frac(pl, pu):
        spl = math.sqrt(pl)
        spu = math.sqrt(pu)
        if price <= pl:
            return 1.0
        elif price >= pu:
            return 0.0
        else:
            x_val = 1.0 / sqrt_p - 1.0 / spu
            total = 2.0 * sqrt_p - price / spu - spl
            return (x_val * price / total) if total > 0 else 0.5

    old_xf = x_frac(old_lower, old_upper)
    new_xf = x_frac(new_lower, new_upper)
    return abs(new_xf - old_xf)


def compute_lp_range_from_width(price: float, width: int, tick_spacing: int = 10) -> dict:
    """Compute the canonical training-env LP range for a width decision.

    Widths are total tick-spacings across the interval: W4 means center +/-2
    tick-spacings, matching UniswapV3PaperEnv._compute_position_bounds.
    """
    tick = price_to_tick(price)
    center_tick = (tick // tick_spacing) * tick_spacing
    half_width_ticks = int(width) * tick_spacing // 2
    lower_tick = center_tick - half_width_ticks
    upper_tick = center_tick + half_width_ticks
    price_lower = tick_to_price(lower_tick)
    price_upper = tick_to_price(upper_tick)
    return {
        "width": int(width),
        "center_tick": int(center_tick),
        "lower_tick": int(lower_tick),
        "upper_tick": int(upper_tick),
        "price_lower": float(price_lower),
        "price_upper": float(price_upper),
        "range_pct": float((price_upper / price_lower - 1.0) * 100.0),
    }


def infer_width_from_state(state: dict, tick_spacing: int = 10) -> Optional[int]:
    """Best-effort recovery of current W label from stored human tick bounds."""
    lower_tick = state.get("lower_tick")
    upper_tick = state.get("upper_tick")
    if lower_tick is None or upper_tick is None:
        return None
    try:
        width = int(round((int(upper_tick) - int(lower_tick)) / float(tick_spacing)))
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    return width if width > 0 else None


def normalize_action_label(
    raw_action_label: Optional[str],
    current_width: Optional[int] = None,
) -> tuple[str, Optional[int]]:
    """Normalize server/Kongtrae action dialects to HOLD, EXIT, WIDTH-n."""
    raw = str(raw_action_label or "HOLD").strip().upper()
    compact = raw.replace("-", "_").replace(" ", "_")

    if compact in {"HOLD", "STAY_CASH", "HOLD_OOR", "MASKED"}:
        return "HOLD", None
    if compact in {"GO_CASH", "EXIT", "EXIT_TO_CASH", "CLOSE_POSITION", "CLOSE"}:
        return "EXIT", None
    if compact == "RECENTER_SAME_WIDTH":
        if current_width:
            return f"WIDTH-{int(current_width)}", int(current_width)
        return "HOLD", None

    match = re.search(r"(?:WIDTH|ENTER_W|DEPLOY_W|RECENTER_W|W)[_-]?(\d+)$", compact)
    if match:
        width = int(match.group(1))
        return f"WIDTH-{width}", width

    return "HOLD", None


# ===========================================================================
# Raw swap data loader
# ===========================================================================

class HourlySwapData:
    """Pre-processed per-hour swap arrays for realistic fee/hedge computation."""

    def __init__(self, decimals0: int = 18, decimals1: int = 6):
        self.decimals0 = decimals0
        self.decimals1 = decimals1
        # Dict[pd.Timestamp -> np.ndarray]
        self.swap_prices_per_hour: dict = {}      # human-readable prices
        self.swap_amounts_per_hour: dict = {}      # USD volume per swap
        self.swap_liquidity_per_hour: dict = {}    # raw pool liquidity per swap
        self.swap_ticks_per_hour: dict = {}        # v3-core ticks per swap
        self.swap_time_seconds_per_hour: dict = {} # seconds into hour per swap
        self.pool_liquidity_per_hour: dict = {}    # median pool liquidity per hour
        self.volume_per_hour: dict = {}            # total USD volume per hour

    @classmethod
    def from_raw_parquet(cls, raw_swap_dir: Path,
                         start_dt: datetime, end_dt: datetime,
                         decimals0: int = 18, decimals1: int = 6) -> "HourlySwapData":
        """Load raw swap parquet files and aggregate into hourly buckets."""
        obj = cls(decimals0, decimals1)

        # Find all parquet files under raw_swap_dir
        candidates = [
            raw_swap_dir / "raw" / "swaps",
            raw_swap_dir / "swaps",
        ]
        parquet_files = []
        for d in candidates:
            if d.exists():
                parquet_files.extend(sorted(d.rglob("*.parquet")))
                if parquet_files:
                    break

        if not parquet_files:
            log.warning("No raw swap parquet files found under %s", raw_swap_dir)
            return obj

        log.info("Loading %d raw swap parquet files...", len(parquet_files))
        dfs = []
        for f in parquet_files:
            try:
                dfs.append(pd.read_parquet(f))
            except Exception as e:
                log.warning("Skipping %s: %s", f, e)
        if not dfs:
            log.warning("No valid swap data loaded")
            return obj

        swaps = pd.concat(dfs, ignore_index=True)
        log.info("Total raw swaps: %d", len(swaps))

        # Parse fields
        swaps["timestamp_dt"] = pd.to_datetime(swaps["timestamp"], unit="s", utc=True)
        swaps["hour"] = swaps["timestamp_dt"].dt.floor("h")

        # Compute human-readable price from sqrt_price_x96
        sqrt_px96 = swaps["sqrt_price_x96"].apply(lambda x: int(str(x)))
        decimal_adj = 10 ** (decimals0 - decimals1)
        # price = (sqrt_price_x96 / 2^96)^2 * 10^(d0 - d1)
        prices = (sqrt_px96.astype(float) / (2**96)) ** 2 * decimal_adj
        swaps["price"] = prices

        # USD volume = abs(amount1) / 10^decimals1
        swaps["volume_usd"] = swaps["amount1"].apply(
            lambda x: abs(int(str(x))) / 10**decimals1
        )

        # Pool liquidity (raw v3-core units)
        swaps["pool_liquidity"] = swaps["liquidity"].apply(lambda x: float(int(str(x))))

        # v3 tick
        swaps["v3_tick"] = swaps["tick"].astype(int)

        # Seconds into hour
        swaps["seconds_in_hour"] = (
            swaps["timestamp_dt"] - swaps["hour"]
        ).dt.total_seconds()

        # Filter to date range
        start_ts = pd.Timestamp(start_dt, tz="UTC")
        end_ts = pd.Timestamp(end_dt, tz="UTC") + pd.Timedelta(days=1)
        swaps = swaps[(swaps["timestamp_dt"] >= start_ts) & (swaps["timestamp_dt"] < end_ts)]

        # Group by hour
        for hour_ts, group in swaps.groupby("hour"):
            group = group.sort_values("timestamp")
            obj.swap_prices_per_hour[hour_ts] = group["price"].values.astype(np.float64)
            obj.swap_amounts_per_hour[hour_ts] = group["volume_usd"].values.astype(np.float64)
            obj.swap_liquidity_per_hour[hour_ts] = group["pool_liquidity"].values.astype(np.float64)
            obj.swap_ticks_per_hour[hour_ts] = group["v3_tick"].values.astype(np.int64)
            obj.swap_time_seconds_per_hour[hour_ts] = group["seconds_in_hour"].values.astype(np.float64)
            obj.pool_liquidity_per_hour[hour_ts] = float(np.median(group["pool_liquidity"].values))
            obj.volume_per_hour[hour_ts] = float(group["volume_usd"].sum())

        log.info("Hourly swap data: %d hours loaded", len(obj.swap_prices_per_hour))
        return obj

    def get_pool_liquidity(self, ts: pd.Timestamp) -> float:
        return self.pool_liquidity_per_hour.get(ts, 0.0)

    def get_volume(self, ts: pd.Timestamp) -> float:
        return self.volume_per_hour.get(ts, 0.0)


# ===========================================================================
# Realistic fee computation (ported from simulation_14)
# ===========================================================================

def compute_fee(
    swap_data: HourlySwapData,
    hour_ts: pd.Timestamp,
    price_t: float,
    price_t1: float,
    L: float,
    price_lower: float,
    price_upper: float,
    pool_fee: float,
    liquidity_scale: float,
) -> float:
    """
    Compute LP fee income for one hour using per-swap data.

    Primary path (swap_amounts available):
      fee_j = swap_amount[j] × pool_fee × liquidity_share_j × in_range_fraction_j

    Fallback (swap_prices only):
      |Δ√p| formula capped at volume × pool_fee × liquidity_share

    Open-close fallback:
      Single-interval formula from hourly open/close prices.
    """
    if L <= 0:
        return 0.0

    swap_prices = swap_data.swap_prices_per_hour.get(hour_ts)
    swap_amounts = swap_data.swap_amounts_per_hour.get(hour_ts)
    swap_liquidities = swap_data.swap_liquidity_per_hour.get(hour_ts)
    swap_ticks = swap_data.swap_ticks_per_hour.get(hour_ts)

    # Hourly-median liquidity share (fallback)
    L_raw = L * liquidity_scale
    pool_L = swap_data.get_pool_liquidity(hour_ts)
    if pool_L > 0 and L_raw > 0:
        liquidity_share = L_raw / (pool_L + L_raw)
    else:
        liquidity_share = 0.0

    # LP tick bounds (in v3-core units for tick comparison with swap data)
    lp_lower_tick_human = price_to_tick(price_lower)
    lp_upper_tick_human = price_to_tick(price_upper)
    decimals0 = swap_data.decimals0
    decimals1 = swap_data.decimals1
    lp_lower_v3 = human_tick_to_v3_tick(lp_lower_tick_human, decimals0, decimals1)
    lp_upper_v3 = human_tick_to_v3_tick(lp_upper_tick_human, decimals0, decimals1)

    if swap_prices is not None and len(swap_prices) >= 1:
        total_fee = 0.0
        use_amounts = swap_amounts is not None and len(swap_amounts) > 0

        if use_amounts:
            # Primary path: per-swap fee with exact liquidity and tick data
            opening_v3_tick = human_tick_to_v3_tick(price_to_tick(price_t), decimals0, decimals1)

            for j in range(len(swap_amounts)):
                p_before = swap_prices[j - 1] if j > 0 else price_t
                p_after = swap_prices[j]

                # Skip if both outside range on same side
                if (p_before < price_lower and p_after < price_lower) or \
                   (p_before > price_upper and p_after > price_upper):
                    continue

                # Per-swap pool liquidity → exact liquidity_share
                if (swap_liquidities is not None and j < len(swap_liquidities)
                        and swap_liquidities[j] > 0):
                    pool_L_j = swap_liquidities[j]
                    ls_j = L_raw / (pool_L_j + L_raw)
                else:
                    ls_j = liquidity_share

                # Tick-based in-range fraction
                if swap_ticks is not None and j < len(swap_ticks):
                    t_before = int(swap_ticks[j - 1]) if j > 0 else opening_v3_tick
                    t_after = int(swap_ticks[j])
                    in_range_frac = _tick_in_range_fraction(
                        t_before, t_after, lp_lower_v3, lp_upper_v3
                    )
                else:
                    # |Δ√p| fallback for in-range fraction
                    p0_c = max(price_lower, min(price_upper, p_before))
                    p1_c = max(price_lower, min(price_upper, p_after))
                    total_sqrt_move = abs(
                        math.sqrt(max(p_after, 1e-30)) - math.sqrt(max(p_before, 1e-30))
                    )
                    in_range_frac = (
                        abs(math.sqrt(p1_c) - math.sqrt(p0_c)) / total_sqrt_move
                        if total_sqrt_move > 0 else 1.0
                    )

                fee_j = swap_amounts[j] * pool_fee * ls_j * in_range_frac
                total_fee += max(0.0, fee_j)

        elif len(swap_prices) >= 2:
            # Fallback: |Δ√p|-based formula (no volume data)
            delta = pool_fee
            fee_mult = delta / (1.0 - delta)
            impact_factor = liquidity_share

            for i in range(len(swap_prices) - 1):
                p0 = swap_prices[i]
                p1 = swap_prices[i + 1]
                if (p0 < price_lower and p1 < price_lower) or \
                   (p0 > price_upper and p1 > price_upper):
                    continue
                p0_c = max(price_lower, min(price_upper, p0))
                p1_c = max(price_lower, min(price_upper, p1))
                sqrt_p0_c = math.sqrt(p0_c)
                sqrt_p1_c = math.sqrt(p1_c)
                if sqrt_p0_c <= sqrt_p1_c:
                    fee_i = fee_mult * L * (sqrt_p1_c - sqrt_p0_c) * impact_factor
                else:
                    fee_i = fee_mult * L * (1.0 / sqrt_p1_c - 1.0 / sqrt_p0_c) * p1_c * impact_factor
                total_fee += max(0.0, fee_i)

            # Cap at volume-based ceiling
            volume_usd = swap_data.get_volume(hour_ts)
            max_fee = volume_usd * pool_fee * liquidity_share
            total_fee = min(total_fee, max_fee)

    else:
        # Open-close fallback
        if (price_t < price_lower and price_t1 < price_lower) or \
           (price_t > price_upper and price_t1 > price_upper):
            return 0.0

        delta = pool_fee
        fee_mult = delta / (1.0 - delta)
        p_t_c = max(price_lower, min(price_upper, price_t))
        p_t1_c = max(price_lower, min(price_upper, price_t1))
        if p_t_c <= p_t1_c:
            total_fee = fee_mult * L * (math.sqrt(p_t1_c) - math.sqrt(p_t_c))
        else:
            total_fee = fee_mult * L * (1.0 / math.sqrt(p_t1_c) - 1.0 / math.sqrt(p_t_c)) * p_t1_c

        total_fee = max(0.0, total_fee)
        volume_usd = swap_data.get_volume(hour_ts)
        max_fee = volume_usd * pool_fee * liquidity_share
        total_fee = min(total_fee, max_fee)

    return total_fee


# ===========================================================================
# Hedge PnL & funding (ported from simulation_14)
# ===========================================================================

def compute_active_hedge_hour(
    swap_data: HourlySwapData,
    hour_ts: pd.Timestamp,
    price_t0: float,
    price_t1: float,
    L: float,
    price_lower: float,
    price_upper: float,
    funding_hr: float,
) -> tuple[float, float]:
    """
    Approximate actively rehedged perp hedge over observed swap path.
    Returns (hedge_pnl, funding_cost).
    """
    swap_prices = swap_data.swap_prices_per_hour.get(hour_ts)
    swap_times = swap_data.swap_time_seconds_per_hour.get(hour_ts)

    if swap_prices is None or len(swap_prices) == 0:
        # Simple open-close hedge
        lp_delta = compute_lp_delta(price_t0, price_lower, price_upper, L)
        hedge_pnl = -lp_delta * (price_t1 - price_t0)
        funding_cost = abs(lp_delta * price_t0) * funding_hr
        return hedge_pnl, funding_cost

    # Active rehedging along swap path
    hedge_pnl = 0.0
    funding_cost = 0.0
    prev_price = price_t0
    prev_time_seconds = 0.0

    for j, swap_price in enumerate(swap_prices):
        cur_price = float(swap_price)
        delta_unit = compute_lp_delta(prev_price, price_lower, price_upper, 1.0)
        hedge_pnl += -delta_unit * (cur_price - prev_price)

        if swap_times is not None and j < len(swap_times):
            cur_time_seconds = float(min(max(swap_times[j], prev_time_seconds), 3600.0))
            dt_hours = max(cur_time_seconds - prev_time_seconds, 0.0) / 3600.0
            funding_cost += abs(delta_unit * prev_price) * funding_hr * dt_hours
            prev_time_seconds = cur_time_seconds

        prev_price = cur_price

    # Remaining time after last swap
    if swap_times is not None:
        delta_unit = compute_lp_delta(prev_price, price_lower, price_upper, 1.0)
        dt_hours = max(3600.0 - prev_time_seconds, 0.0) / 3600.0
        funding_cost += abs(delta_unit * prev_price) * funding_hr * dt_hours
    else:
        # No timing data: use open delta for full hour
        open_delta = compute_lp_delta(price_t0, price_lower, price_upper, 1.0)
        funding_cost = abs(open_delta * price_t0) * funding_hr

    # Scale by liquidity (computed per-unit-L above)
    hedge_pnl *= L
    funding_cost *= L

    return hedge_pnl, funding_cost


# ===========================================================================
# Transaction costs (ported from simulation_14)
# ===========================================================================

def compute_trade_costs(
    notional: float,
    swap_frac: float,
    pool_fee: float,
    gas_cost_usd: float,
    mev_slippage_pct: float,
) -> tuple[float, float, float]:
    """Gas + swap fee + MEV/slippage cost for a trade.
    Returns (total_tx_cost, swap_fee_cost, mev_cost)."""
    capped_swap_frac = min(max(float(swap_frac), 0.0), 1.0)
    base_notional = max(float(notional), 0.0)
    swap_fee_cost = capped_swap_frac * pool_fee * base_notional
    mev_cost = capped_swap_frac * mev_slippage_pct * base_notional
    tx_cost = gas_cost_usd + swap_fee_cost + mev_cost
    return tx_cost, swap_fee_cost, mev_cost


def compute_exit_swap_fraction(price: float, price_lower: float, price_upper: float) -> float:
    """Token0 value fraction of an LP position — swap cost for exiting to cash."""
    if price <= 0:
        return 0.0
    if price <= price_lower:
        return 1.0
    if price >= price_upper:
        return 0.0
    sqrt_p = math.sqrt(price)
    sqrt_pl = math.sqrt(price_lower)
    sqrt_pu = math.sqrt(price_upper)
    amount0_value = (1.0 / sqrt_p - 1.0 / sqrt_pu) * price
    amount1_value = sqrt_p - sqrt_pl
    total_value = amount0_value + amount1_value
    if total_value <= 0:
        return 0.0
    return min(max(amount0_value / total_value, 0.0), 1.0)


def compute_time_in_range_for_hour(
    swap_data: "HourlySwapData",
    hour_ts: "pd.Timestamp",
    lower_tick: int,
    upper_tick: int,
) -> float:
    """Fraction of swaps in the given hour that fell within LP tick bounds."""
    swap_ticks = swap_data.swap_ticks_per_hour.get(hour_ts)
    if swap_ticks is None or len(swap_ticks) == 0:
        return 0.0
    in_range = (swap_ticks >= lower_tick) & (swap_ticks <= upper_tick)
    return float(np.mean(in_range))


# ===========================================================================
# Position state helpers
# ===========================================================================

def _compute_position_state(current_price: float, state: dict) -> str:
    if not state.get("has_position"):
        return "cash"
    pl = state.get("price_lower", 0.0) or 0.0
    pu = state.get("price_upper", float("inf")) or float("inf")
    if pl <= current_price <= pu:
        return "lp_in_range"
    return "lp_oor"


# ===========================================================================
# Core simulation step (realistic economics)
# ===========================================================================

def simulate_step(
    step_idx: int,
    prev_price: float,
    current_price: float,
    timestamp: datetime,
    action_label: str,
    lp_range: Optional[dict],
    prev_state: dict,
    cfg: dict,
    swap_data: HourlySwapData,
) -> tuple[dict, dict]:
    """
    Process one simulation step with realistic simulation_14 economics.

    Timeline:
      - prev_state was the state AFTER the previous step's action.
      - During [prev_step → this_step] the price moved prev_price → current_price.
      - We first credit/debit P&L for that interval, then apply the new action.

    Returns (new_state, step_record).

    Note: `prev_state["hours_since_rebalance"]` is expected to already reflect
    the hour that elapses BETWEEN the previous step and this one — the main
    loop ticks it before building the /infer body so the policy sees the same
    obs the training env would at `idx - position_entry_idx`.
    """
    s = prev_state.copy()
    pool_fee          = cfg.get("pool_fee", 0.0005)
    gas_cost_usd      = cfg.get("gas_cost_usd", 0.03)
    mev_slippage_pct  = cfg.get("mev_slippage_pct", 0.0001)
    funding_annual    = cfg.get("funding_rate_annual", 0.048)
    funding_hr        = funding_annual / 8760.0
    hedge_ratio       = cfg.get("hedge_ratio", 1.0)
    decimals0         = cfg.get("decimals0", 18)
    decimals1         = cfg.get("decimals1", 6)
    liquidity_scale   = 10 ** ((decimals0 + decimals1) / 2)
    hedge_mode        = cfg.get("hedge_accounting_mode", "continuous_delta_hedged")

    # Timestamp for swap data lookup (use the hour of this step)
    hour_ts = pd.Timestamp(timestamp, tz="UTC").floor("h")

    # ---- 1. Compute P&L for the interval ending at this step ----------------
    fee_usd              = 0.0
    lp_value_change_usd  = 0.0
    hedge_pnl_usd        = 0.0
    funding_cost_usd     = 0.0

    # Debug diagnostics (always populated, 0.0 when no position)
    dbg_L_raw             = 0.0
    dbg_pool_L_median     = 0.0
    dbg_liquidity_share   = 0.0
    dbg_hourly_volume_usd = float(swap_data.get_volume(hour_ts))
    _swaps_this_hour = swap_data.swap_prices_per_hour.get(hour_ts)
    dbg_num_swaps         = int(len(_swaps_this_hour)) if _swaps_this_hour is not None else 0

    if s.get("has_position") and step_idx > 0 and s.get("liquidity", 0) > 0:
        L = s["liquidity"]
        pl = s.get("price_lower", 0.0) or 0.0
        pu = s.get("price_upper", float("inf")) or float("inf")
        prev_pos_state = _compute_position_state(prev_price, s)

        # Diagnostics: compute hourly-median liquidity share the same way compute_fee does.
        dbg_L_raw = L * liquidity_scale
        dbg_pool_L_median = float(swap_data.get_pool_liquidity(hour_ts))
        if dbg_pool_L_median > 0 and dbg_L_raw > 0:
            dbg_liquidity_share = dbg_L_raw / (dbg_pool_L_median + dbg_L_raw)

        # Position value change (exact v3 math)
        value_t0 = compute_position_value(prev_price, pl, pu, L)
        value_t1 = compute_position_value(current_price, pl, pu, L)
        lp_value_change_usd = value_t1 - value_t0

        if prev_pos_state == "lp_in_range":
            # Fee accrual from per-swap data
            fee_usd = compute_fee(
                swap_data, hour_ts, prev_price, current_price,
                L, pl, pu, pool_fee, liquidity_scale,
            )

        # Hedge PnL and funding (even for OOR, delta hedge still applies)
        hedge_pnl_usd, funding_cost_usd = compute_active_hedge_hour(
            swap_data, hour_ts, prev_price, current_price,
            L, pl, pu, funding_hr,
        )
        # Scale by hedge ratio (1.0 = full hedge matching training, <1.0 = partial)
        hedge_pnl_usd *= hedge_ratio
        funding_cost_usd *= hedge_ratio

    # Apply interval P&L to capital tracking
    # continuous_delta_hedged: capital = initial + Σ(fee + swing_pnl - funding - tx_cost)
    swing_pnl_usd = lp_value_change_usd + hedge_pnl_usd
    s["accumulated_fees"] = s.get("accumulated_fees", 0.0) + fee_usd
    s["cumulative_hedge_pnl"] = s.get("cumulative_hedge_pnl", 0.0) + hedge_pnl_usd
    s["cumulative_funding"] = s.get("cumulative_funding", 0.0) + funding_cost_usd

    # Update portfolio value using v3 position value + accumulated fees + hedge pnl
    if s.get("has_position") and s.get("liquidity", 0) > 0:
        pl = s.get("price_lower", 0.0) or 0.0
        pu = s.get("price_upper", float("inf")) or float("inf")
        pos_value = compute_position_value(current_price, pl, pu, s["liquidity"])
        s["portfolio_value_usd"] = (
            pos_value
            + s["accumulated_fees"]
            + s["cumulative_hedge_pnl"]
            - s["cumulative_funding"]
        )
    # else: portfolio_value_usd stays as actual_capital (cash)

    # ---- 2. Apply action -------------------------------------------------------
    step_tx_cost     = 0.0
    swap_fee_cost    = 0.0
    mev_cost         = 0.0

    if action_label == "EXIT":
        # Model requests position exit → close to cash
        if s.get("has_position"):
            effective_action = "exit_to_cash"
            pl = s.get("price_lower", 0.0) or 0.0
            pu = s.get("price_upper", float("inf")) or float("inf")
            swap_frac = compute_exit_swap_fraction(current_price, pl, pu)
            capital_before_cost = s["portfolio_value_usd"]
            step_tx_cost, swap_fee_cost, mev_cost = compute_trade_costs(
                capital_before_cost, swap_frac, pool_fee, gas_cost_usd, mev_slippage_pct
            )
            s["has_position"]          = False
            s["width"]                 = None
            s["lower_tick"]            = None
            s["upper_tick"]            = None
            s["price_lower"]           = None
            s["price_upper"]           = None
            s["entry_price"]           = None
            s["liquidity"]             = 0.0
            s["hours_since_rebalance"] = 0.0
            s["accumulated_fees"]      = 0.0
            s["cumulative_hedge_pnl"]  = 0.0
            s["cumulative_funding"]    = 0.0
            s["portfolio_value_usd"]   = max(capital_before_cost - step_tx_cost, 0.0)
        else:
            effective_action = "hold"  # EXIT while already in cash = no-op
    elif action_label != "HOLD" and lp_range is not None:
        # Enter or recenter
        width_str = action_label.split("-")[1].lower()   # "4", "6", "10", "20"

        if s.get("has_position"):
            effective_action = f"recenter_w{width_str}"
            # Close old position first
            old_pl = s.get("price_lower", 0.0) or 0.0
            old_pu = s.get("price_upper", float("inf")) or float("inf")
            new_pl = lp_range["price_lower"]
            new_pu = lp_range["price_upper"]
            swap_frac = compute_swap_fraction(
                current_price, old_pl, old_pu, new_pl, new_pu
            )
            # Realize position: capital = current portfolio value
            capital_before_cost = s["portfolio_value_usd"]
        else:
            effective_action = f"enter_w{width_str}"
            swap_frac = 0.5  # First deployment: ~50% swap
            capital_before_cost = s["portfolio_value_usd"]

        step_tx_cost, swap_fee_cost, mev_cost = compute_trade_costs(
            capital_before_cost, swap_frac, pool_fee, gas_cost_usd, mev_slippage_pct
        )

        deployable_capital = max(capital_before_cost - step_tx_cost, 0.0)

        # Open new position
        new_pl = lp_range["price_lower"]
        new_pu = lp_range["price_upper"]
        new_L = compute_liquidity_from_capital(deployable_capital, current_price, new_pl, new_pu)

        s["has_position"]          = True
        s["width"]                 = int(lp_range.get("width", int(width_str)))
        s["lower_tick"]            = lp_range["lower_tick"]
        s["upper_tick"]            = lp_range["upper_tick"]
        s["price_lower"]           = new_pl
        s["price_upper"]           = new_pu
        s["entry_price"]           = current_price
        s["liquidity"]             = new_L
        s["hours_since_rebalance"] = 0.0
        # Reset accumulators for new position
        s["accumulated_fees"]      = 0.0
        s["cumulative_hedge_pnl"]  = 0.0
        s["cumulative_funding"]    = 0.0
        s["portfolio_value_usd"]   = deployable_capital
    else:
        effective_action = "hold"
        # hsr was already ticked at the start of the step

    # ---- 3. Determine position state after action --------------------------------
    position_state = _compute_position_state(current_price, s)
    is_cash_after  = int(position_state == "cash")

    s["position_state"]  = position_state
    s["current_price"]   = current_price

    # PnL breakdown (continuous_delta_hedged mode)
    if hedge_mode == "continuous_delta_hedged":
        hedged_core_pnl = swing_pnl_usd - funding_cost_usd
        net_before_tx = hedged_core_pnl + fee_usd
        net_after_tx = net_before_tx - step_tx_cost
    elif hedge_mode == "idealized_perfect":
        net_before_tx = fee_usd - funding_cost_usd
        net_after_tx = net_before_tx - step_tx_cost
    else:  # "none"
        net_before_tx = fee_usd + lp_value_change_usd
        net_after_tx = net_before_tx - step_tx_cost

    gross_fee_carry = fee_usd - funding_cost_usd - step_tx_cost

    # band_lower/band_upper: belt-and-suspenders against stale-bound regressions.
    # For any held position, recompute the canonical bounds from (width, current_price)
    # using the sim14 contract (half_width_ticks = width * tick_spacing // 2). The
    # dashboard prefers these over price_lower/price_upper so a logging bug can no
    # longer silently make recenter rows look like holds.
    if s.get("has_position") and s.get("width") and current_price > 0:
        _canonical_range = compute_lp_range_from_width(current_price, int(s["width"]), cfg)
        band_lower = float(_canonical_range["price_lower"])
        band_upper = float(_canonical_range["price_upper"])
    else:
        band_lower = None
        band_upper = None

    step_record = {
        "step":                    step_idx,
        "timestamp":               timestamp.isoformat(),
        "reference_date":          timestamp.strftime("%Y-%m-%dT%H:%M:%S"),
        "initial_capital_usd":     s["initial_capital_usd"],
        "current_price":           current_price,
        "effective_action":        effective_action,
        "action_label":            action_label,
        "position_state":          position_state,
        "is_cash_after":           is_cash_after,
        "portfolio_value":         s["portfolio_value_usd"],
        "fee_usd":                 fee_usd,
        "tx_cost_usd":             step_tx_cost,
        "swap_fee_cost_usd":       swap_fee_cost,
        "mev_cost_usd":            mev_cost,
        "lp_value_change_usd":     lp_value_change_usd,
        "hedge_pnl_usd":           hedge_pnl_usd,
        "funding_cost_usd":        funding_cost_usd,
        "swing_pnl_usd":           swing_pnl_usd,
        "gross_fee_carry_usd":     gross_fee_carry,
        "net_before_tx_usd":       net_before_tx,
        "net_after_tx_usd":        net_after_tx,
        "reward_usd":              net_after_tx,
        "raw_swing_pnl_usd":       swing_pnl_usd,
        "raw_boundary_il_usd":     0.0,
        "hedge_accounting_mode":   hedge_mode,
        "has_position":            int(s.get("has_position", False)),
        "width":                   s.get("width"),
        "lower_tick":              s.get("lower_tick"),
        "upper_tick":              s.get("upper_tick"),
        "price_lower":             s.get("price_lower"),
        "price_upper":             s.get("price_upper"),
        "band_lower":              band_lower,
        "band_upper":              band_upper,
        "liquidity":               s.get("liquidity", 0.0),
        "hours_since_rebalance":   s["hours_since_rebalance"],
        # --- Debug diagnostics ------------------------------------------------
        "dbg_L_raw":               dbg_L_raw,
        "dbg_pool_L_median":       dbg_pool_L_median,
        "dbg_liquidity_share":     dbg_liquidity_share,
        "dbg_hourly_volume_usd":   dbg_hourly_volume_usd,
        "dbg_num_swaps":           dbg_num_swaps,
    }

    return s, step_record


# ---------------------------------------------------------------------------
# HTTP client
# ---------------------------------------------------------------------------

def call_infer(
    server_url: str,
    strategy: str,
    api_key: Optional[str],
    body: dict,
    max_retries: int,
    retry_backoff_base: float,
    timeout: int,
) -> tuple[Optional[dict], int, float, int, Optional[str]]:
    """
    POST /infer/{strategy} with retry on 503.

    Returns (response_dict, status_code, latency_ms, retry_count, error_detail)
    """
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    url = f"{server_url}/infer/{strategy}"
    retry_count = 0
    t0 = time.monotonic()

    for attempt in range(max_retries + 1):
        try:
            resp = requests.post(url, json=body, headers=headers, timeout=timeout)
            latency_ms = (time.monotonic() - t0) * 1000.0

            if resp.status_code == 200:
                return resp.json(), 200, latency_ms, retry_count, None

            if resp.status_code == 503 and attempt < max_retries:
                wait = float(resp.headers.get("Retry-After", retry_backoff_base * (2 ** attempt)))
                log.warning("503 — retrying in %.1fs (attempt %d/%d)", wait, attempt + 1, max_retries)
                time.sleep(wait)
                retry_count += 1
                continue

            return None, resp.status_code, latency_ms, retry_count, resp.text[:500]

        except requests.Timeout:
            latency_ms = (time.monotonic() - t0) * 1000.0
            if attempt < max_retries:
                time.sleep(retry_backoff_base * (2 ** attempt))
                retry_count += 1
                continue
            return None, None, latency_ms, retry_count, f"Timeout after {timeout}s"

        except requests.RequestException as e:
            latency_ms = (time.monotonic() - t0) * 1000.0
            if attempt < max_retries:
                time.sleep(retry_backoff_base * (2 ** attempt))
                retry_count += 1
                continue
            return None, None, latency_ms, retry_count, str(e)

    latency_ms = (time.monotonic() - t0) * 1000.0
    return None, 503, latency_ms, retry_count, "Max retries exceeded"


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

def check_server_health(server_url: str, timeout: int = 10) -> bool:
    try:
        resp = requests.get(f"{server_url}/health", timeout=timeout)
        if resp.status_code == 200:
            data = resp.json()
            status = data.get("status", "unknown")
            log.info("Server health: %s | models_loaded: %s", status, data.get("models_loaded"))
            if status == "unavailable":
                log.error("Server reports 'unavailable' — B2 data may be missing")
                return False
            return True
        log.error("Health check returned HTTP %d", resp.status_code)
        return False
    except Exception as e:
        log.error("Cannot reach server at %s: %s", server_url, e)
        return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Run model server backtest simulation")
    parser.add_argument("--config", default=str(BASE_DIR / "config" / "backtest_config.yaml"))
    parser.add_argument("--resume", action="store_true",
                        help="Resume from last completed step (skip already-logged steps)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print first 3 request bodies then exit")
    args = parser.parse_args()

    cfg         = load_config(Path(args.config))
    server_url  = cfg["server_url"].rstrip("/")
    strategy    = cfg.get("strategy", "default")
    api_key     = os.environ.get("MODEL_API_KEY") or cfg.get("api_key")
    initial_cap = cfg.get("initial_capital_usd", 1000.0)
    cadence_h   = cfg.get("cadence_hours", 1)
    max_retries = cfg.get("max_retries", 3)
    backoff     = cfg.get("retry_backoff_base", 1.0)
    timeout     = cfg.get("request_timeout", 30)

    if cadence_h <= 0:
        log.error("cadence_hours must be > 0, got: %s", cadence_h)
        sys.exit(1)

    results_dir = BASE_DIR / cfg.get("output_dir", "results")
    results_dir.mkdir(parents=True, exist_ok=True)

    log_path   = results_dir / "inference_log.csv"
    trace_path = results_dir / "trace_df.parquet"

    # ------------------------------------------------------------------
    # Server health check
    # ------------------------------------------------------------------
    if not args.dry_run:
        log.info("Checking server health at %s ...", server_url)
        if not check_server_health(server_url):
            log.error("Model server is not reachable. Start it with:")
            log.error("  cd C:/Coding/llaminet/model && uvicorn app.main:app --port 4001")
            sys.exit(1)

    # ------------------------------------------------------------------
    # Build hourly timestamps
    # ------------------------------------------------------------------
    try:
        start_dt = parse_config_date(cfg["start_date"], "start_date")
        end_dt = parse_config_date(cfg["end_date"], "end_date") + timedelta(days=1)
    except (KeyError, TypeError, ValueError) as e:
        log.error("Invalid date config: %s", e)
        sys.exit(1)
    if start_dt >= end_dt:
        log.error("Invalid date range: start_date must be before end_date")
        sys.exit(1)

    timestamps = []
    t = start_dt
    while t < end_dt:
        timestamps.append(t)
        t += timedelta(hours=cadence_h)

    log.info("Steps: %d  (%s → %s)", len(timestamps), timestamps[0], timestamps[-1])

    # ------------------------------------------------------------------
    # Load raw swap data for realistic fee computation
    # ------------------------------------------------------------------
    decimals0 = cfg.get("decimals0", 18)
    decimals1 = cfg.get("decimals1", 6)
    raw_swap_dir = BASE_DIR / "data" / "raw_swaps"

    if not args.dry_run:
        log.info("Loading raw swap data for realistic fee computation...")
        swap_data = HourlySwapData.from_raw_parquet(
            raw_swap_dir, start_dt, end_dt - timedelta(days=1),
            decimals0=decimals0, decimals1=decimals1,
        )
    else:
        swap_data = HourlySwapData(decimals0, decimals1)

    # ------------------------------------------------------------------
    # Resume: find last completed step
    # ------------------------------------------------------------------
    start_step = 0
    existing_log_rows: list[dict] = []
    existing_trace_rows: list[dict] = []

    if args.resume and log_path.exists():
        log_df = pd.read_csv(log_path)
        trace_df = pd.read_parquet(trace_path) if trace_path.exists() else pd.DataFrame()
        if not trace_df.empty:
            start_step = int(trace_df["step"].max()) + 1
            existing_trace_rows = trace_df.to_dict("records")
            if not log_df.empty:
                existing_log_rows = log_df[log_df["step"] < start_step].to_dict("records")
            log.info("Resuming from step %d", start_step)
        elif not log_df.empty:
            log.warning(
                "--resume requested but %s is missing/empty; starting from step 0",
                trace_path,
            )

    # ------------------------------------------------------------------
    # Initialise simulation state
    # ------------------------------------------------------------------
    if existing_trace_rows:
        last = existing_trace_rows[-1]
        state = {
            "has_position":          bool(last.get("has_position", False)),
            "width":                 last.get("width"),
            "lower_tick":            last.get("lower_tick"),
            "upper_tick":            last.get("upper_tick"),
            "price_lower":           last.get("price_lower"),
            "price_upper":           last.get("price_upper"),
            "entry_price":           last.get("current_price"),
            "liquidity":             last.get("liquidity", 0.0),
            "portfolio_value_usd":   last.get("portfolio_value", initial_cap),
            "initial_capital_usd":   initial_cap,
            "hours_since_rebalance": last.get("hours_since_rebalance", 0.0),
            "position_state":        last.get("position_state", "cash"),
            "current_price":         last.get("current_price", 0.0),
            "accumulated_fees":      0.0,
            "cumulative_hedge_pnl":  0.0,
            "cumulative_funding":    0.0,
        }
        if state["width"] is None and state["has_position"]:
            state["width"] = infer_width_from_state(state, cfg.get("tick_spacing", 10))
    else:
        state = {
            "has_position":          False,
            "width":                 None,
            "lower_tick":            None,
            "upper_tick":            None,
            "price_lower":           None,
            "price_upper":           None,
            "entry_price":           None,
            "liquidity":             0.0,
            "portfolio_value_usd":   initial_cap,
            "initial_capital_usd":   initial_cap,
            "hours_since_rebalance": 0.0,
            "position_state":        "cash",
            "current_price":         0.0,
            "accumulated_fees":      0.0,
            "cumulative_hedge_pnl":  0.0,
            "cumulative_funding":    0.0,
        }

    trace_rows: list[dict] = list(existing_trace_rows)
    log_rows:   list[dict] = list(existing_log_rows)
    fatal_error = False

    # ------------------------------------------------------------------
    # CSV log writer (append mode when resuming)
    # ------------------------------------------------------------------
    LOG_FIELDS = [
        "step", "timestamp", "reference_date", "status_code", "latency_ms",
        "retry_count", "error_detail", "action", "raw_action_label", "action_label",
        "current_price", "price_source", "data_age_seconds", "data_latest_utc",
        "ohlcv_rows", "lp_range_json",
    ]

    log_file_mode = "a" if args.resume and log_path.exists() else "w"
    log_fh = open(log_path, log_file_mode, newline="", encoding="utf-8")
    log_writer = csv.DictWriter(log_fh, fieldnames=LOG_FIELDS, extrasaction="ignore")
    if log_file_mode == "w":
        log_writer.writeheader()

    # ------------------------------------------------------------------
    # Simulation loop
    # ------------------------------------------------------------------
    prev_price = state["current_price"]

    try:
        for step_idx, ts in enumerate(timestamps):
            if step_idx < start_step:
                continue

            # Send full ISO datetime so the model server truncates candles
            # at this exact hour (no future data leak).
            reference_date = ts.strftime("%Y-%m-%dT%H:%M:%S")

            # Tick hsr for any surviving position BEFORE building the body so
            # the policy sees `hours = idx - position_entry_idx` (matches the
            # training env). simulate_step then uses this value as-is.
            if state.get("has_position") and step_idx > 0:
                state["hours_since_rebalance"] = (
                    state.get("hours_since_rebalance", 0.0) + 1.0
                )

            # Build request — include caller-computed observation features
            ncr = 0.0
            tir = 0.0
            if state["has_position"]:
                acc_fees = state.get("accumulated_fees", 0.0)
                acc_fund = state.get("cumulative_funding", 0.0)
                ncr = (acc_fees - acc_fund) / max(initial_cap, 1.0)
                if state["lower_tick"] is not None and step_idx > 0:
                    prev_hour = pd.Timestamp(timestamps[step_idx - 1], tz="UTC").floor("h")
                    tir = compute_time_in_range_for_hour(
                        swap_data, prev_hour,
                        int(state["lower_tick"]), int(state["upper_tick"]),
                    )

            body: dict = {
                "has_position":          state["has_position"],
                "portfolio_value_usd":   state["portfolio_value_usd"],
                "initial_capital_usd":   state["initial_capital_usd"],
                "hours_since_rebalance": state["hours_since_rebalance"],
                "reference_date":        reference_date,
                "current_width":         state.get("width"),
                "net_carry_ratio":       ncr,
                "time_in_range":         tir,
            }
            if state["has_position"] and state["lower_tick"] is not None:
                body["lower_tick"] = int(state["lower_tick"])
                body["upper_tick"] = int(state["upper_tick"])

            if args.dry_run:
                print(f"Step {step_idx} [{ts.isoformat()}]: {json.dumps(body, indent=2)}")
                if step_idx >= start_step + 2:
                    print("... (dry-run: showing first 3 steps only)")
                    break
                continue

            # Call model server
            resp_data, status_code, latency_ms, retry_count, error_detail = call_infer(
                server_url, strategy, api_key, body, max_retries, backoff, timeout
            )

            # Log HTTP observability
            log_row = {
                "step":            step_idx,
                "timestamp":       ts.isoformat(),
                "reference_date":  reference_date,
                "status_code":     status_code,
                "latency_ms":      round(latency_ms, 1),
                "retry_count":     retry_count,
                "error_detail":    error_detail or "",
                "action":          resp_data.get("action")          if resp_data else None,
                "raw_action_label":(
                    (resp_data.get("action_label") or resp_data.get("action"))
                    if resp_data else None
                ),
                "action_label":    None,
                "current_price":   resp_data.get("current_price")   if resp_data else None,
                "price_source":    resp_data.get("price_source")    if resp_data else None,
                "data_age_seconds":resp_data.get("data_age_seconds")if resp_data else None,
                "data_latest_utc": resp_data.get("data_latest_utc") if resp_data else None,
                "ohlcv_rows":      resp_data.get("ohlcv_rows")      if resp_data else None,
                "lp_range_json":   json.dumps(resp_data.get("lp_range")) if resp_data else None,
            }
            if resp_data is None:
                log.error("Step %d [%s] FAILED: HTTP %s — %s", step_idx, ts, status_code, error_detail)
                if status_code in (400, 401, 404, 422):
                    log.error(
                        "Non-retryable inference error (%s). Check strategy/API key/request payload.",
                        status_code,
                    )
                    if status_code == 401:
                        log.error(
                            "Authentication failed for /infer. Set a valid API key in "
                            "config (api_key) or MODEL_API_KEY env var."
                        )
                    fatal_error = True
                    break
                # On failure: treat as HOLD (no position change)
                action_label = "HOLD"
                lp_range     = None
                log_row["action_label"] = action_label
                log_row["lp_range_json"] = None
                if prev_price > 0:
                    current_price = prev_price
                else:
                    log.error(
                        "No valid fallback price available at step %d; aborting run to avoid corrupt simulation.",
                        step_idx,
                    )
                    fatal_error = True
                    break
            else:
                raw_action_label = resp_data.get("action_label") or resp_data.get("action") or "HOLD"
                current_price = resp_data["current_price"]
                current_width = state.get("width") or infer_width_from_state(
                    state, cfg.get("tick_spacing", 10)
                )
                action_label, requested_width = normalize_action_label(
                    raw_action_label,
                    current_width=current_width,
                )
                lp_range = (
                    compute_lp_range_from_width(
                        current_price,
                        requested_width,
                        cfg.get("tick_spacing", 10),
                    )
                    if requested_width
                    else None
                )
                log_row["action_label"] = action_label
                log_row["lp_range_json"] = json.dumps(lp_range) if lp_range else None

                log.info(
                    "Step %4d [%s] → %-10s  raw=%-18s price=$%.2f  latency=%.0fms  pv=$%.2f",
                    step_idx, ts.strftime("%Y-%m-%d %H:00"),
                    action_label, raw_action_label, current_price, latency_ms,
                    state["portfolio_value_usd"],
                )

            log_writer.writerow(log_row)
            log_rows.append(log_row)

            # Simulate portfolio step
            state, step_record = simulate_step(
                step_idx=step_idx,
                prev_price=prev_price,
                current_price=current_price,
                timestamp=ts,
                action_label=action_label,
                lp_range=lp_range,
                prev_state=state,
                cfg=cfg,
                swap_data=swap_data,
            )

            trace_rows.append(step_record)
            prev_price = current_price

            # Checkpoint every 24 steps (once per day)
            if step_idx % 24 == 0 and step_idx > start_step:
                log_fh.flush()
                _save_trace(trace_rows, trace_path)

    finally:
        log_fh.close()

    if not args.dry_run:
        _save_trace(trace_rows, trace_path)
        log.info("Done. trace_df saved to %s (%d rows)", trace_path, len(trace_rows))
        log.info("inference_log saved to %s (%d rows)", log_path, len(log_rows))
        _print_pnl_debug_summary(trace_rows)
        if fatal_error:
            sys.exit(1)
        log.info("Run 04_compute_metrics.py next.")


def _save_trace(rows: list[dict], path: Path) -> None:
    df = pd.DataFrame(rows)
    if not df.empty:
        df.to_parquet(path, index=False)


def _print_pnl_debug_summary(rows: list[dict]) -> None:
    """Break down PnL components by position_state to surface what's dominating."""
    if not rows:
        return
    df = pd.DataFrame(rows)
    numeric_cols = [
        "fee_usd", "funding_cost_usd", "tx_cost_usd",
        "lp_value_change_usd", "hedge_pnl_usd", "swing_pnl_usd",
        "net_after_tx_usd", "dbg_liquidity_share", "dbg_pool_L_median",
        "dbg_L_raw", "dbg_hourly_volume_usd", "dbg_num_swaps",
    ]
    for c in numeric_cols:
        if c not in df.columns:
            df[c] = 0.0

    log.info("=" * 78)
    log.info("PnL DEBUG SUMMARY  (per position_state, totals in USD)")
    log.info("=" * 78)

    totals = {
        "fee":     df["fee_usd"].sum(),
        "swing":   df["swing_pnl_usd"].sum(),
        "funding": df["funding_cost_usd"].sum(),
        "tx":      df["tx_cost_usd"].sum(),
        "net":     df["net_after_tx_usd"].sum(),
    }
    log.info(
        "TOTAL   steps=%4d  fee=%+8.4f  swing=%+8.4f  funding=%+8.4f  "
        "tx=%+8.4f  net=%+8.4f",
        len(df), totals["fee"], totals["swing"],
        -totals["funding"], -totals["tx"], totals["net"],
    )

    for state, grp in df.groupby("position_state"):
        log.info(
            "[%-11s] n=%4d  fee=%+8.4f  swing=%+8.4f  funding=%+8.4f  "
            "tx=%+8.4f  net=%+8.4f",
            state, len(grp),
            grp["fee_usd"].sum(), grp["swing_pnl_usd"].sum(),
            -grp["funding_cost_usd"].sum(), -grp["tx_cost_usd"].sum(),
            grp["net_after_tx_usd"].sum(),
        )

    # In-range diagnostics only (liquidity share is meaningful only with a live position)
    in_range = df[df["position_state"] == "lp_in_range"]
    if not in_range.empty:
        ls = in_range["dbg_liquidity_share"]
        vol = in_range["dbg_hourly_volume_usd"]
        pool_L = in_range["dbg_pool_L_median"]
        nsw = in_range["dbg_num_swaps"]
        log.info("-" * 78)
        log.info("In-range hours only (n=%d):", len(in_range))
        log.info(
            "  liquidity_share:  min=%.2e  median=%.2e  max=%.2e",
            ls.min(), ls.median(), ls.max(),
        )
        log.info(
            "  pool_L (median):  min=%.2e  median=%.2e  max=%.2e",
            pool_L.min(), pool_L.median(), pool_L.max(),
        )
        log.info(
            "  hourly volume:    min=$%.0f   median=$%.0f   max=$%.0f",
            vol.min(), vol.median(), vol.max(),
        )
        log.info(
            "  swaps per hour:   min=%d      median=%d      max=%d",
            int(nsw.min()), int(nsw.median()), int(nsw.max()),
        )
        log.info(
            "  fee per hour:     min=$%.6f  median=$%.6f  max=$%.6f",
            in_range["fee_usd"].min(),
            in_range["fee_usd"].median(),
            in_range["fee_usd"].max(),
        )
        # Expected-vs-actual sanity: fee ≈ volume × pool_fee × liquidity_share
        expected_hourly_fee = (vol * 0.0005 * ls).median()
        log.info(
            "  expected fee/hr (vol×0.0005×LS median): $%.6f  "
            "(actual median: $%.6f)",
            expected_hourly_fee, in_range["fee_usd"].median(),
        )
    log.info("=" * 78)


if __name__ == "__main__":
    main()
