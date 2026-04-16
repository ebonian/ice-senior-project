# uniswap_v3_ppo_paper.py
"""
Uniswap v3 PPO Training - Paper-Based Approach (Exact Per-Swap)

Implements the methodology from:
  Xu & Brini (2025) - "Improving DeFi Accessibility through Efficient Liquidity
                       Provisioning with Deep Reinforcement Learning" (AAAI 2025)
  arXiv:2501.07508

Key features:
1. EXACT per-swap fee calculation (summing Equations 5-6 over all swaps per hour)
2. HODL benchmark reward: R = (ΔV_LP - ΔV_HODL) + fees - gas - swap_fees
   Subsumes LVR when in-range, correctly penalizes OOR via actual value divergence
3. Hourly decision steps with swap-level fee accuracy
4. State space: 45-dim (33 tech features + 12 position features)
5. Continuous action space: tick widths for LP interval
"""

import os
import math
import glob
from typing import List, Tuple, Optional, Dict
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

import gymnasium as gym
from gymnasium import spaces

from stable_baselines3 import PPO
from stable_baselines3.common.vec_env import DummyVecEnv, SubprocVecEnv, VecNormalize
from stable_baselines3.common.callbacks import EvalCallback, CheckpointCallback

Q96 = 2 ** 96

# v3-core tick bounds (TickMath.MIN_TICK / MAX_TICK), aligned to tick_spacing=10
MIN_TICK = -887270
MAX_TICK = 887270


def sqrt_price_x96_to_price(sqrt_price_x96: int, decimals0: int, decimals1: int) -> float:
    """Convert Uniswap v3 sqrtPriceX96 to human-readable price."""
    p = float(sqrt_price_x96) / Q96
    return (p * p) * (10 ** (decimals0 - decimals1))


def price_to_tick(price: float) -> int:
    """
    Convert price to tick index (Equation 1 from paper).
    i = floor(log(p_t) / log(1.0001))
    """
    if price <= 0:
        return 0
    return int(math.floor(math.log(price) / math.log(1.0001)))


def tick_to_price(tick: int) -> float:
    """Convert tick index to price: p(i) = 1.0001^i"""
    return math.pow(1.0001, tick)


def human_tick_to_v3_tick(human_tick: int, decimals0: int, decimals1: int) -> int:
    """Convert human-price tick to v3-core raw-price tick.

    Our environment uses human-readable prices (e.g. ETH/USDT = 2500),
    while v3-core uses raw token ratios (token1_raw / token0_raw).
    The offset is: round((decimals0 - decimals1) * log(10) / log(1.0001)).
    For WETH(18)/USDT(6): offset = +276324.
    """
    offset = int(round((decimals0 - decimals1) * math.log(10) / math.log(1.0001)))
    return human_tick - offset


def v3_tick_to_human_tick(v3_tick: int, decimals0: int, decimals1: int) -> int:
    """Convert v3-core raw-price tick to human-price tick.

    Inverse of human_tick_to_v3_tick. See that function for details.
    """
    offset = int(round((decimals0 - decimals1) * math.log(10) / math.log(1.0001)))
    return v3_tick + offset


def _tick_in_range_fraction(tick_before: int, tick_after: int,
                            lp_lower_tick: int, lp_upper_tick: int) -> float:
    """
    Fraction of a swap's tick span that falls within the LP range.
    Uses exact integer tick-span overlap (no floating-point approximation).
    v3-core: fee accrual stops at tick boundaries; this computes how much of
    the swap's traversal occurred within [lp_lower_tick, lp_upper_tick].
    Returns float in [0.0, 1.0].
    """
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


# =============================================================================
# Technical Indicators (from Zhang et al. 2023, Table 2)
# =============================================================================

# 22 original technical + 9 trend + 2 fast regime = 33 features
FEATURE_COLS = [
    # Original technical features (22)
    'high_open_ratio', 'low_open_ratio', 'close_open_ratio',
    'dema_ratio', 'momentum_12', 'roc_12', 'atr_14', 'natr_14',
    'adx_14', 'plus_di', 'minus_di', 'cci_20', 'rsi_14',
    'macd', 'macd_signal', 'macd_hist',
    'bb_upper', 'bb_lower', 'bb_width',
    'stoch_k', 'stoch_d', 'volume_sma_ratio',
    # Trend features (9) - critical for directional positioning
    'return_1h', 'return_24h', 'return_7d',
    'price_vs_ma50', 'price_vs_ma200', 'ma50_vs_ma200',
    'market_regime',  # -1 bear, 0 sideways, +1 bull
    'trend_strength_24h', 'trend_strength_7d',
    # Fast regime features (2) - faster confirmation than 7d market_regime
    'regime_fast',   # +1 bull / 0 sideways / -1 bear based on 24h return ±1.5%
    'vol_regime',    # 1.0 = high vol (natr_14 > 0.5%), 0.0 = low vol
]
assert len(FEATURE_COLS) == 33, f"Expected 33 features, got {len(FEATURE_COLS)}"

# Discrete width set for action mapping (Fix 2: reduces action precision requirements)
# Each width gets ~6.7% of action range (vs 1.5% with 40 linear widths)
WIDTH_SET = [1, 2, 4, 6, 10, 15, 20, 30, 40]


def compute_technical_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute technical indicators from OHLCV data.
    Based on Zhang et al. (2023) Table 2 - 31 features.
    """
    if 'close' not in df.columns:
        return df

    close = df['close'].values
    high = df['high'].values if 'high' in df.columns else close
    low = df['low'].values if 'low' in df.columns else close
    open_price = df['open'].values if 'open' in df.columns else close
    volume = df['volume'].values if 'volume' in df.columns else np.ones_like(close)

    n = len(close)

    # Basic OHLC ratios (3 features)
    df['high_open_ratio'] = high / np.maximum(open_price, 1e-10)
    df['low_open_ratio'] = low / np.maximum(open_price, 1e-10)
    df['close_open_ratio'] = close / np.maximum(open_price, 1e-10)

    # Double Exponential Moving Average (DEMA)
    def ema(data, period):
        alpha = 2.0 / (period + 1)
        result = np.zeros_like(data, dtype=float)
        result[0] = data[0]
        for i in range(1, len(data)):
            result[i] = alpha * data[i] + (1 - alpha) * result[i - 1]
        return result

    ema_12 = ema(close, 12)
    ema_12_12 = ema(ema_12, 12)
    dema = 2 * ema_12 - ema_12_12
    df['dema_ratio'] = dema / np.maximum(open_price, 1e-10)

    # Momentum indicators (normalized as percentage change, not raw USD)
    momentum_12 = np.zeros(n)
    momentum_12[12:] = (close[12:] - close[:-12]) / np.maximum(close[:-12], 1e-10)
    df['momentum_12'] = momentum_12

    # Rate of Change (6-hour, distinct from 12-hour momentum above)
    roc_6 = np.zeros(n)
    roc_6[6:] = (close[6:] - close[:-6]) / np.maximum(close[:-6], 1e-10)
    df['roc_12'] = roc_6  # Keep column name for compatibility with trained models

    # Average True Range (ATR)
    tr = np.maximum(high - low,
                    np.maximum(np.abs(high - np.roll(close, 1)),
                               np.abs(low - np.roll(close, 1))))
    tr[0] = high[0] - low[0]
    atr_14_raw = pd.Series(tr).rolling(14, min_periods=1).mean().values
    df['natr_14'] = atr_14_raw / np.maximum(close, 1e-10)
    # Normalize atr_14 as percentage of price (raw USD saturates at clip=10)
    df['atr_14'] = df['natr_14']

    # Average Directional Index (ADX)
    plus_dm = np.maximum(high - np.roll(high, 1), 0)
    minus_dm = np.maximum(np.roll(low, 1) - low, 0)
    plus_dm[0] = 0
    minus_dm[0] = 0
    atr_smooth = ema(tr, 14)
    plus_di = 100 * ema(plus_dm, 14) / np.maximum(atr_smooth, 1e-10)
    minus_di = 100 * ema(minus_dm, 14) / np.maximum(atr_smooth, 1e-10)
    dx = 100 * np.abs(plus_di - minus_di) / np.maximum(plus_di + minus_di, 1e-10)
    df['adx_14'] = ema(dx, 14) / 100.0
    df['plus_di'] = plus_di / 100.0
    df['minus_di'] = minus_di / 100.0

    # Commodity Channel Index (CCI)
    typical_price = (high + low + close) / 3.0
    tp_sma = pd.Series(typical_price).rolling(20, min_periods=1).mean().values
    tp_mad = pd.Series(typical_price).rolling(20, min_periods=1).apply(
        lambda x: np.mean(np.abs(x - x.mean())), raw=True
    ).fillna(1).values
    df['cci_20'] = (typical_price - tp_sma) / np.maximum(0.015 * tp_mad, 1e-10) / 200.0

    # Relative Strength Index (RSI)
    delta = np.diff(close, prepend=close[0])
    gain = np.where(delta > 0, delta, 0)
    loss = np.where(delta < 0, -delta, 0)
    avg_gain = ema(gain, 14)
    avg_loss = ema(loss, 14)
    rs = avg_gain / np.maximum(avg_loss, 1e-10)
    df['rsi_14'] = 1 - 1 / (1 + rs)

    # MACD
    ema_12_close = ema(close, 12)
    ema_26_close = ema(close, 26)
    macd = ema_12_close - ema_26_close
    signal = ema(macd, 9)
    df['macd'] = macd / np.maximum(close, 1e-10)
    df['macd_signal'] = signal / np.maximum(close, 1e-10)
    df['macd_hist'] = (macd - signal) / np.maximum(close, 1e-10)

    # Bollinger Bands
    sma_20 = pd.Series(close).rolling(20, min_periods=1).mean().values
    std_20 = pd.Series(close).rolling(20, min_periods=1).std().fillna(0).values
    df['bb_upper'] = (sma_20 + 2 * std_20) / np.maximum(close, 1e-10)
    df['bb_lower'] = (sma_20 - 2 * std_20) / np.maximum(close, 1e-10)
    df['bb_width'] = (4 * std_20) / np.maximum(close, 1e-10)

    # Stochastic Oscillator
    low_14 = pd.Series(low).rolling(14, min_periods=1).min().values
    high_14 = pd.Series(high).rolling(14, min_periods=1).max().values
    df['stoch_k'] = (close - low_14) / np.maximum(high_14 - low_14, 1e-10)
    df['stoch_d'] = pd.Series(df['stoch_k']).rolling(3, min_periods=1).mean().values

    # Volume indicator
    df['volume_sma_ratio'] = volume / np.maximum(
        pd.Series(volume).rolling(20, min_periods=1).mean().values, 1e-10
    )

    # ==== Trend features (9) ====

    # Price returns over different horizons
    return_1h = np.zeros(n)
    return_1h[1:] = (close[1:] - close[:-1]) / np.maximum(close[:-1], 1e-10)
    df['return_1h'] = return_1h

    return_24h = np.zeros(n)
    return_24h[24:] = (close[24:] - close[:-24]) / np.maximum(close[:-24], 1e-10)
    df['return_24h'] = return_24h

    return_7d = np.zeros(n)
    return_7d[168:] = (close[168:] - close[:-168]) / np.maximum(close[:-168], 1e-10)
    df['return_7d'] = return_7d

    # Moving average trend signals
    ma_50 = pd.Series(close).rolling(50, min_periods=1).mean().values
    ma_200 = pd.Series(close).rolling(200, min_periods=1).mean().values
    df['price_vs_ma50'] = (close - ma_50) / np.maximum(ma_50, 1e-10)
    df['price_vs_ma200'] = (close - ma_200) / np.maximum(ma_200, 1e-10)
    df['ma50_vs_ma200'] = (ma_50 - ma_200) / np.maximum(ma_200, 1e-10)

    # Market regime (-1 bear, 0 sideways, +1 bull) based on 7-day return
    regime = np.zeros(n)
    for i in range(168, n):
        denom = max(close[i - 168], 1e-10)
        ret_7d = (close[i] - close[i - 168]) / denom
        if ret_7d > 0.03:
            regime[i] = 1.0
        elif ret_7d < -0.03:
            regime[i] = -1.0
    df['market_regime'] = regime

    # Trend strength
    df['trend_strength_24h'] = np.abs(df['return_24h'])
    df['trend_strength_7d'] = np.abs(df['return_7d'])

    # Fast regime: 24h return threshold ±1.5% (confirms in 24h vs 168h for market_regime)
    regime_fast = np.zeros(n)
    for i in range(24, n):
        denom = max(close[i - 24], 1e-10)
        ret_24h = (close[i] - close[i - 24]) / denom
        if ret_24h > 0.015:
            regime_fast[i] = 1.0
        elif ret_24h < -0.015:
            regime_fast[i] = -1.0
    df['regime_fast'] = regime_fast

    # Vol regime: natr_14 > 0.5% = high vol (wide width appropriate)
    df['vol_regime'] = (df['natr_14'] > 0.005).astype(float)

    df = df.fillna(0)
    return df


@dataclass
class HourlyData:
    """Hourly resampled data for training (paper approach)."""
    timestamps: List[pd.Timestamp]
    prices: Dict[pd.Timestamp, float]  # hourly close price
    volumes: Dict[pd.Timestamp, float]  # hourly swap volume in USD
    volatilities: Dict[pd.Timestamp, float]  # exponentially weighted volatility
    ma_24h: Dict[pd.Timestamp, float]  # 24-hour moving average
    ma_168h: Dict[pd.Timestamp, float]  # 168-hour (1 week) moving average
    decimals0: int
    decimals1: int
    pool_fee: float  # δ in paper (e.g. 0.003 for 0.3%)
    tick_spacing: int
    # Per-swap prices for each hour, precomputed from swap-level data.
    # Used for exact per-swap fee calculation following Zhang et al. (2023).
    swap_prices_per_hour: Optional[Dict[pd.Timestamp, np.ndarray]] = None
    # Per-swap USD volumes (|amount1| / 10^decimals1) for each hour.
    # Used for direct v3-core fee formula: fee_i = volume_i × pool_fee × liquidity_share × in_range_fraction.
    # More accurate than |Δ√p| proxy in stable periods (high volume, small price moves).
    swap_amounts_per_hour: Optional[Dict[pd.Timestamp, np.ndarray]] = None
    # Median pool active liquidity per hour (raw v3-core units from swap events).
    # Used to compute liquidity share: fees_ours = fees_pool × (L_ours / L_pool).
    pool_liquidity_per_hour: Optional[Dict[pd.Timestamp, float]] = None
    # Per-swap pool active liquidity (raw v3-core units, one per swap per hour).
    # Eliminates the hourly-median approximation in liquidity_share computation.
    swap_liquidity_per_hour: Optional[Dict[pd.Timestamp, np.ndarray]] = None
    # Per-swap pool tick after each swap, in human-readable tick space.
    # Enables exact integer tick-span in-range fraction (replaces |Δ√p| proxy).
    swap_ticks_per_hour: Optional[Dict[pd.Timestamp, np.ndarray]] = None
    # Per-swap elapsed seconds from the hour start.
    # Enables finer intrahour hedge/funding approximation.
    swap_time_seconds_per_hour: Optional[Dict[pd.Timestamp, np.ndarray]] = None
    # 31-dim technical indicator features per timestamp (enables 39-dim obs mode)
    features: Optional[Dict[pd.Timestamp, np.ndarray]] = None
    # Hourly high/low prices (for intra_hour_rvol observation feature)
    hourly_high: Optional[Dict[pd.Timestamp, float]] = None
    hourly_low:  Optional[Dict[pd.Timestamp, float]] = None
    # Internal caches shared across env instances that reuse the same HourlyData.
    _fee_path_cache: Dict[Tuple[int, int, int], Dict[str, np.ndarray | float | str]] = field(
        default_factory=dict,
        repr=False,
    )
    _active_hedge_cache: Dict[Tuple[int, int, int], Tuple[float, float]] = field(
        default_factory=dict,
        repr=False,
    )


def prepare_hourly_data(data_dir: str) -> HourlyData:
    """
    Prepare hourly resampled data (paper methodology).
    Resamples swap data to hourly OHLCV format.
    """
    print("🔄 Preparing hourly data (paper methodology)...")
    
    # Load data files
    pool_cfg = pd.read_csv(os.path.join(data_dir, "pool_config_eth_usdt_0p3.csv"))
    tokens = pd.read_csv(os.path.join(data_dir, "token_metadata_eth_usdt_0p3.csv"))
    swaps_files = glob.glob(os.path.join(data_dir, "swaps_*_eth_usdt_0p3.csv"))
    
    if not swaps_files:
        raise FileNotFoundError(f"Missing swaps_*_eth_usdt_0p3.csv in {data_dir}")
    
    swaps = pd.read_csv(swaps_files[0], low_memory=False)
    
    # Get token decimals
    tokens['contract_address'] = tokens['contract_address'].str.lower()
    t0_addr = pool_cfg.loc[0, 'token0'].lower()
    t1_addr = pool_cfg.loc[0, 'token1'].lower()
    t0 = tokens.set_index('contract_address').loc[t0_addr]
    t1 = tokens.set_index('contract_address').loc[t1_addr]
    decimals0 = int(t0['decimals'])
    decimals1 = int(t1['decimals'])
    
    # Pool parameters
    pool_fee_bps = int(pool_cfg.loc[0, 'fee'])
    pool_fee = pool_fee_bps / 1_000_000  # e.g. 3000 -> 0.003 (0.3%)
    tick_spacing = int(pool_cfg.loc[0, 'tickSpacing'])
    
    print(f"  Pool fee: {pool_fee*100:.2f}% ({pool_fee_bps} bps)")
    print(f"  Tick spacing: {tick_spacing}")
    
    # Parse timestamps and compute prices
    swaps['evt_block_time'] = pd.to_datetime(swaps['evt_block_time'], utc=True)
    swaps = swaps.sort_values('evt_block_time').reset_index(drop=True)
    swaps['price'] = swaps['sqrtPriceX96'].apply(
        lambda x: sqrt_price_x96_to_price(int(x), decimals0, decimals1)
    )
    swaps['volume_usd'] = swaps['amount1'].abs() / (10 ** decimals1)

    # Validate liquidity column exists (required for accurate fee share calculation)
    if 'liquidity' not in swaps.columns:
        raise ValueError(
            "Swap data missing 'liquidity' column. "
            "This is required for accurate fee share calculation (L_ours / L_pool). "
            "Re-export swap data with the liquidity field from Uniswap v3 swap events."
        )
    swaps['liquidity'] = swaps['liquidity'].astype(float)

    # Validate tick column exists (required for exact tick-based in-range fraction)
    if 'tick' not in swaps.columns:
        raise ValueError(
            "Swap data missing 'tick' column. "
            "This is required for exact tick-span in-range fraction computation. "
            "Re-export swap data with the tick field from Uniswap v3 swap events."
        )

    # Precompute per-swap prices and amounts for each hour from swap-level data.
    # Following Zhang et al. (2023): fees are summed over every swap per hour.
    # swap_amounts_per_hour stores |amount1| / 10^decimals1 (USD volume per swap).
    # v3-core traceability: fee_i = volume_i × pool_fee × (L_ours / L_pool) × in_range_fraction.
    swaps_indexed_for_prices = swaps.set_index('evt_block_time')
    swap_prices_per_hour_raw = {}
    swap_amounts_per_hour_raw = {}
    pool_liq_per_hour_raw = {}
    swap_liquidity_per_hour_raw = {}
    swap_ticks_per_hour_raw = {}
    swap_time_seconds_per_hour_raw = {}
    # Precompute once: decimals are pool constants, so the offset never changes per swap.
    tick_offset = int(round((decimals0 - decimals1) * math.log(10) / math.log(1.0001)))
    for hour, group in swaps_indexed_for_prices.groupby(pd.Grouper(freq='1h')):
        if len(group) >= 2:
            swap_prices_per_hour_raw[hour] = group['price'].values.astype(np.float64)
        elif len(group) == 1:
            swap_prices_per_hour_raw[hour] = group['price'].values.astype(np.float64)
        if len(group) > 0:
            pool_liq_per_hour_raw[hour] = group['liquidity'].median()
            # Per-swap USD volumes: |amount1| / 10^decimals1
            swap_amounts_per_hour_raw[hour] = (
                group['amount1'].abs() / (10 ** decimals1)
            ).values.astype(np.float64)
            # Per-swap pool active liquidity (exact, eliminates hourly-median approximation)
            swap_liquidity_per_hour_raw[hour] = group['liquidity'].values.astype(np.float64)
            # Per-swap tick: vectorized add of precomputed offset (v3→human conversion)
            swap_ticks_per_hour_raw[hour] = group['tick'].values.astype(np.int64) + tick_offset
            hour_start = pd.Timestamp(hour)
            swap_time_seconds_per_hour_raw[hour] = (
                (group.index - hour_start).total_seconds().to_numpy(dtype=np.float64)
            )
    
    # Resample to hourly OHLCV
    swaps.set_index('evt_block_time', inplace=True)
    hourly = swaps.resample('1h').agg({
        'price': ['first', 'last', 'max', 'min'],
        'volume_usd': 'sum'
    })
    hourly.columns = ['open', 'close', 'high', 'low', 'volume']
    hourly = hourly.dropna(subset=['close'])
    
    # Forward-fill missing hours (no swaps in that hour)
    full_range = pd.date_range(start=hourly.index.min(), end=hourly.index.max(), freq='1h', tz='UTC')
    hourly = hourly.reindex(full_range)
    hourly['close'] = hourly['close'].ffill()
    hourly['open'] = hourly['open'].ffill()
    hourly['high'] = hourly['high'].ffill()
    hourly['low'] = hourly['low'].ffill()
    hourly['volume'] = hourly['volume'].fillna(0)
    
    print(f"  📊 {len(hourly)} hourly candles")
    
    # Compute volatility (exponentially weighted std of log returns)
    # Paper uses smoothing factor α = 0.05
    hourly['log_return'] = np.log(hourly['close']).diff()
    hourly['volatility'] = hourly['log_return'].ewm(alpha=0.05, min_periods=1).std()
    hourly['volatility'] = hourly['volatility'].fillna(0)
    
    # Moving averages
    hourly['ma_24h'] = hourly['close'].rolling(window=24, min_periods=1).mean()
    hourly['ma_168h'] = hourly['close'].rolling(window=168, min_periods=1).mean()
    
    print(f"  📈 Computed volatility and moving averages")

    # Compute 31-dim technical indicators for extended observation space
    hourly = compute_technical_indicators(hourly)

    # Ensure all feature columns exist
    for col in FEATURE_COLS:
        if col not in hourly.columns:
            hourly[col] = 0.0

    print(f"  🧮 Computed {len(FEATURE_COLS)} technical features (22 original + 9 trend + 2 fast regime)")
    warmup_hours = 200  # ma_200 needs 200 hours to stabilize
    print(f"  ⚠️  Indicator warmup: first {warmup_hours} hours have partial lookback (ma_200)")

    # Convert to dictionaries for fast lookup
    timestamps = list(hourly.index)
    prices = hourly['close'].to_dict()
    volumes = hourly['volume'].to_dict()
    volatilities = hourly['volatility'].to_dict()
    ma_24h = hourly['ma_24h'].to_dict()
    ma_168h = hourly['ma_168h'].to_dict()
    hourly_high_dict = hourly['high'].to_dict()
    hourly_low_dict  = hourly['low'].to_dict()

    # Build 31-dim feature vectors per timestamp
    features = {}
    nan_count = 0
    for ts in timestamps:
        feat_vec = hourly.loc[ts, FEATURE_COLS].values.astype(np.float32)
        # No pre-clipping: VecNormalize handles normalization + clip_obs=10.0
        # Pre-clipping raw values destroyed the distribution before normalization
        if np.any(np.isnan(feat_vec)):
            nan_count += 1
            feat_vec = np.nan_to_num(feat_vec, nan=0.0)
        # Clip only extreme outliers (±1000) to prevent inf propagation
        feat_vec = np.clip(feat_vec, -1000, 1000)
        features[ts] = feat_vec
    if nan_count > 0:
        print(f"  ⚠️  Replaced NaN in {nan_count}/{len(timestamps)} feature vectors")

    # Map per-swap prices and amounts to the full (forward-filled) timestamp index
    swap_prices_per_hour = {}
    swap_amounts_per_hour = {}
    swap_liquidity_per_hour = {}
    swap_ticks_per_hour = {}
    swap_time_seconds_per_hour = {}
    for ts in timestamps:
        swap_prices_per_hour[ts] = swap_prices_per_hour_raw.get(ts, None)
        swap_amounts_per_hour[ts] = swap_amounts_per_hour_raw.get(ts, None)
        swap_liquidity_per_hour[ts] = swap_liquidity_per_hour_raw.get(ts, None)
        swap_ticks_per_hour[ts] = swap_ticks_per_hour_raw.get(ts, None)
        swap_time_seconds_per_hour[ts] = swap_time_seconds_per_hour_raw.get(ts, None)

    # Forward-fill pool liquidity across all hours
    pool_liquidity_per_hour = {}
    last_liq = None
    for ts in timestamps:
        liq = pool_liq_per_hour_raw.get(ts, None)
        if liq is not None:
            last_liq = liq
        pool_liquidity_per_hour[ts] = last_liq if last_liq is not None else 0.0

    print("✅ Data preparation complete!")

    return HourlyData(
        timestamps=timestamps,
        prices=prices,
        volumes=volumes,
        volatilities=volatilities,
        ma_24h=ma_24h,
        ma_168h=ma_168h,
        decimals0=decimals0,
        decimals1=decimals1,
        pool_fee=pool_fee,
        tick_spacing=tick_spacing,
        swap_prices_per_hour=swap_prices_per_hour,
        swap_amounts_per_hour=swap_amounts_per_hour,
        pool_liquidity_per_hour=pool_liquidity_per_hour,
        swap_liquidity_per_hour=swap_liquidity_per_hour,
        swap_ticks_per_hour=swap_ticks_per_hour,
        swap_time_seconds_per_hour=swap_time_seconds_per_hour,
        features=features,
        hourly_high=hourly_high_dict,
        hourly_low=hourly_low_dict,
    )


class UniswapV3PaperEnv(gym.Env):
    """
    Uniswap v3 LP environment following paper methodology (Reward v4).

    State space:
      Extended mode (default): 45-dim (33 tech features + 12 position features)
        Position features: capital_drawdown, width_normalized, in_range,
        position_value_ratio, realized_vol, dist_to_boundary, hours_since_rebalance,
        volume_per_tick, time_in_range_last_hour, dist_upper_sigma, dist_lower_sigma,
        intra_hour_rvol
      Legacy mode (fallback): 8-dim (log_price, tick, width, liquidity, vol, ma24, ma168, in_range)

    Action space (two scalars, 2-zone):
      - a[0] < hold_threshold (0.5):  HOLD existing LP position (no cost)
      - a[0] >= hold_threshold (0.5): DEPLOY new LP at current price with width from a[1]
      - a[1] in [0, 1]: width selection (0→W1, 1→W40, linear through WIDTH_SET)
      No BURN zone. Agent is always in LP (or redeploying LP). Agent starts with
      an auto-deployed W20 position; initial auto-deploy is always free.

    Reward (capital-normalized; delta-hedged LP P&L — maximize fee − IL − costs):
      HOLD in-range:  r_t = (ΔV_LP + hedge_pnl + fee − funding) / capital
        ΔV_LP = V_lp(price_t1) − V_lp(price_t0); hedge_pnl = −lp_delta_x × ΔP.
        ΔV_LP + hedge_pnl ≈ IL ≤ 0. Net signal: fee − IL − funding.
      HOLD OOR:       r_t = −(missed_fee + funding) / capital
        missed_fee = fee a position of current_width centered at price_t0 would earn.
        ΔV_LP = 0 when OOR at both t0 and t1 (position value is constant).
      DEPLOY:         r_t = (ΔV_LP + hedge_pnl + fee − gas − swap_fee − funding) / capital
        ΔV_LP = V_lp(price_t1, new_pos) − actual_capital (V_lp(t0) = capital by construction).
        fee uses next-hour swap data to avoid look-ahead bias.
      No BURN branch. No cash state.

    Gradient: agent maximises fee − IL − costs. Agent learns to balance range width
      (narrow = more fee concentration but more IL when in-range) vs OOR risk.
      OOR penalty (missed_fee) makes redeployment rational when price exits range.
    """

    metadata = {"render_modes": []}

    def __init__(
        self,
        hourly_data,  # HourlyData or HourlyDataExtended
        initial_capital_usd: float = 1000.0,  # $1,000 initial capital
        gas_cost_usd: float = 0.03,  # Arbitrum L2: burn + swap + mint ≈ 3 txs × ~$0.01
        mev_slippage_pct: float = 0.0001,  # MEV sandwich + slippage: ~0.01% of swap amount (Arbitrum L2)
        min_tick_width: int = 1,
        max_tick_width: int = 40,
        hold_threshold: float = 0.5,
        burn_threshold: float = 0.0,
        mode: str = "train",
        train_ratio: float = 0.8,
        val_ratio: float = 0.1,
        start_idx: Optional[int] = None,
        end_idx: Optional[int] = None,
        in_range_bonus_usd: float = 0.0,
        hedge_funding_rate_annual: float = 0.11,  # 11% APR; realistic ETH perpetual funding
        hedge_enabled: bool = True,  # False → unhedged LP reward (no hedge_pnl, no funding)
    ):
        super().__init__()

        self.hourly_data = hourly_data
        self.initial_capital = float(initial_capital_usd)
        self.gas_cost_usd = float(gas_cost_usd)
        self.mev_slippage_pct = float(mev_slippage_pct)
        self.in_range_bonus_usd = float(in_range_bonus_usd)
        self.hedge_funding_rate_annual = float(hedge_funding_rate_annual)
        self._funding_hr = self.hedge_funding_rate_annual / 8760.0
        self.hedge_enabled = hedge_enabled
        self.min_tick_width = min_tick_width
        self.max_tick_width = max_tick_width
        self.hold_threshold = hold_threshold
        self.burn_threshold = burn_threshold
        self.pool_fee = hourly_data.pool_fee
        self.tick_spacing = hourly_data.tick_spacing
        # Opportunity cost cap: max theoretical fee if position has 100% of pool liquidity for 1 hr.
        # Prevents extreme-volume spikes from destabilizing the PPO value function.
        self._missed_fee_cap = self.initial_capital * self.pool_fee

        # Split data: custom indices override mode-based split
        if start_idx is not None and end_idx is not None:
            self.timestamps = hourly_data.timestamps[start_idx:end_idx]
        else:
            # Default: 80/10/10 train/val/test
            n_total = len(hourly_data.timestamps)
            train_end = int(n_total * train_ratio)
            val_end = int(n_total * (train_ratio + val_ratio))

            if mode == "train":
                self.timestamps = hourly_data.timestamps[:train_end]
            elif mode == "eval":
                self.timestamps = hourly_data.timestamps[train_end:val_end]
            elif mode == "test":
                self.timestamps = hourly_data.timestamps[val_end:]
            else:
                self.timestamps = hourly_data.timestamps
        
        self.n_steps = len(self.timestamps) - 1  # Need t and t+1
        
        # Check if we have extended features (from HourlyDataExtended)
        self.has_extended_features = hasattr(hourly_data, 'features') and hourly_data.features is not None
        
        if self.has_extended_features:
            # 39-dim observation: 31 tech features + 8 position features
            # Position features:
            # 1. capital_drawdown (continuous: 1 - pos_value/capital)
            # 2. width_normalized
            # 3. in_range
            # 4. position_value_ratio
            # 5. realized_vol (6h realized volatility, replaces redundant price_momentum)
            # 6. dist_to_boundary (signed: positive in-range, negative OOR)
            # 7. hours_since_rebalance (normalized by 168h, not 24h)
            # 8. volume_per_tick (log-normalized volume density; signals narrow-range opportunity)
            n_tech_features = 33
            self.state_dim = n_tech_features + 12  # 33 tech + 12 position = 45-dim obs
            self.max_width = self.max_tick_width * self.tick_spacing
            self.observation_space = spaces.Box(
                low=-np.inf, high=np.inf,
                shape=(self.state_dim,), dtype=np.float32
            )
        else:
            # Legacy 8-dim observation (fallback)
            self.max_width = self.max_tick_width * self.tick_spacing
            self.observation_space = spaces.Box(
                low=np.array([-np.inf, -1e6, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], dtype=np.float32),
                high=np.array([np.inf, 1e6, 100.0, 10.0, 1.0, 2.0, 2.0, 1.0], dtype=np.float32),
            )
        
        # Continuous action space: [decision, width]
        self.action_space = spaces.Box(low=0.0, high=1.0, shape=(2,), dtype=np.float32)
        
        # Conversion: L_pool_raw = L_ours × 10^((d0+d1)/2) per v3-core unit analysis
        # Our L is in human-readable price units; pool's L from swap events is in raw units.
        self._liquidity_scale = 10 ** ((hourly_data.decimals0 + hourly_data.decimals1) / 2)

        # Episode state
        self._reset_state()

    def _reset_state(self):
        self.idx = 0
        self.has_lp = False
        self.lp_lower_tick = None
        self.lp_upper_tick = None
        self.lp_width_ticks = 0
        self.liquidity = 0.0  # L_t in paper
        self.entry_price = None
        self.initial_value_usd = None
        self.position_entry_idx = 0  # Track position age
        self.actual_capital = self.initial_capital
        self.accumulated_fees = 0.0  # v3-core tokensOwed: idle fees not yet collected
        self.cumulative_hedge_pnl = 0.0  # net hedge P&L (hedge_pnl − funding) since last MTM

    def _compute_value_per_L(self, price: float, lower_price: float, upper_price: float) -> float:
        """USD value per unit of liquidity for the 3-way price-range cases (v3-core math).

        Returns the capital needed to deploy 1 unit of L at the given price and range.
        Used to compute L = capital / value_per_L in both initial deploy and rebalance.
        """
        sqrt_p  = math.sqrt(price)
        sqrt_pl = math.sqrt(lower_price)
        sqrt_pu = math.sqrt(upper_price)
        if price <= lower_price:
            return (1.0 / sqrt_pl - 1.0 / sqrt_pu) * price
        elif price >= upper_price:
            return sqrt_pu - sqrt_pl
        else:
            return 2.0 * sqrt_p - price / sqrt_pu - sqrt_pl

    def _auto_deploy_initial_position(self):
        """Deploy a default W20 position at episode start (Fix 1: eliminates cold-start trap).

        No cost charged -- the agent starts already deployed.
        First decision becomes 'keep W20 or switch to different width'.
        """
        if self.idx >= len(self.timestamps):
            return
        price = self._get_price(self.timestamps[self.idx])
        if price <= 0:
            return

        default_width = 20  # W20 in tick_spacing units
        lower_tick, upper_tick = self._compute_position_bounds(price, default_width)
        lower_price = tick_to_price(lower_tick)
        upper_price = tick_to_price(upper_tick)

        value_per_L = self._compute_value_per_L(price, lower_price, upper_price)
        if value_per_L <= 0:
            return

        L = self.actual_capital / value_per_L
        self.has_lp = True
        self.liquidity = L
        self.lp_width_ticks = default_width * self.tick_spacing
        self.lp_lower_tick = lower_tick
        self.lp_upper_tick = upper_tick
        self.entry_price = price
        self.initial_value_usd = self.actual_capital
        self.position_entry_idx = self.idx

    def get_portfolio_value(self) -> float:
        """Compute actual portfolio value at current price.

        Returns the mark-to-market value of the LP position + accumulated fees
        + unrealized hedge P&L (cumulative_hedge_pnl).
        Agent is always in LP (no cash/burned state in Reward v4).
        """
        if self.idx >= len(self.timestamps):
            idx = len(self.timestamps) - 1
        else:
            idx = self.idx
        price = self._get_price(self.timestamps[idx])
        if price <= 0:
            return self.actual_capital

        if self.has_lp and self.liquidity > 0 and self.lp_lower_tick is not None:
            lp_lower_price = tick_to_price(self.lp_lower_tick)
            lp_upper_price = tick_to_price(self.lp_upper_tick)
            return self._compute_position_value(
                price, lp_lower_price, lp_upper_price, self.liquidity
            ) + self.accumulated_fees + (self.cumulative_hedge_pnl if self.hedge_enabled else 0.0)
        else:
            return self.actual_capital

    def _get_price(self, t: pd.Timestamp) -> float:
        return self.hourly_data.prices.get(t, 0.0)

    def _get_volatility(self, t: pd.Timestamp) -> float:
        return self.hourly_data.volatilities.get(t, 0.0)

    def _get_ma_24h(self, t: pd.Timestamp) -> float:
        return self.hourly_data.ma_24h.get(t, 0.0)

    def _get_ma_168h(self, t: pd.Timestamp) -> float:
        return self.hourly_data.ma_168h.get(t, 0.0)

    def _get_volume(self, t: pd.Timestamp) -> float:
        return self.hourly_data.volumes.get(t, 0.0)

    def _get_pool_liquidity(self, t: pd.Timestamp) -> float:
        """Get pool active liquidity in raw v3-core units for this hour."""
        if self.hourly_data.pool_liquidity_per_hour:
            return self.hourly_data.pool_liquidity_per_hour.get(t, 0.0)
        return 0.0

    def _compute_position_value(self, price: float, price_lower: float, price_upper: float, L: float) -> float:
        """
        Compute LP position value V_t(p_t) from Equation 15 (first part).
        V_t(p_t) = L_t * (2√p_t - p_t/√p_t^u - √p_t^l)  [when p ∈ [p_l, p_u]]
        """
        if L <= 0 or price <= 0:
            return 0.0
        
        sqrt_p = math.sqrt(price)
        sqrt_pl = math.sqrt(price_lower)
        sqrt_pu = math.sqrt(price_upper)
        
        if price <= price_lower:
            # All in X: value = x * price
            x = L * (1.0 / sqrt_pl - 1.0 / sqrt_pu)
            return x * price
        elif price >= price_upper:
            # All in Y: value = y
            y = L * (sqrt_pu - sqrt_pl)
            return y
        else:
            # In range: Equation 15
            return L * (2.0 * sqrt_p - price / sqrt_pu - sqrt_pl)


    def _compute_lp_delta(
        self,
        price: float,
        lower_price: Optional[float] = None,
        upper_price: Optional[float] = None,
        liquidity: Optional[float] = None,
    ) -> float:
        """
        ETH delta of LP position at given price — equals token0 (ETH) amount
        that would be extracted if the position were closed at `price`.

        v3-core reference: getAmount0Delta (SqrtPriceMath.sol).
        Corresponds to ∂V/∂p = x_amount for a Uniswap v3 position.

        Defaults to current active position state if range/liquidity not provided.
        """
        L = liquidity if liquidity is not None else self.liquidity
        if L <= 0:
            return 0.0
        p_l = lower_price if lower_price is not None else (
            tick_to_price(self.lp_lower_tick) if self.lp_lower_tick is not None else None
        )
        p_u = upper_price if upper_price is not None else (
            tick_to_price(self.lp_upper_tick) if self.lp_upper_tick is not None else None
        )
        if p_l is None or p_u is None:
            return 0.0

        sqrt_p  = math.sqrt(price)
        sqrt_pl = math.sqrt(p_l)
        sqrt_pu = math.sqrt(p_u)

        if price <= p_l:
            return L * (1.0 / sqrt_pl - 1.0 / sqrt_pu)
        elif price >= p_u:
            return 0.0
        else:
            return L * (1.0 / sqrt_p - 1.0 / sqrt_pu)

    def _compute_hour_hedge(self, price_t0, price_t1, lower_price, upper_price, liquidity):
        """Compute hedge P&L and funding cost for one hour. PURE — no side effects.

        hedge_enabled=True:  Returns hedge P&L and funding cost. Caller must
            explicitly accumulate to cumulative_hedge_pnl for capital tracking.
        hedge_enabled=False: Delta-neutral reward shaping — hedge_pnl cancels first-order
            directional exposure in the reward, leaving only fee + IL (second-order).
            No funding charged, no cumulative tracking (not a real position).

        Returns (hedge_pnl, funding_cost).

        Bug fix (2026-03-13): Removed side-effect mutation of cumulative_hedge_pnl.
        Previously, both the reward path (via return values) and the capital path
        (via cumulative_hedge_pnl) consumed hedge_pnl and funding_cost, causing
        double-counting of ~$85/episode (77% of the VRP edge).
        """
        lp_delta_x = self._compute_lp_delta(price_t0, lower_price, upper_price, liquidity)
        hedge_pnl = -lp_delta_x * (price_t1 - price_t0)
        if self.hedge_enabled:
            funding_cost = abs(lp_delta_x * price_t0) * self._funding_hr
            return hedge_pnl, funding_cost
        else:
            # Delta-neutral adjustment only — no funding, no capital accumulation.
            return hedge_pnl, 0.0

    def _compute_position_bounds(self, price: float, width_ticks: int) -> tuple[int, int]:
        """Compute aligned (lower_tick, upper_tick) centered at `price` for `width_ticks` spacings.

        Center is clamped so both bounds remain within [MIN_TICK, MAX_TICK].
        Used by auto_deploy, hypothetical fee, no-op detection, and DEPLOY branch.
        """
        tick = price_to_tick(price)
        aligned = (tick // self.tick_spacing) * self.tick_spacing
        half_w = width_ticks * self.tick_spacing // 2
        center = max(MIN_TICK + half_w, min(MAX_TICK - half_w, aligned))
        return max(center - half_w, MIN_TICK), min(center + half_w, MAX_TICK)

    def _compute_hypothetical_fee(self, price_t0: float, price_t1: float,
                                   hour_idx: int, width_ticks: int) -> float:
        """Fee a hypothetical position of `width_ticks` centered at price_t0 would earn.

        Uses same-hour swap data (hour_idx = self.idx) — NOT lookahead.
        We are computing what a position would have earned during the hour that
        just closed (t0→t1). Both real fee and missed_fee use the same swap events.

        Uses current mark-to-market LP value (not stale actual_capital) to size
        the hypothetical position, preventing over/understatement after price moves.

        Used to penalize OOR holding: reward = −(missed_fee + funding) / capital.
        """
        if price_t0 <= 0 or width_ticks <= 0:
            return 0.0
        lower_tick, upper_tick = self._compute_position_bounds(price_t0, width_ticks)
        lower_p = tick_to_price(lower_tick)
        upper_p = tick_to_price(upper_tick)
        value_per_L = self._compute_value_per_L(price_t0, lower_p, upper_p)
        if value_per_L <= 0:
            return 0.0
        # Use current position value instead of stale actual_capital
        current_value = self.get_portfolio_value()
        L_hypo = current_value / value_per_L
        return self._compute_fee(price_t0, price_t1, L_hypo, lower_p, upper_p,
                                  fee_hour_idx=hour_idx)

    def _get_cached_fee_path(
        self,
        hour_idx: int,
        price_t: float,
        price_lower: float,
        price_upper: float,
    ) -> dict:
        """Build/cache exact per-swap fee path metadata for a given hour and range."""
        lp_lower_tick = price_to_tick(price_lower)
        lp_upper_tick = price_to_tick(price_upper)
        key = (int(hour_idx), int(lp_lower_tick), int(lp_upper_tick))
        cache = self.hourly_data._fee_path_cache
        cached = cache.get(key)
        if cached is not None:
            return cached

        t0 = self.timestamps[hour_idx]
        swap_prices = (
            self.hourly_data.swap_prices_per_hour.get(t0, None)
            if self.hourly_data.swap_prices_per_hour is not None else None
        )
        swap_amounts = (
            self.hourly_data.swap_amounts_per_hour.get(t0, None)
            if self.hourly_data.swap_amounts_per_hour is not None else None
        )
        swap_liquidities = (
            self.hourly_data.swap_liquidity_per_hour.get(t0, None)
            if self.hourly_data.swap_liquidity_per_hour is not None else None
        )
        swap_ticks = (
            self.hourly_data.swap_ticks_per_hour.get(t0, None)
            if self.hourly_data.swap_ticks_per_hour is not None else None
        )

        if swap_prices is None or len(swap_prices) < 1 or swap_amounts is None or len(swap_amounts) == 0:
            cached = {"kind": "uncached"}
            cache[key] = cached
            return cached

        opening_tick = price_to_tick(price_t)
        coeffs = []
        pool_liqs = []
        fallback_pool_liq = self._get_pool_liquidity(t0)

        for j in range(len(swap_amounts)):
            p_before = swap_prices[j - 1] if j > 0 else price_t
            p_after = swap_prices[j]

            if (p_before < price_lower and p_after < price_lower) or \
               (p_before > price_upper and p_after > price_upper):
                continue

            if swap_ticks is not None and j < len(swap_ticks):
                t_before = int(swap_ticks[j - 1]) if j > 0 else opening_tick
                t_after = int(swap_ticks[j])
                in_range_frac = _tick_in_range_fraction(
                    t_before, t_after, lp_lower_tick, lp_upper_tick
                )
            else:
                p0_c = max(price_lower, min(price_upper, p_before))
                p1_c = max(price_lower, min(price_upper, p_after))
                total_sqrt_move = abs(
                    math.sqrt(max(p_after, 1e-30)) - math.sqrt(max(p_before, 1e-30))
                )
                in_range_frac = (
                    abs(math.sqrt(p1_c) - math.sqrt(p0_c)) / total_sqrt_move
                    if total_sqrt_move > 0 else 1.0
                )

            coeff = float(swap_amounts[j]) * self.pool_fee * float(in_range_frac)
            if coeff <= 0.0:
                continue

            if (
                swap_liquidities is not None
                and j < len(swap_liquidities)
                and float(swap_liquidities[j]) > 0.0
            ):
                pool_liq_j = float(swap_liquidities[j])
            else:
                pool_liq_j = float(fallback_pool_liq) if fallback_pool_liq > 0 else float("nan")

            coeffs.append(coeff)
            pool_liqs.append(pool_liq_j)

        cached = {
            "kind": "swap_amounts",
            "coeffs": np.asarray(coeffs, dtype=np.float64),
            "pool_liqs": np.asarray(pool_liqs, dtype=np.float64),
        }
        cache[key] = cached
        return cached

    def _compute_fee(self, price_t: float, price_t1: float, L: float, price_lower: float, price_upper: float,
                     fee_hour_idx: int | None = None) -> float:
        """
        Compute LP fee income for one hour.

        Primary path (when swap_amounts_per_hour is available):
            fee_i = |amount1_i| / 10^decimals1 × pool_fee × liquidity_share × in_range_fraction_i
        This is the exact v3-core formula:
            feeGrowthGlobal += feeAmount / L_pool        (v3-core TickMath / Swap logic)
            LP collects L_ours × feeGrowthInside = feeAmount × (L_ours / L_pool)
        in_range_fraction estimated per-swap from |Δ√p| ratio (proportional to the volume
        that crossed through the LP range).

        Fallback path (per-swap prices but no amounts):
            Uses |Δ√p| formula (Zhang et al. 2023 Eq. 5-6) with impact_factor cap.
            Capped at volume × pool_fee × liquidity_share for safety.

        Open-close fallback (no per-swap data):
            Single-interval |Δ√p| formula from hourly open/close prices.

        Args:
            fee_hour_idx: If provided, use this index into self.timestamps to look up
                swap data. Defaults to self.idx. Used by DEPLOY to avoid look-ahead bias:
                a newly deployed position earns fees from the NEXT hour (idx+1), not the
                current hour whose close price determined the position's placement.
        """
        if L <= 0:
            return 0.0

        # Get precomputed per-swap data for the specified hour
        hour_idx = fee_hour_idx if fee_hour_idx is not None else self.idx
        t0 = self.timestamps[hour_idx]

        swap_prices = (
            self.hourly_data.swap_prices_per_hour.get(t0, None)
            if self.hourly_data.swap_prices_per_hour is not None else None
        )
        swap_amounts = (
            self.hourly_data.swap_amounts_per_hour.get(t0, None)
            if self.hourly_data.swap_amounts_per_hour is not None else None
        )
        swap_liquidities = (
            self.hourly_data.swap_liquidity_per_hour.get(t0, None)
            if self.hourly_data.swap_liquidity_per_hour is not None else None
        )
        swap_ticks = (
            self.hourly_data.swap_ticks_per_hour.get(t0, None)
            if self.hourly_data.swap_ticks_per_hour is not None else None
        )

        # Compute hourly-median liquidity share as fallback
        # v3-core: feeGrowthGlobal += feeAmount / L_pool; LP collects L_ours × feeGrowthInside
        L_raw = L * self._liquidity_scale
        pool_L = self._get_pool_liquidity(t0)
        if pool_L > 0 and L_raw > 0:
            liquidity_share = L_raw / (pool_L + L_raw)
        else:
            liquidity_share = 0.0

        cached_fee_path = self._get_cached_fee_path(hour_idx, price_t, price_lower, price_upper)
        if cached_fee_path.get("kind") == "swap_amounts":
            coeffs = cached_fee_path["coeffs"]
            if len(coeffs) == 0:
                return 0.0
            pool_liqs = cached_fee_path["pool_liqs"]
            ls = np.where(
                np.isfinite(pool_liqs) & (pool_liqs > 0),
                L_raw / (pool_liqs + L_raw),
                liquidity_share,
            )
            return float(np.sum(coeffs * ls))

        if swap_prices is not None and len(swap_prices) >= 1:
            total_fee = 0.0
            use_amounts = swap_amounts is not None and len(swap_amounts) > 0

            # Precompute LP ticks for exact tick-span in-range fraction
            lp_lower_tick = price_to_tick(price_lower)
            lp_upper_tick = price_to_tick(price_upper)

            if use_amounts:
                # Per-swap fee: iterate over each swap j=0..N-1.
                # v3 Swap events emit POST-execution state:
                #   swap_ticks[j] = tick AFTER swap j executed
                #   swap_amounts[j] = volume of swap j
                # Swap j moved the pool from its pre-swap state to swap_ticks[j].
                # Pre-swap state = swap_ticks[j-1] for j>0, or hour opening tick for j=0.
                opening_tick = price_to_tick(price_t)

                for j in range(len(swap_amounts)):
                    p_before = swap_prices[j - 1] if j > 0 else price_t
                    p_after = swap_prices[j]

                    # Skip if both outside range on same side (LP earns nothing)
                    if (p_before < price_lower and p_after < price_lower) or \
                       (p_before > price_upper and p_after > price_upper):
                        continue

                    # Per-swap pool liquidity → exact liquidity_share per swap
                    if (swap_liquidities is not None and j < len(swap_liquidities)
                            and swap_liquidities[j] > 0):
                        pool_L_j = swap_liquidities[j]
                        ls_j = L_raw / (pool_L_j + L_raw)
                    else:
                        ls_j = liquidity_share  # fall back to hourly median

                    # Tick-based in-range fraction: swap j moved tick from t_before to t_after
                    if swap_ticks is not None and j < len(swap_ticks):
                        t_before = int(swap_ticks[j - 1]) if j > 0 else opening_tick
                        t_after = int(swap_ticks[j])
                        in_range_frac = _tick_in_range_fraction(
                            t_before, t_after, lp_lower_tick, lp_upper_tick
                        )
                    else:
                        # |Δ√p| fallback
                        p0_c = max(price_lower, min(price_upper, p_before))
                        p1_c = max(price_lower, min(price_upper, p_after))
                        total_sqrt_move = abs(math.sqrt(max(p_after, 1e-30)) - math.sqrt(max(p_before, 1e-30)))
                        in_range_frac = (
                            abs(math.sqrt(p1_c) - math.sqrt(p0_c)) / total_sqrt_move
                            if total_sqrt_move > 0 else 1.0
                        )

                    fee_j = swap_amounts[j] * self.pool_fee * ls_j * in_range_frac
                    total_fee += max(0.0, fee_j)

            elif len(swap_prices) >= 2:
                # Fallback: |Δ√p|-based formula (Zhang et al. 2023 Eq. 5-6)
                # Uses pairs of consecutive post-swap prices (no volume data).
                # impact_factor prevents overstatement when L_ours >> L_pool.
                delta = self.pool_fee
                fee_mult = delta / (1.0 - delta)
                impact_factor = liquidity_share

                for i in range(len(swap_prices) - 1):
                    p0 = swap_prices[i]
                    p1 = swap_prices[i + 1]

                    if (p0 < price_lower and p1 < price_lower) or (p0 > price_upper and p1 > price_upper):
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

                # Cap to volume-based ceiling for safety
                volume_usd = self._get_volume(t0)
                max_fee = volume_usd * self.pool_fee * liquidity_share
                total_fee = min(total_fee, max_fee)

        else:
            # Fallback to open-close formula if no per-swap data available
            if (price_t < price_lower and price_t1 < price_lower) or \
               (price_t > price_upper and price_t1 > price_upper):
                return 0.0

            delta = self.pool_fee
            fee_mult = delta / (1.0 - delta)
            p_t_clamped = max(price_lower, min(price_upper, price_t))
            p_t1_clamped = max(price_lower, min(price_upper, price_t1))

            if p_t_clamped <= p_t1_clamped:
                total_fee = fee_mult * L * (math.sqrt(p_t1_clamped) - math.sqrt(p_t_clamped))
            else:
                total_fee = fee_mult * L * (1.0 / math.sqrt(p_t1_clamped) - 1.0 / math.sqrt(p_t_clamped)) * p_t1_clamped

            total_fee = max(0.0, total_fee)
            # Cap open-close fallback to volume-based ceiling
            volume_usd = self._get_volume(t0)
            max_fee = volume_usd * self.pool_fee * liquidity_share
            total_fee = min(total_fee, max_fee)

        return total_fee

    def _compute_swap_fraction(self, price: float,
                               old_lower: float, old_upper: float, old_L: float,
                               new_lower: float, new_upper: float) -> float:
        """Compute fraction of capital that needs swapping during rebalance (Fix 4).

        Compares token X fraction of old vs new position to determine actual swap needed.
        Returns fraction in [0, 1].
        """
        if old_L <= 0 or price <= 0:
            return 0.5  # First deployment: assume 50%

        sqrt_p = math.sqrt(price)

        # Old position: token X value fraction
        if price <= old_lower:
            old_x_frac = 1.0
        elif price >= old_upper:
            old_x_frac = 0.0
        else:
            sqrt_ol = math.sqrt(old_lower)
            sqrt_ou = math.sqrt(old_upper)
            x_old = old_L * (1.0 / sqrt_p - 1.0 / sqrt_ou)
            y_old = old_L * (sqrt_p - sqrt_ol)
            total_val = x_old * price + y_old
            old_x_frac = (x_old * price / total_val) if total_val > 0 else 0.5

        # New position: token X value fraction
        if price <= new_lower:
            new_x_frac = 1.0
        elif price >= new_upper:
            new_x_frac = 0.0
        else:
            sqrt_nl = math.sqrt(new_lower)
            sqrt_nu = math.sqrt(new_upper)
            # For unit liquidity, compute fraction
            x_new_unit = 1.0 / sqrt_p - 1.0 / sqrt_nu
            y_new_unit = sqrt_p - sqrt_nl
            total_new = x_new_unit * price + y_new_unit
            new_x_frac = (x_new_unit * price / total_new) if total_new > 0 else 0.5

        # Swap fraction = change in token X allocation
        return min(abs(old_x_frac - new_x_frac), 1.0)

    def _get_obs(self) -> np.ndarray:
        if self.has_extended_features:
            return self._get_obs_extended()
        return self._get_obs_legacy()
    
    def _get_obs_extended(self) -> np.ndarray:
        """39-dim observation: 31 tech features + 8 position features."""
        if self.idx >= len(self.timestamps):
            return np.zeros(self.state_dim, dtype=np.float32)
        
        t = self.timestamps[self.idx]
        price = self._get_price(t)
        
        # 33 technical features (FEATURE_COLS); fallback must match to avoid shape mismatch
        tech_features = self.hourly_data.features.get(t, np.zeros(len(FEATURE_COLS), dtype=np.float32))
        
        # 12 position features
        # capital_drawdown: continuous signal based on position value vs initial capital
        if self.has_lp and self.lp_lower_tick is not None:
            lp_lower_price = tick_to_price(self.lp_lower_tick)
            lp_upper_price = tick_to_price(self.lp_upper_tick)
            in_range = 1.0 if lp_lower_price <= price <= lp_upper_price else 0.0
            pos_val = self._compute_position_value(price, lp_lower_price, lp_upper_price, self.liquidity) if self.liquidity > 0 else 0.0
            total_val = pos_val + self.accumulated_fees
            capital_drawdown = max(0.0, 1.0 - total_val / max(self.initial_capital, 1e-10))
            position_value_ratio = total_val / max(self.initial_capital, 1e-10)
        else:
            # Safety fallback: no LP position (shouldn't happen with auto_deploy)
            in_range = 0.0
            position_value_ratio = 0.0
            capital_drawdown = 1.0
        width_normalized = self.lp_width_ticks / max(self.max_width, 1)
        
        # Realized volatility (replaces price_momentum which duplicated return_1h)
        # Uses 6-hour lookback for short-term vol signal not captured by natr_14
        if self.idx >= 6:
            recent_returns = []
            for j in range(1, 7):
                p_prev = self._get_price(self.timestamps[self.idx - j])
                p_cur = self._get_price(self.timestamps[self.idx - j + 1])
                if p_prev > 0:
                    recent_returns.append((p_cur - p_prev) / p_prev)
            realized_vol = float(np.std(recent_returns)) if recent_returns else 0.0
        else:
            realized_vol = 0.0
            
        # Dist to boundary: normalize by fixed 100 ticks for consistent scale (Fix 5)
        # Positive = in range (distance to nearest boundary), Negative = out of range
        dist_to_boundary = 0.0
        if self.has_lp and self.lp_lower_tick is not None:
            tick = price_to_tick(price)
            if in_range > 0.5:
                dist = min(abs(tick - self.lp_lower_tick), abs(self.lp_upper_tick - tick))
                dist_to_boundary = dist / 100.0
            else:
                if tick < self.lp_lower_tick:
                    dist = self.lp_lower_tick - tick
                else:
                    dist = tick - self.lp_upper_tick
                dist_to_boundary = -dist / 100.0

        # Hours since rebalance: log scale for better short-term resolution
        hours_since_rebalance = 0.0
        if self.has_lp:
            hours = self.idx - self.position_entry_idx
            hours_since_rebalance = math.log(1.0 + hours) / math.log(169.0)

        # Expected Yield Proxy (replaces volume_per_tick directly):
        # Instead of generic volume density, give the agent a deterministic yield estimate:
        # Expected Hourly Fee = (Volume / Pool_Liquidity) * Our_Liquidity * Pool_Fee (approximate assumption)
        # We simplify this to: Yield = (Volume * Pool_Fee) / max(Width, 1) to give the network 
        # a continuous monotonic signal that narrow width = high yield.
        volume_now = self._get_volume(t)
        lp_ticks_now = max(self.lp_width_ticks, self.tick_spacing) if self.has_lp else (
            self.max_tick_width * self.tick_spacing
        )
        
        # Approximate the raw dollar fee generation power of the current width setup per hour
        approx_hourly_yield_usd = (volume_now * self.pool_fee) / max(lp_ticks_now, 1)
        
        # Normalize and scale so it isn't an exploding gradient (log1p works well)
        volume_per_tick = math.log1p(approx_hourly_yield_usd) / 5.0

        # Feature 9 (obs[41]): fraction of last hour's swaps where price was inside LP range.
        # Uses swap_ticks_per_hour for the just-completed step (self.idx - 1).
        time_in_range_last_hour = 0.0
        if (self.has_lp and self.lp_lower_tick is not None
                and self.hourly_data.swap_ticks_per_hour is not None
                and self.idx > 0):
            t_prev = self.timestamps[self.idx - 1]
            prev_ticks = self.hourly_data.swap_ticks_per_hour.get(t_prev, None)
            if prev_ticks is not None and len(prev_ticks) > 0:
                time_in_range_last_hour = float(np.mean(
                    (prev_ticks >= self.lp_lower_tick) & (prev_ticks <= self.lp_upper_tick)
                ))

        # Features 10-11 (obs[42-43]): distance to boundaries in σ units.
        # Positive = boundary is dist σ-moves away. Clamped to [0, 5].
        vol_now = self._get_volatility(t) if t is not None else 0.0
        if self.has_lp and self.lp_upper_tick is not None and vol_now > 0:
            upper_p = tick_to_price(self.lp_upper_tick)
            dist_upper_sigma = max(0.0, min(5.0, (upper_p - price) / (price * vol_now)))
        else:
            dist_upper_sigma = 0.0
        if self.has_lp and self.lp_lower_tick is not None and vol_now > 0:
            lower_p = tick_to_price(self.lp_lower_tick)
            dist_lower_sigma = max(0.0, min(5.0, (price - lower_p) / (price * vol_now)))
        else:
            dist_lower_sigma = 0.0

        # Feature 12 (obs[44]): (high - low) / close for the current hour.
        # Intra-hour realized range vol; distinct from EWMA vol.
        if (self.hourly_data.hourly_high is not None
                and self.hourly_data.hourly_low is not None
                and t is not None):
            h = self.hourly_data.hourly_high.get(t, price)
            l = self.hourly_data.hourly_low.get(t, price)
            intra_hour_rvol = (h - l) / max(price, 1e-10)
        else:
            intra_hour_rvol = 0.0

        position_features = np.array([
            capital_drawdown, width_normalized, in_range, position_value_ratio,
            realized_vol, dist_to_boundary, hours_since_rebalance, volume_per_tick,
            time_in_range_last_hour, dist_upper_sigma, dist_lower_sigma, intra_hour_rvol,
        ], dtype=np.float32)

        return np.concatenate([tech_features, position_features])
    
    def _get_obs_legacy(self) -> np.ndarray:
        """Original 8-dim observation (fallback)."""
        if self.idx >= len(self.timestamps):
            return np.zeros(8, dtype=np.float32)
        
        t = self.timestamps[self.idx]
        price = self._get_price(t)
        tick = price_to_tick(price) if price > 0 else 0
        volatility = self._get_volatility(t)
        ma_24h = self._get_ma_24h(t)
        ma_168h = self._get_ma_168h(t)
        
        log_price = math.log(price) if price > 0 else 0.0
        tick_normalized = tick / 10000.0
        width_normalized = self.lp_width_ticks / 100.0
        liquidity_normalized = self.liquidity / 1e6 if self.liquidity > 0 else 0.0
        volatility_normalized = min(volatility * 100, 1.0)
        ma_24h_ratio = ma_24h / price if price > 0 and ma_24h > 0 else 1.0
        ma_168h_ratio = ma_168h / price if price > 0 and ma_168h > 0 else 1.0
        
        in_range = 0.0
        if self.has_lp and self.lp_lower_tick is not None and self.lp_upper_tick is not None:
            lp_lower_price = tick_to_price(self.lp_lower_tick)
            lp_upper_price = tick_to_price(self.lp_upper_tick)
            in_range = 1.0 if lp_lower_price <= price <= lp_upper_price else 0.0
        
        return np.array([
            log_price, tick_normalized, width_normalized,
            liquidity_normalized, volatility_normalized,
            ma_24h_ratio, ma_168h_ratio, in_range,
        ], dtype=np.float32)

    def reset(self, *, seed: int | None = None, options: dict | None = None):
        super().reset(seed=seed)
        self._reset_state()
        self._auto_deploy_initial_position()
        return self._get_obs(), {}

    def step(self, action: np.ndarray):
        if self.idx >= self.n_steps:
            return self._get_obs(), 0.0, True, False, {}

        t0 = self.timestamps[self.idx]
        t1 = self.timestamps[self.idx + 1]

        price_t0 = self._get_price(t0)
        price_t1 = self._get_price(t1)

        reward = 0.0

        # Decode two-scalar action (2-zone: HOLD / DEPLOY):
        #   a[0] < hold_threshold (0.5) → HOLD existing LP
        #   a[0] >= hold_threshold      → DEPLOY at current price, width from a[1]
        #   a[1] in [0, 1]              → width index into WIDTH_SET
        a_decision = float(np.clip(action[0], 0.0, 1.0))
        a_width    = float(np.clip(action[1], 0.0, 1.0))
        is_deploy = a_decision >= self.hold_threshold
        if not is_deploy:
            tick_width = 0  # HOLD
        else:
            widx = int(round(a_width * (len(WIDTH_SET) - 1)))
            widx = max(0, min(widx, len(WIDTH_SET) - 1))
            tick_width = WIDTH_SET[widx]

        # Compute potential DEPLOY bounds once — reused in no-op check and DEPLOY branch.
        new_lower_tick, new_upper_tick = None, None
        if tick_width > 0:
            new_lower_tick, new_upper_tick = self._compute_position_bounds(price_t0, tick_width)
            # No-op detection: skip costs if position is unchanged (same ticks)
            if self.has_lp and self.lp_lower_tick is not None:
                if new_lower_tick == self.lp_lower_tick and new_upper_tick == self.lp_upper_tick:
                    tick_width = 0

        if tick_width == 0:
            # HOLD — keep existing LP position, no gas cost
            if self.has_lp and self.liquidity > 0:
                lp_lower_price = tick_to_price(self.lp_lower_tick)
                lp_upper_price = tick_to_price(self.lp_upper_tick)
                in_range = lp_lower_price <= price_t0 <= lp_upper_price

                # v3-core: fee_i = volume_i × pool_fee × (L_ours / L_pool) × in_range_fraction
                fee = self._compute_fee(price_t0, price_t1, self.liquidity,
                                        lp_lower_price, lp_upper_price,
                                        fee_hour_idx=self.idx)
                # v3-core: fees accrue as tokensOwed (idle, not part of active liquidity)
                self.accumulated_fees += fee

                hedge_pnl, funding_cost = self._compute_hour_hedge(
                    price_t0, price_t1, lp_lower_price, lp_upper_price, self.liquidity)
                # Accumulate hedge P&L for capital tracking (once only — reward uses return values)
                if self.hedge_enabled:
                    self.cumulative_hedge_pnl += hedge_pnl - funding_cost

                if in_range:
                    # In-range: ΔV_LP + hedge_pnl ≈ IL (always ≤ 0). Net = fee − IL − funding.
                    # v3-core traceability: position value uses sqrtPrice math (see _compute_position_value).
                    V_lp_t0 = self._compute_position_value(
                        price_t0, lp_lower_price, lp_upper_price, self.liquidity)
                    V_lp_t1 = self._compute_position_value(
                        price_t1, lp_lower_price, lp_upper_price, self.liquidity)
                    delta_usd = V_lp_t1 - V_lp_t0
                    reward = (delta_usd + hedge_pnl + fee - funding_cost) / self.initial_capital
                else:
                    # OOR: no fee income, only funding cost (if hedge active).
                    # Bug fix (2026-03-13): Removed missed_fee penalty — it was circular
                    # (used agent's own width), fictitious (no balance-sheet counterpart),
                    # and redundant (zero fee income during OOR already penalizes via dilution).
                    reward = -funding_cost / self.initial_capital if self.hedge_enabled else 0.0
            else:
                # Safety fallback: no LP (shouldn't happen with auto_deploy).
                # Penalize using a W10 hypothetical as proxy.
                missed_fee = self._compute_hypothetical_fee(price_t0, price_t1, self.idx, 10)
                reward = -missed_fee / self.initial_capital
        else:
            # DEPLOY: rebalance to specified width (always costs gas).
            # new_lower_tick / new_upper_tick already computed by _compute_position_bounds above.
            new_lower_price = tick_to_price(new_lower_tick)
            new_upper_price = tick_to_price(new_upper_tick)

            # v3-core: burn+collect returns position tokens + all accumulated fees
            # Collect accumulated fees before computing new position capital
            collected_fees = self.accumulated_fees
            self.accumulated_fees = 0.0

            # Mark-to-market before rebalance: LP value + fees + net hedge P&L
            old_has_lp = self.has_lp
            old_L = self.liquidity
            old_lower_tick = self.lp_lower_tick
            old_upper_tick = self.lp_upper_tick
            if old_has_lp and old_L > 0 and old_lower_tick is not None:
                old_lower_price = tick_to_price(old_lower_tick)
                old_upper_price = tick_to_price(old_upper_tick)
                self.actual_capital = (
                    self._compute_position_value(
                        price_t0, old_lower_price, old_upper_price, old_L)
                    + collected_fees
                    + (self.cumulative_hedge_pnl if self.hedge_enabled else 0.0)
                )
                if self.actual_capital <= 0:
                    self.actual_capital = self.initial_capital  # Safety floor
            else:
                # No prior position (first deploy after reset): fees added to capital
                self.actual_capital += collected_fees + (self.cumulative_hedge_pnl if self.hedge_enabled else 0.0)
            self.cumulative_hedge_pnl = 0.0

            # Compute liquidity from actual_capital (Fix 3)
            sqrt_p = math.sqrt(price_t0)
            sqrt_pl = math.sqrt(new_lower_price)
            sqrt_pu = math.sqrt(new_upper_price)
            
            # ── Swap and MEV costs (must deduct BEFORE creating position) ──
            # Compute swap fraction needed for the rebalance
            if old_has_lp and old_L > 0 and old_lower_tick is not None:
                swap_frac = self._compute_swap_fraction(
                    price_t0, tick_to_price(old_lower_tick), tick_to_price(old_upper_tick),
                    old_L, new_lower_price, new_upper_price)
            else:
                swap_frac = 0.5  # True first deployment: assume 50/50 split

            swap_fee_cost = swap_frac * self.pool_fee * self.actual_capital
            mev_cost = swap_frac * self.mev_slippage_pct * self.actual_capital
            reward -= (swap_fee_cost + mev_cost)
            self.actual_capital -= (swap_fee_cost + mev_cost)  # post-cost basis for L and delta_usd

            # ── Deploy new position with post-cost capital ──
            value_per_L = self._compute_value_per_L(price_t0, new_lower_price, new_upper_price)
            
            if value_per_L > 0:
                new_L = self.actual_capital / value_per_L
            else:
                new_L = 0.0

            self.initial_value_usd = self.actual_capital
            self.has_lp = True
            self.liquidity = new_L
            self.lp_width_ticks = tick_width * self.tick_spacing
            self.lp_lower_tick = new_lower_tick
            self.lp_upper_tick = new_upper_tick
            self.entry_price = price_t0
            self.position_entry_idx = self.idx

            # Position deployed at close of hour idx → earns fees from idx+1 onward.
            # Avoids look-ahead bias: position didn't exist during hour idx's swaps.
            next_idx = min(self.idx + 1, len(self.timestamps) - 1)
            fee = self._compute_fee(price_t0, price_t1, new_L, new_lower_price, new_upper_price,
                                    fee_hour_idx=next_idx)

            # Start fresh fee accumulation for new position
            self.accumulated_fees += fee

            # Reward: ΔV_LP + hedge_pnl + fee − gas − swap_fee_cost − funding.
            # actual_capital is post-cost (swap+mev deducted above); V_lp(t0) = new_L × value_per_L = actual_capital.
            # delta_usd = V_lp(t1) − actual_capital_post; combined with -(swap+mev): total = V_lp(t1) − K + fee − gas.
            V_lp_t1_new = self._compute_position_value(
                price_t1, new_lower_price, new_upper_price, new_L)
            delta_usd = V_lp_t1_new - self.actual_capital  # V_lp(t0) = actual_capital by construction
            hedge_pnl, funding_cost = self._compute_hour_hedge(
                price_t0, price_t1, new_lower_price, new_upper_price, new_L)
            # Accumulate hedge P&L for capital tracking (deploy hour of new position)
            if self.hedge_enabled:
                self.cumulative_hedge_pnl += hedge_pnl - funding_cost
            # reward already has -(swap_fee_cost + mev_cost) from the deduction above
            reward += delta_usd + hedge_pnl + fee - self.gas_cost_usd - funding_cost

            reward /= self.initial_capital  # normalize entire DEPLOY reward

        self.idx += 1
        terminated = self.idx >= self.n_steps
        
        info = {
            "t0": t0,
            "price": price_t1,
            "liquidity": self.liquidity,
            "accumulated_fees": self.accumulated_fees,
        }
        if terminated:
            info["final_portfolio_value"] = self.get_portfolio_value()
        return self._get_obs(), reward, terminated, False, info


def make_env_fn(
    hourly_data,  # HourlyData or HourlyDataExtended
    initial_capital_usd: float = 1000.0,
    gas_cost_usd: float = 0.03,  # Must match env default
    min_tick_width: int = 1,
    max_tick_width: int = 40,
    hold_threshold: float = 0.5,
    burn_threshold: float = 0.0,
    mode: str = "train",
    start_idx: Optional[int] = None,
    end_idx: Optional[int] = None,
    in_range_bonus_usd: float = 0.0,
    hedge_funding_rate_annual: float = 0.11,
    hedge_enabled: bool = True,
):
    def _init():
        return UniswapV3PaperEnv(
            hourly_data=hourly_data,
            initial_capital_usd=initial_capital_usd,
            gas_cost_usd=gas_cost_usd,
            min_tick_width=min_tick_width,
            max_tick_width=max_tick_width,
            hold_threshold=hold_threshold,
            burn_threshold=burn_threshold,
            mode=mode,
            start_idx=start_idx,
            end_idx=end_idx,
            in_range_bonus_usd=in_range_bonus_usd,
            hedge_funding_rate_annual=hedge_funding_rate_annual,
            hedge_enabled=hedge_enabled,
        )
    return _init


def train_paper_method(
    data_dir: str,
    num_envs: int = 8,
    total_timesteps: int = 2_000_000,
    initial_capital_usd: float = 1000.0,
    gas_cost_usd: float = 0.03,
    save_path: str = "ppo_uniswap_v3_paper",
    eval_freq: int = 10_000,
    min_tick_width: int = 1,
    max_tick_width: int = 40,
    hold_threshold: float = 0.5,
    burn_threshold: float = 0.0,
    seed: Optional[int] = None,
    hourly_data: Optional['HourlyData'] = None,
    start_idx: Optional[int] = None,
    end_idx: Optional[int] = None,
    ppo_kwargs: Optional[Dict] = None,
    callbacks: Optional[List] = None,
    in_range_bonus_usd: float = 0.0,
    hedge_funding_rate_annual: float = 0.11,
):
    """
    Train PPO using the paper's methodology.

    This follows Xu & Brini (2025) - arXiv:2501.07508:
    - Hourly resampled data
    - Formula-based fee calculation (Equations 5-6)
    - HODL benchmark reward (subsumes LVR, correctly penalizes OOR)
    - Continuous action space mapping to tick widths
    """
    print("=" * 60)
    print("🚀 Paper-Based Uniswap v3 PPO Training")
    print("   Following Xu & Brini (2025) - arXiv:2501.07508")
    print("=" * 60)
    print(f"  Data dir: {data_dir}")
    print(f"  Parallel environments: {num_envs}")
    print(f"  Total timesteps: {total_timesteps:,}")
    print(f"  Initial Capital: ${initial_capital_usd}")
    print(f"  Action space: continuous [0,1] -> hold<{hold_threshold}, deploy>={hold_threshold}, width=[{min_tick_width},{max_tick_width}]")
    print()
    
    # Prepare hourly data with 31-dim technical features (enables 39-dim obs)
    if hourly_data is None:
        hourly_data = prepare_hourly_data(data_dir)
    print(f"  Extended features: {hourly_data.features is not None} (45-dim observation)")

    print()
    print("🏋️ Creating training environments...")

    train_fn = make_env_fn(hourly_data, initial_capital_usd=initial_capital_usd,
                           gas_cost_usd=gas_cost_usd,
                           min_tick_width=min_tick_width, max_tick_width=max_tick_width,
                           hold_threshold=hold_threshold, burn_threshold=burn_threshold,
                           mode="train", start_idx=start_idx, end_idx=end_idx,
                           in_range_bonus_usd=in_range_bonus_usd,
                           hedge_funding_rate_annual=hedge_funding_rate_annual)
    # Eval uses default mode split (no custom indices) unless walk-forward provides them
    eval_fn = make_env_fn(hourly_data, initial_capital_usd=initial_capital_usd,
                          gas_cost_usd=gas_cost_usd,
                          min_tick_width=min_tick_width, max_tick_width=max_tick_width,
                          hold_threshold=hold_threshold, burn_threshold=burn_threshold,
                          mode="eval",
                          hedge_funding_rate_annual=hedge_funding_rate_annual)
    
    if num_envs > 1:
        env = SubprocVecEnv([train_fn for _ in range(num_envs)])
    else:
        env = DummyVecEnv([train_fn])
    
    env = VecNormalize(env, norm_obs=True, norm_reward=True, clip_obs=10.0)
    
    eval_env = DummyVecEnv([eval_fn])
    eval_env = VecNormalize(eval_env, norm_obs=True, norm_reward=False, clip_obs=10.0)
    eval_env.training = False
    
    print(f"  ✅ {num_envs} training envs, 1 eval env created")
    print()
    
    # PPO hyperparameters (similar to paper: optimize via grid search)
    n_steps = max(4096 // num_envs, 64)  # Fix 6: 512 per env for more stable updates
    batch_size = min(256, n_steps * num_envs)

    print("🧠 Creating PPO model...")
    print(f"  n_steps per env: {n_steps}")
    print(f"  batch_size: {batch_size}")
    
    # Default PPO hyperparameters (can be overridden via ppo_kwargs)
    default_ppo_params = dict(
        verbose=1,
        n_steps=n_steps,
        batch_size=batch_size,
        gamma=0.999,  # Longer horizon for 5000+ step episodes (Fix: amortize MEV over 1000h)
        learning_rate=lambda progress: 3e-4 * (0.1 + 0.9 * progress),  # Linear decay to 3e-5
        ent_coef=0.005,  # Low entropy: exploit learned policy
        clip_range=0.2,  # Paper range: 0.05 to 0.4
        n_epochs=10,  # reverted from 5; ppo_two_scalar used 10 and worked
        gae_lambda=0.99,  # Extended from 0.95: horizon ~100h (was ~20h); allows stable-period fee payoffs
        policy_kwargs=dict(
            net_arch=[128, 128],  # Scaled up for 38-dim state space
            log_std_init=-1.0,  # Fix 6: start with std~0.37 instead of 1.0
        ),
        tensorboard_log="./tb_logs_paper/",  # Fix 6: enable monitoring
    )
    if seed is not None:
        default_ppo_params["seed"] = seed
    if ppo_kwargs:
        default_ppo_params.update(ppo_kwargs)

    model = PPO("MlpPolicy", env, **default_ppo_params)
    print("  Using standard MLP policy")
    
    # Callbacks
    if callbacks is not None:
        all_callbacks = callbacks
    else:
        checkpoint_callback = CheckpointCallback(
            save_freq=max(10000 // num_envs, 1000),
            save_path="./checkpoints_paper/",
            name_prefix="ppo_paper"
        )

        eval_callback = EvalCallback(
            eval_env,
            best_model_save_path="./best_model_paper/",
            log_path="./eval_logs_paper/",
            eval_freq=max(eval_freq // num_envs, 1000),
            n_eval_episodes=10,
            deterministic=True,
        )
        all_callbacks = [checkpoint_callback, eval_callback]

    print()
    print("🏃 Starting training...")
    print("=" * 60)

    model.learn(
        total_timesteps=total_timesteps,
        callback=all_callbacks,
        progress_bar=False,
    )
    
    print()
    if save_path is not None:
        print("💾 Saving model...")
        model.save(save_path)
        env.save(f"{save_path}_vec_normalize.pkl")
        print(f"  Model saved to: {save_path}.zip")
        print(f"  VecNormalize saved to: {save_path}_vec_normalize.pkl")
    
    print()
    print("=" * 60)
    print("✅ Training complete!")
    print("=" * 60)
    
    return model, env


def evaluate_paper_method(
    data_dir: str,
    model_path: str = "ppo_uniswap_v3_paper.zip",
    vec_normalize_path: Optional[str] = None,
    n_episodes: int = 10,
    min_tick_width: int = 1,
    max_tick_width: int = 40,
    hold_threshold: float = 0.5,
    burn_threshold: float = 0.0,
    initial_capital_usd: float = 1000.0,
    return_per_step: bool = False,
    hourly_data: Optional['HourlyData'] = None,
    mode: str = "test",
    start_idx: Optional[int] = None,
    end_idx: Optional[int] = None,
) -> dict:
    """
    Evaluate trained model on test set.

    If return_per_step=True, includes per-step rewards and prices arrays
    in the return dict for downstream metrics computation.
    """
    if vec_normalize_path is None:
        vec_normalize_path = model_path.replace(".zip", "_vec_normalize.pkl")

    print("=" * 60)
    print(f"📊 Evaluation on {mode.upper()} set (paper methodology)")
    print("=" * 60)
    print(f"  Data dir: {data_dir}")
    print(f"  Model: {model_path}")
    print()

    if hourly_data is None:
        hourly_data = prepare_hourly_data(data_dir)

    eval_fn = make_env_fn(hourly_data, initial_capital_usd=initial_capital_usd,
                          min_tick_width=min_tick_width, max_tick_width=max_tick_width,
                          hold_threshold=hold_threshold, burn_threshold=burn_threshold,
                          mode=mode, start_idx=start_idx, end_idx=end_idx)
    env = DummyVecEnv([eval_fn])
    env = VecNormalize(env, norm_obs=True, norm_reward=False, clip_obs=10.0)
    if os.path.exists(vec_normalize_path):
        env = VecNormalize.load(vec_normalize_path, env)
    env.training = False
    env.norm_reward = False

    model = PPO.load(model_path, env=env)

    # Compute HODL benchmark from test split prices
    n_total = len(hourly_data.timestamps)
    train_end = int(n_total * 0.8)
    val_end = int(n_total * 0.9)
    test_timestamps = hourly_data.timestamps[val_end:]
    test_start_price = hourly_data.prices[test_timestamps[0]]
    test_end_price = hourly_data.prices[test_timestamps[-1]]
    hodl_eth_return = initial_capital_usd * (test_end_price / test_start_price) - initial_capital_usd
    hodl_5050_return = 0.5 * initial_capital_usd * (test_end_price / test_start_price) + 0.5 * initial_capital_usd - initial_capital_usd

    rewards = []
    burn_count = 0
    hold_count = 0
    deploy_widths = []  # track raw tick_width for histogram
    per_step_data = []  # per-episode: list of (step_rewards, step_prices)

    # Regime-conditioned action tracking (bull/bear/sideways by market_regime feature)
    # and low-volatility subset (natr_14 < 0.005, "stable" market hours).
    _regime_keys = ('bull', 'bear', 'sideways')
    regime_stats = {k: {'hold': 0, 'deploy': []} for k in _regime_keys}
    low_vol_stats = {'hold': 0, 'deploy': []}  # natr_14 < 0.005
    _market_regime_idx = FEATURE_COLS.index('market_regime')
    _natr_idx = FEATURE_COLS.index('natr_14')

    for ep in range(n_episodes):
        # VecNormalize doesn't support seed argument, use plain reset
        reset_result = env.reset()
        obs = reset_result[0] if isinstance(reset_result, (tuple, list)) else reset_result
        done = False
        total_reward = 0.0
        ep_step_rewards = []
        ep_step_prices = []

        while not done:
            action, _ = model.predict(obs, deterministic=True)

            # Decode two-scalar action for tracking (2-zone: HOLD / DEPLOY)
            a_decision = float(np.clip(action[0][0], 0.0, 1.0))
            a_width    = float(np.clip(action[0][1], 0.0, 1.0))
            this_hold = False
            this_tw = None
            if a_decision < hold_threshold:
                hold_count += 1
                this_hold = True
            else:
                widx = int(round(a_width * (len(WIDTH_SET) - 1)))
                widx = max(0, min(widx, len(WIDTH_SET) - 1))
                tw = WIDTH_SET[widx]
                deploy_widths.append(tw)
                this_tw = tw

            step_result = env.step(action)
            if len(step_result) == 5:
                obs, reward, terminated, truncated, info = step_result
                done = bool(terminated[0] or truncated[0])
            else:
                obs, reward, done, info = step_result
                done = bool(done[0])

            r = float(reward[0])
            total_reward += r

            # Regime-conditioned action tracking: look up regime from step's t0 timestamp
            step_t0 = (info[0].get("t0") if isinstance(info, (list, tuple)) and len(info) > 0
                       else info.get("t0") if isinstance(info, dict) else None)
            if step_t0 is not None and hourly_data.features:
                feat = hourly_data.features.get(step_t0)
                if feat is not None:
                    regime_val = float(feat[_market_regime_idx])
                    natr_val = float(feat[_natr_idx])
                    rk = 'bull' if regime_val > 0.5 else ('bear' if regime_val < -0.5 else 'sideways')
                    if this_hold:
                        regime_stats[rk]['hold'] += 1
                        if natr_val < 0.005:
                            low_vol_stats['hold'] += 1
                    elif this_tw is not None:
                        regime_stats[rk]['deploy'].append(this_tw)
                        if natr_val < 0.005:
                            low_vol_stats['deploy'].append(this_tw)

            if return_per_step:
                ep_step_rewards.append(r)
                if isinstance(info, (list, tuple)) and len(info) > 0:
                    ep_step_prices.append(info[0].get("price", 0.0))
                elif isinstance(info, dict):
                    ep_step_prices.append(info.get("price", 0.0))

        # Get actual portfolio value from terminal step info
        actual_final = initial_capital_usd + total_reward  # fallback
        if isinstance(info, (list, tuple)) and len(info) > 0:
            actual_final = info[0].get("final_portfolio_value", actual_final)
        elif isinstance(info, dict):
            actual_final = info.get("final_portfolio_value", actual_final)

        rewards.append((total_reward, actual_final))
        if return_per_step:
            per_step_data.append({
                "rewards": np.array(ep_step_rewards),
                "prices": np.array(ep_step_prices),
            })

    # Print action distribution
    total_actions = hold_count + len(deploy_widths)
    print("Action distribution:")
    pct_hold = 100 * hold_count / total_actions if total_actions > 0 else 0
    print(f"  {'HOLD':15s}: {hold_count:5d} ({pct_hold:.1f}%)")

    if deploy_widths:
        # Histogram bins for deploy widths
        bin_edges = np.linspace(min_tick_width, max_tick_width, 9)  # 8 bins
        counts, _ = np.histogram(deploy_widths, bins=bin_edges)
        for i in range(len(counts)):
            lo, hi = bin_edges[i], bin_edges[i + 1]
            label = f"W=[{lo:.0f},{hi:.0f})"
            pct = 100 * counts[i] / total_actions if total_actions > 0 else 0
            print(f"  {label:15s}: {counts[i]:5d} ({pct:.1f}%)")
    print()

    # Regime-conditioned action distribution
    print("Action distribution by market regime:")
    for rk in _regime_keys:
        rs = regime_stats[rk]
        n_rk = rs['hold'] + len(rs['deploy'])
        if n_rk == 0:
            continue
        pct_d = 100 * len(rs['deploy']) / n_rk
        pct_h = 100 * rs['hold'] / n_rk
        avg_w = float(np.mean(rs['deploy'])) if rs['deploy'] else float('nan')
        print(f"  {rk.upper():8s}: n={n_rk:5d} | DEPLOY {pct_d:5.1f}% (avg W={avg_w:.1f}) "
              f"| HOLD {pct_h:5.1f}%")

    lv_n = low_vol_stats['hold'] + len(low_vol_stats['deploy'])
    if lv_n > 0:
        pct_d = 100 * len(low_vol_stats['deploy']) / lv_n
        pct_h = 100 * low_vol_stats['hold'] / lv_n
        avg_w = float(np.mean(low_vol_stats['deploy'])) if low_vol_stats['deploy'] else float('nan')
        print(f"  {'LOW-VOL':8s}: n={lv_n:5d} | DEPLOY {pct_d:5.1f}% (avg W={avg_w:.1f}) "
              f"| HOLD {pct_h:5.1f}% (natr_14 < 0.005)")
    print()

    alpha_rewards = [r[0] for r in rewards]
    final_values = [r[1] for r in rewards]

    mean_reward = float(np.mean(alpha_rewards))
    std_reward = float(np.std(alpha_rewards))
    mean_final = float(np.mean(final_values))

    # LP final value from actual portfolio mark-to-market
    mean_lp_return_pct = 100 * (mean_final / initial_capital_usd - 1.0)
    hodl_eth_final = initial_capital_usd + hodl_eth_return
    hodl_eth_pct = 100 * hodl_eth_return / initial_capital_usd
    hodl_5050_final = initial_capital_usd + hodl_5050_return
    hodl_5050_pct = 100 * hodl_5050_return / initial_capital_usd
    alpha_vs_eth = mean_final - hodl_eth_final
    alpha_vs_5050 = mean_final - hodl_5050_final

    print("Results:")
    print(f"  Mean cumulative alpha (vs HODL): {mean_reward:.2f} +/- {std_reward:.2f}")
    print(f"  Mean final portfolio value: ${mean_final:,.2f}")
    print()
    print("  HODL Benchmark Comparison:")
    print(f"    ETH price:    ${test_start_price:,.2f} -> ${test_end_price:,.2f} ({100*(test_end_price/test_start_price - 1):+.1f}%)")
    print(f"    LP final:     ${mean_final:,.2f} ({mean_lp_return_pct:+.1f}%)")
    print(f"    HODL ETH:     ${hodl_eth_final:,.2f} ({hodl_eth_pct:+.1f}%)")
    print(f"    HODL 50/50:   ${hodl_5050_final:,.2f} ({hodl_5050_pct:+.1f}%)")
    print(f"    Alpha vs ETH: ${alpha_vs_eth:+,.2f}")
    print(f"    Alpha vs 50/50: ${alpha_vs_5050:+,.2f}")
    print("=" * 60)

    result = {
        "mean_reward": mean_reward,
        "std_reward": std_reward,
        "mean_final_value": mean_final,
        "hold_count": hold_count,
        "deploy_widths": deploy_widths,
        "hodl_eth_return": hodl_eth_return,
        "hodl_5050_return": hodl_5050_return,
        "alpha_vs_eth": alpha_vs_eth,
        "alpha_vs_5050": alpha_vs_5050,
        "episode_rewards": alpha_rewards,
        "regime_stats": regime_stats,
        "low_vol_stats": low_vol_stats,
        "episode_final_values": final_values,
    }
    if return_per_step:
        result["per_step_data"] = per_step_data
    return result


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Paper-based PPO training for Uniswap v3 LP")
    parser.add_argument("--data-dir", type=str, default=None, help="Path to data")
    parser.add_argument("--num-envs", type=int, default=8, help="Number of parallel environments")
    parser.add_argument("--timesteps", type=int, default=2_000_000, help="Total training timesteps")
    parser.add_argument("--save-path", type=str, default="ppo_uniswap_v3_paper", help="Model save path")
    parser.add_argument("--evaluate", action="store_true", help="Evaluate on test set")
    parser.add_argument("--eval-episodes", type=int, default=10, help="Episodes for evaluation")
    parser.add_argument("--min-tick-width", type=int, default=1, help="Minimum tick width (in tick_spacing units)")
    parser.add_argument("--max-tick-width", type=int, default=40, help="Maximum tick width (in tick_spacing units)")
    parser.add_argument("--hold-threshold", type=float, default=0.40, help="Action threshold below which agent HOLDs")
    parser.add_argument("--burn-threshold", type=float, default=0.10, help="Action threshold below which agent BURNs LP position")
    parser.add_argument("--capital", type=float, default=1000.0, help="Initial capital in USD")

    args = parser.parse_args()
    
    if args.data_dir is None:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        cwd = os.getcwd()
        candidates = [
            os.path.join(script_dir, "training_data"),
            os.path.join(cwd, "training_data"),
            # Also check simulation_6 (since we share data)
            os.path.join(os.path.dirname(script_dir), "simulation_6", "training_data"),
            cwd,
        ]
        required = "pool_config_eth_usdt_0p3.csv"
        for d in candidates:
            if d and os.path.isfile(os.path.join(d, required)):
                args.data_dir = os.path.abspath(d)
                break
        else:
            raise FileNotFoundError(
                f"Data not found. Tried: {candidates}. "
                f"Pass --data-dir /path/to/training_data"
            )
    
    if args.evaluate:
        evaluate_paper_method(
            data_dir=args.data_dir,
            model_path=f"{args.save_path}.zip" if not args.save_path.endswith(".zip") else args.save_path,
            n_episodes=args.eval_episodes,
            initial_capital_usd=args.capital,
            min_tick_width=args.min_tick_width,
            max_tick_width=args.max_tick_width,
            hold_threshold=args.hold_threshold,
            burn_threshold=args.burn_threshold,
        )
    else:
        train_paper_method(
            data_dir=args.data_dir,
            num_envs=args.num_envs,
            total_timesteps=args.timesteps,
            save_path=args.save_path,
            initial_capital_usd=args.capital,
            min_tick_width=args.min_tick_width,
            max_tick_width=args.max_tick_width,
            hold_threshold=args.hold_threshold,
            burn_threshold=args.burn_threshold,
        )
