"""
Kongtrae v2 – Hedged LP Decision Engine
========================================
Three-head DQN with continuous delta hedging for Uniswap V3 ETH/USDT 0.05%.

Two modes:
  --strategy dqn    (default) Three-head Double-Dueling DQN with VecNormalize
  --strategy rule   Benchmark bb_width threshold rule

Usage:
    # DQN model (default):
    python inference.py --ohlcv-csv hourly_eth.csv --state cash

    # Rule baseline:
    python inference.py --strategy rule --ohlcv-csv hourly_eth.csv

    # Quick mode (price only, less accurate):
    python inference.py --price 3000
"""

from __future__ import annotations

import argparse
import json
import math
import os
import pickle
import sys
from datetime import datetime, timezone
from typing import Optional

import numpy as np
import pandas as pd

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PACKAGE_DIR = SCRIPT_DIR
PACKAGE_PARENT = os.path.dirname(PACKAGE_DIR)
if PACKAGE_PARENT not in sys.path:
    sys.path.insert(0, PACKAGE_PARENT)

# ─── Pool constants ──────────────────────────────────────────────────────────
TICK_SPACING = 10
POOL_FEE = 0.0005  # 0.05%
DEC0, DEC1 = 18, 6  # WETH, USDT
TICK_OFFSET = int(round((DEC0 - DEC1) * math.log(10) / math.log(1.0001)))

# ─── Feature columns (must match training) ──────────────────────────────────
FEATURE_COLS = [
    'high_open_ratio', 'low_open_ratio', 'close_open_ratio',
    'dema_ratio', 'momentum_12', 'roc_12', 'atr_14', 'natr_14',
    'adx_14', 'plus_di', 'minus_di', 'cci_20', 'rsi_14',
    'macd', 'macd_signal', 'macd_hist',
    'bb_upper', 'bb_lower', 'bb_width',
    'stoch_k', 'stoch_d', 'volume_sma_ratio',
    'return_1h', 'return_24h', 'return_7d',
    'price_vs_ma50', 'price_vs_ma200', 'ma50_vs_ma200',
    'market_regime', 'trend_strength_24h', 'trend_strength_7d',
    'regime_fast', 'vol_regime',
]

# Vol features used by the hedged env (indices into FEATURE_COLS)
VOL_FEATURE_INDICES = [
    FEATURE_COLS.index("atr_14"),
    FEATURE_COLS.index("natr_14"),
    FEATURE_COLS.index("bb_width"),
    FEATURE_COLS.index("volume_sma_ratio"),
    FEATURE_COLS.index("adx_14"),
    FEATURE_COLS.index("vol_regime"),
]

# Three-head action mapping for the shipped W4/W6/W10/W20 model
ACTION_WIDTHS = (4, 6, 10, 20)
NUM_ACTIONS = 2 + len(ACTION_WIDTHS)  # 6: stay/exit + 4 widths
ACTIONS = {
    "cash": {
        0: "STAY_CASH",
        1: "ENTER_W4",
        2: "ENTER_W6",
        3: "ENTER_W10",
        4: "ENTER_W20",
        5: "MASKED",
    },
    "lp_in_range": {
        0: "HOLD",
        1: "GO_CASH",
        2: "RECENTER_SAME_WIDTH",
        3: "MASKED",
        4: "MASKED",
        5: "MASKED",
    },
    "lp_oor": {
        0: "HOLD_OOR",
        1: "GO_CASH",
        2: "RECENTER_SAME_WIDTH",
        3: "MASKED",
        4: "MASKED",
        5: "MASKED",
    },
}


# ─── Technical indicator computation ────────────────────────────────────────

def _ema(data: np.ndarray, period: int) -> np.ndarray:
    alpha = 2.0 / (period + 1)
    result = np.zeros_like(data, dtype=float)
    result[0] = data[0]
    for i in range(1, len(data)):
        result[i] = alpha * data[i] + (1 - alpha) * result[i - 1]
    return result


def compute_technical_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Compute 33 technical indicators from OHLCV data."""
    if 'close' not in df.columns:
        return df

    close = df['close'].values.astype(float)
    high = df['high'].values.astype(float) if 'high' in df.columns else close.copy()
    low = df['low'].values.astype(float) if 'low' in df.columns else close.copy()
    open_price = df['open'].values.astype(float) if 'open' in df.columns else close.copy()
    volume = df['volume'].values.astype(float) if 'volume' in df.columns else np.ones_like(close)

    n = len(close)

    df['high_open_ratio'] = high / np.maximum(open_price, 1e-10)
    df['low_open_ratio'] = low / np.maximum(open_price, 1e-10)
    df['close_open_ratio'] = close / np.maximum(open_price, 1e-10)

    ema_12 = _ema(close, 12)
    ema_12_12 = _ema(ema_12, 12)
    dema = 2 * ema_12 - ema_12_12
    df['dema_ratio'] = dema / np.maximum(open_price, 1e-10)

    momentum_12 = np.zeros(n)
    momentum_12[12:] = (close[12:] - close[:-12]) / np.maximum(close[:-12], 1e-10)
    df['momentum_12'] = momentum_12

    roc_6 = np.zeros(n)
    roc_6[6:] = (close[6:] - close[:-6]) / np.maximum(close[:-6], 1e-10)
    df['roc_12'] = roc_6

    tr = np.maximum(high - low,
                    np.maximum(np.abs(high - np.roll(close, 1)),
                               np.abs(low - np.roll(close, 1))))
    tr[0] = high[0] - low[0]
    atr_14_raw = pd.Series(tr).rolling(14, min_periods=1).mean().values
    df['natr_14'] = atr_14_raw / np.maximum(close, 1e-10)
    df['atr_14'] = df['natr_14']

    plus_dm = np.maximum(high - np.roll(high, 1), 0)
    minus_dm = np.maximum(np.roll(low, 1) - low, 0)
    plus_dm[0] = 0
    minus_dm[0] = 0
    atr_smooth = _ema(tr, 14)
    plus_di = 100 * _ema(plus_dm, 14) / np.maximum(atr_smooth, 1e-10)
    minus_di = 100 * _ema(minus_dm, 14) / np.maximum(atr_smooth, 1e-10)
    dx = 100 * np.abs(plus_di - minus_di) / np.maximum(plus_di + minus_di, 1e-10)
    df['adx_14'] = _ema(dx, 14) / 100.0
    df['plus_di'] = plus_di / 100.0
    df['minus_di'] = minus_di / 100.0

    typical_price = (high + low + close) / 3.0
    tp_sma = pd.Series(typical_price).rolling(20, min_periods=1).mean().values
    tp_mad = pd.Series(typical_price).rolling(20, min_periods=1).apply(
        lambda x: np.mean(np.abs(x - x.mean())), raw=True
    ).fillna(1).values
    df['cci_20'] = (typical_price - tp_sma) / np.maximum(0.015 * tp_mad, 1e-10) / 200.0

    delta = np.diff(close, prepend=close[0])
    gain = np.where(delta > 0, delta, 0)
    loss = np.where(delta < 0, -delta, 0)
    avg_gain = _ema(gain, 14)
    avg_loss = _ema(loss, 14)
    rs = avg_gain / np.maximum(avg_loss, 1e-10)
    df['rsi_14'] = 1 - 1 / (1 + rs)

    ema_12_close = _ema(close, 12)
    ema_26_close = _ema(close, 26)
    macd = ema_12_close - ema_26_close
    signal = _ema(macd, 9)
    df['macd'] = macd / np.maximum(close, 1e-10)
    df['macd_signal'] = signal / np.maximum(close, 1e-10)
    df['macd_hist'] = (macd - signal) / np.maximum(close, 1e-10)

    sma_20 = pd.Series(close).rolling(20, min_periods=1).mean().values
    std_20 = pd.Series(close).rolling(20, min_periods=1).std().fillna(0).values
    df['bb_upper'] = (sma_20 + 2 * std_20) / np.maximum(close, 1e-10)
    df['bb_lower'] = (sma_20 - 2 * std_20) / np.maximum(close, 1e-10)
    df['bb_width'] = (4 * std_20) / np.maximum(close, 1e-10)

    low_14 = pd.Series(low).rolling(14, min_periods=1).min().values
    high_14 = pd.Series(high).rolling(14, min_periods=1).max().values
    df['stoch_k'] = (close - low_14) / np.maximum(high_14 - low_14, 1e-10)
    df['stoch_d'] = pd.Series(df['stoch_k']).rolling(3, min_periods=1).mean().values

    df['volume_sma_ratio'] = volume / np.maximum(
        pd.Series(volume).rolling(20, min_periods=1).mean().values, 1e-10
    )

    return_1h = np.zeros(n)
    return_1h[1:] = (close[1:] - close[:-1]) / np.maximum(close[:-1], 1e-10)
    df['return_1h'] = return_1h

    return_24h = np.zeros(n)
    return_24h[24:] = (close[24:] - close[:-24]) / np.maximum(close[:-24], 1e-10)
    df['return_24h'] = return_24h

    return_7d = np.zeros(n)
    return_7d[168:] = (close[168:] - close[:-168]) / np.maximum(close[:-168], 1e-10)
    df['return_7d'] = return_7d

    ma_50 = pd.Series(close).rolling(50, min_periods=1).mean().values
    ma_200 = pd.Series(close).rolling(200, min_periods=1).mean().values
    df['price_vs_ma50'] = (close - ma_50) / np.maximum(ma_50, 1e-10)
    df['price_vs_ma200'] = (close - ma_200) / np.maximum(ma_200, 1e-10)
    df['ma50_vs_ma200'] = (ma_50 - ma_200) / np.maximum(ma_200, 1e-10)

    regime = np.zeros(n)
    for i in range(168, n):
        denom = max(close[i - 168], 1e-10)
        ret_7d = (close[i] - close[i - 168]) / denom
        if ret_7d > 0.03:
            regime[i] = 1.0
        elif ret_7d < -0.03:
            regime[i] = -1.0
    df['market_regime'] = regime

    df['trend_strength_24h'] = np.abs(df['return_24h'])
    df['trend_strength_7d'] = np.abs(df['return_7d'])

    regime_fast = np.zeros(n)
    for i in range(24, n):
        denom = max(close[i - 24], 1e-10)
        ret_24h = (close[i] - close[i - 24]) / denom
        if ret_24h > 0.015:
            regime_fast[i] = 1.0
        elif ret_24h < -0.015:
            regime_fast[i] = -1.0
    df['regime_fast'] = regime_fast

    df['vol_regime'] = (df['natr_14'] > 0.005).astype(float)

    df = df.fillna(0)
    return df


# ─── Data loading ────────────────────────────────────────────────────────────

def load_ohlcv(path: str) -> pd.DataFrame:
    """Load hourly OHLCV CSV."""
    df = pd.read_csv(path, parse_dates=[0], index_col=0)
    df.columns = [c.lower() for c in df.columns]
    if 'close' not in df.columns:
        raise ValueError("CSV must have 'close' column")
    return df


def load_swap_csv(path: str) -> pd.DataFrame:
    """Load raw Uniswap V3 swap CSV and convert to hourly OHLCV."""
    df = pd.read_csv(path, low_memory=False)
    df.columns = [c.strip() for c in df.columns]
    required = ['evt_block_time', 'sqrtPriceX96']
    for col in required:
        if col not in df.columns:
            raise ValueError(f"Swap CSV missing '{col}'. Found: {df.columns.tolist()}")

    df['evt_block_time'] = pd.to_datetime(df['evt_block_time'], utc=True)
    df = df.sort_values('evt_block_time')

    Q96 = 2**96

    def price_fn(x):
        try:
            p = float(x) / Q96
            return (p * p) * (10 ** (DEC0 - DEC1))
        except Exception:
            return 0.0

    df['price'] = df['sqrtPriceX96'].apply(price_fn)

    if 'amount1' in df.columns:
        df['amount1'] = pd.to_numeric(df['amount1'], errors='coerce').abs()
        df['volume_usd'] = df['amount1'] / (10 ** DEC1)
    elif 'amount0' in df.columns:
        df['amount0'] = pd.to_numeric(df['amount0'], errors='coerce').abs()
        df['volume_usd'] = (df['amount0'] / (10 ** DEC0)) * df['price']
    else:
        df['volume_usd'] = 0.0

    df.set_index('evt_block_time', inplace=True)
    hourly = df['price'].resample('h').ohlc()
    hourly['volume'] = df['volume_usd'].resample('h').sum()
    hourly['close'] = hourly['close'].ffill()
    hourly['open'] = hourly['open'].fillna(hourly['close'])
    hourly['high'] = hourly['high'].fillna(hourly['close'])
    hourly['low'] = hourly['low'].fillna(hourly['close'])
    hourly['volume'] = hourly['volume'].fillna(0)
    hourly.columns = ['open', 'high', 'low', 'close', 'volume']
    return hourly


def make_dummy_ohlcv(price: float, volume: float = 5_000_000) -> pd.DataFrame:
    """Create minimal OHLCV DataFrame for price-only mode."""
    dates = pd.date_range(end=datetime.now(tz=timezone.utc), periods=200, freq='h')
    return pd.DataFrame({
        'open': price, 'high': price,
        'low': price, 'close': price,
        'volume': volume,
    }, index=dates)


# ─── Tick math ───────────────────────────────────────────────────────────────

def price_to_tick(price: float) -> int:
    """Convert USD price to simulation tick."""
    return int(round(math.log(price) / math.log(1.0001)))


def tick_to_price(tick: int) -> float:
    """Convert simulation tick to USD price."""
    return 1.0001 ** tick


def price_to_onchain_tick(price_usd: float) -> int:
    """Convert USD price to on-chain tick (accounts for token decimals)."""
    price_raw = price_usd * 10 ** (DEC1 - DEC0)  # USDT(6) / WETH(18) raw ratio
    return math.floor(math.log(price_raw) / math.log(1.0001))


def onchain_tick_to_price(tick: int) -> float:
    """Convert on-chain tick to USD price."""
    price_raw = 1.0001 ** tick
    return price_raw * 10 ** (DEC0 - DEC1)


def compute_lp_range(price: float, width: int) -> dict:
    """Compute on-chain LP range for given width (in tick spacings).

    Ticks are aligned to TICK_SPACING (10) as required by Uniswap V3.
    """
    tick = price_to_onchain_tick(price)
    center_tick = (tick // TICK_SPACING) * TICK_SPACING
    lower_tick = center_tick - width * TICK_SPACING
    upper_tick = center_tick + width * TICK_SPACING
    p_lower = onchain_tick_to_price(lower_tick)
    p_upper = onchain_tick_to_price(upper_tick)
    return {
        "width": width,
        "center_tick": center_tick,
        "lower_tick": lower_tick,
        "upper_tick": upper_tick,
        "price_lower": round(p_lower, 2),
        "price_upper": round(p_upper, 2),
        "range_pct": round((p_upper / p_lower - 1) * 100, 2),
    }


# ─── Rule-based strategy ────────────────────────────────────────────────────

def expanding_median(values: np.ndarray) -> np.ndarray:
    """Compute expanding (cumulative) median for each position."""
    result = np.zeros_like(values)
    for i in range(len(values)):
        result[i] = np.median(values[: i + 1])
    return result


def rule_strategy(
    df: pd.DataFrame,
    width: int = 10,
    state: str = "cash",
) -> dict:
    """
    bb_width threshold rule: deploy when bb_width > expanding median.

    Walk-forward validated: 10/10 folds positive, mean +$130/month on $1K.
    Beats all DQN variants tested.
    """
    df = compute_technical_indicators(df.copy())
    bb_values = df['bb_width'].values.astype(np.float32)
    medians = expanding_median(bb_values)

    current_bb = float(bb_values[-1])
    current_median = float(medians[-1])
    signal_on = current_bb > current_median
    bb_ratio = current_bb / max(current_median, 1e-6)

    if state == "cash":
        if signal_on:
            action = f"DEPLOY_W{width}"
            recommendation = f"Deploy LP at width {width} (bb_width={current_bb:.4f} > median={current_median:.4f})"
        else:
            action = "STAY_CASH"
            recommendation = f"Stay cash (bb_width={current_bb:.4f} <= median={current_median:.4f})"
    elif state == "lp_in_range":
        action = "HOLD"
        recommendation = "Hold position (in range, earning fees)"
    elif state == "lp_oor":
        action = f"RECENTER_W{width}"
        recommendation = f"Recenter at width {width} (OOR: recenter is +EV, net +$1.40/hr)"
    else:
        action = "STAY_CASH"
        recommendation = "Unknown state, defaulting to cash"

    return {
        "action": action,
        "recommendation": recommendation,
        "bb_width": round(current_bb, 6),
        "bb_median": round(current_median, 6),
        "bb_ratio": round(bb_ratio, 4),
        "signal_on": signal_on,
    }


# ─── DQN model strategy ─────────────────────────────────────────────────────

def _projected_entry_features(
    natr_14: float,
    volume_sma_ratio: float,
    width: int,
) -> tuple[float, float]:
    """Compute hours_to_oor and fee_il_ratio for a candidate width."""
    sigma_hourly = max(natr_14, 1e-6)
    width_normalized = max(float(width) / 40.0, 0.01)
    half_width_ticks = (float(width) * TICK_SPACING) / 2.0
    half_width_frac = math.exp(half_width_ticks * math.log(1.0001)) - 1.0
    sigma_actual = sigma_hourly / 1.3
    hours_to_oor = min(
        (half_width_frac ** 2) / max(sigma_actual ** 2, 1e-12),
        500.0,
    )
    fee_il_ratio = min(
        10.0,
        volume_sma_ratio * POOL_FEE / max(sigma_hourly ** 2 * width_normalized, 1e-10),
    )
    return hours_to_oor / 100.0, fee_il_ratio


def build_dqn_observation(
    features_33: np.ndarray,
    state: str,
    bb_values: np.ndarray,
    current_idx: int,
    width_normalized: float = 0.0,
    in_range: float = 0.0,
    dist_to_boundary_sigma: float = 0.0,
    hours_since_rebalance: float = 0.0,
    expected_hours_to_oor: float = 0.0,
    fee_il_ratio: float = 0.0,
    realized_vol_6h: float = 0.0,
    intra_hour_rvol: float = 0.0,
    book_capital_ratio: float = 1.0,
    net_carry_ratio: float = 0.0,
    time_in_range: float = 0.0,
    is_cash: float = 1.0,
) -> np.ndarray:
    """Build 31-dim observation for the shipped three-head DQN."""
    # 1) State one-hot [3]
    state_map = {"cash": 0, "lp_in_range": 1, "lp_oor": 2}
    one_hot = np.zeros(3, dtype=np.float32)
    one_hot[state_map.get(state, 0)] = 1.0

    # 2) Paper signal features [2]
    median_vals = expanding_median(bb_values[: current_idx + 1])
    current_median = max(float(median_vals[-1]), 1e-6)
    current_bb = float(bb_values[current_idx])
    bb_ratio = np.clip(current_bb / current_median, 0.0, 10.0)
    bb_signal = 1.0 if current_bb > current_median else 0.0
    paper_features = np.array([bb_ratio, bb_signal], dtype=np.float32)

    # 3) Candidate entry features [8] (W4, W6, W10, W20)
    natr_14 = float(features_33[FEATURE_COLS.index("natr_14")])
    vol_sma = float(features_33[FEATURE_COLS.index("volume_sma_ratio")])
    candidate_features = []
    for w in ACTION_WIDTHS:
        h, f = _projected_entry_features(natr_14, vol_sma, w)
        candidate_features.extend([h, f])
    candidate_features = np.array(candidate_features, dtype=np.float32)

    # 4) Vol features [6]
    vol_features = np.array(
        [features_33[i] for i in VOL_FEATURE_INDICES],
        dtype=np.float32,
    )

    # 5) Position features [12]
    position_features = np.array([
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
    ], dtype=np.float32)

    return np.concatenate([one_hot, paper_features, candidate_features, vol_features, position_features])


def load_dqn_model(model_dir: str, device: str = "cpu"):
    """Load three-head DQN model + VecNormalize stats."""
    from kongtrae.training.three_head_dueling_dqn import ThreeHeadDoubleDuelingDQN

    model_path = os.path.join(model_dir, "dqn_three_head_v2.zip")
    vec_path = os.path.join(model_dir, "dqn_three_head_v2_vecnormalize.pkl")

    if not os.path.exists(model_path):
        raise FileNotFoundError(f"Model not found: {model_path}")
    if not os.path.exists(vec_path):
        raise FileNotFoundError(f"VecNormalize not found: {vec_path}")

    model = ThreeHeadDoubleDuelingDQN.load(model_path, device=device)

    with open(vec_path, "rb") as f:
        vec_normalize = pickle.load(f)

    return model, vec_normalize


def dqn_strategy(
    df: pd.DataFrame,
    state: str,
    model_dir: str,
    device: str = "cpu",
    current_width: Optional[int] = None,
    in_range: bool = False,
    hours_since_rebalance: int = 0,
) -> dict:
    """Run three-head DQN model for LP decision."""
    model, vec_normalize = load_dqn_model(model_dir, device)

    df = compute_technical_indicators(df.copy())
    features_33 = df[FEATURE_COLS].iloc[-1].values.astype(np.float32)
    features_33 = np.nan_to_num(features_33, nan=0.0, posinf=0.0, neginf=0.0)

    bb_values = df['bb_width'].values.astype(np.float32)

    # Build position state features
    is_cash = 1.0 if state == "cash" else 0.0
    width_norm = (current_width or 0) / 40.0 if current_width else 0.0
    in_range_val = 1.0 if in_range and state != "cash" else 0.0
    hrs_norm = math.log1p(max(hours_since_rebalance, 0)) / math.log(169.0) if state != "cash" else 0.0

    natr_14 = max(float(features_33[FEATURE_COLS.index("natr_14")]), 1e-6)
    if current_width and state != "cash":
        half_ticks = (current_width * TICK_SPACING) / 2.0
        half_frac = math.exp(half_ticks * math.log(1.0001)) - 1.0
        sigma_actual = natr_14 / 1.3
        exp_hours = min((half_frac ** 2) / max(sigma_actual ** 2, 1e-12), 500.0)
        vol_sma = float(features_33[FEATURE_COLS.index("volume_sma_ratio")])
        fil_ratio = min(10.0, vol_sma * POOL_FEE / max(natr_14 ** 2 * max(width_norm, 0.01), 1e-10))
    else:
        exp_hours = 0.0
        fil_ratio = 0.0

    # Compute realized vol from close prices
    closes = df['close'].values.astype(float)
    if len(closes) >= 7:
        rets = np.diff(closes[-7:]) / np.maximum(closes[-7:-1], 1e-10)
        rvol_6h = float(np.std(rets))
    else:
        rvol_6h = 0.0

    # Intra-hour realized vol from high/low (training env uses this for all states)
    if 'high' in df.columns and 'low' in df.columns:
        last_high = float(df['high'].iloc[-1])
        last_low = float(df['low'].iloc[-1])
        last_price = float(df['close'].iloc[-1])
        intra_rvol = (last_high - last_low) / max(last_price, 1e-10)
    else:
        intra_rvol = 0.0

    obs = build_dqn_observation(
        features_33=features_33,
        state=state,
        bb_values=bb_values,
        current_idx=len(bb_values) - 1,
        width_normalized=width_norm,
        in_range=in_range_val,
        hours_since_rebalance=hrs_norm,
        expected_hours_to_oor=exp_hours,
        fee_il_ratio=fil_ratio,
        realized_vol_6h=rvol_6h,
        intra_hour_rvol=intra_rvol,
        book_capital_ratio=1.0,
        is_cash=is_cash,
    )

    # Apply VecNormalize
    obs_batch = np.array([obs], dtype=np.float32)
    obs_normalized = vec_normalize.normalize_obs(obs_batch)

    # Get model prediction
    action, _ = model.predict(obs_normalized, deterministic=True)
    action_int = int(action[0]) if hasattr(action, '__len__') else int(action)

    action_label = ACTIONS.get(state, {}).get(action_int, f"UNKNOWN_{action_int}")

    # Fallback: if model picks a masked action, use sensible default
    if action_label == "MASKED":
        if state == "cash":
            action_int = 1  # default to first width
            action_label = ACTIONS["cash"][1]
        elif state == "lp_oor":
            action_int = 2  # recenter
            action_label = "RECENTER_SAME_WIDTH"
        else:
            action_int = 0
            action_label = "HOLD"

    # Determine width from action
    deployed_width = None
    if state == "cash" and 1 <= action_int <= len(ACTION_WIDTHS):
        deployed_width = ACTION_WIDTHS[action_int - 1]
    elif state == "lp_oor" and action_int == 2:
        deployed_width = current_width or ACTION_WIDTHS[0]

    recommendation = action_label
    if deployed_width:
        recommendation = f"{action_label} -> Set LP at width {deployed_width}"

    return {
        "action": action_label,
        "action_int": action_int,
        "deployed_width": deployed_width,
        "recommendation": recommendation,
    }


# ─── Main decision function ─────────────────────────────────────────────────

def decide(args):
    """Main entry point."""
    # Load data
    if args.swap_csv:
        df = load_swap_csv(args.swap_csv)
    elif args.ohlcv_csv:
        df = load_ohlcv(args.ohlcv_csv)
    elif args.price:
        df = make_dummy_ohlcv(args.price, args.volume)
        print("  Warning: price-only mode. Technical indicators will be approximate.")
    else:
        raise ValueError("Provide --swap-csv, --ohlcv-csv, or --price")

    current_price = float(df['close'].iloc[-1])
    last_ts = df.index[-1]

    # Run strategy
    if args.strategy == "rule":
        result = rule_strategy(df, width=args.width, state=args.state)
    else:
        model_dir = os.path.join(SCRIPT_DIR, "models")
        result = dqn_strategy(
            df,
            state=args.state,
            model_dir=model_dir,
            device=args.device,
            current_width=args.current_width,
            in_range=args.in_range,
            hours_since_rebalance=args.hours_since_rebalance,
        )

    # Determine deployed width for range calculation
    action = result["action"]
    deployed_width = None
    if "W10" in action:
        deployed_width = 10
    elif "W20" in action:
        deployed_width = 20
    elif "DEPLOY_W" in action:
        deployed_width = int(action.split("W")[1])
    elif "RECENTER" in action and args.current_width:
        deployed_width = args.current_width
    elif result.get("deployed_width"):
        deployed_width = result["deployed_width"]

    lp_range = None
    if deployed_width:
        lp_range = compute_lp_range(current_price, deployed_width)

    # Output
    output = {
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "data_timestamp": str(last_ts),
        "current_price": round(current_price, 2),
        "strategy": args.strategy,
        "state": args.state,
        **result,
    }
    if lp_range:
        output["lp_range"] = lp_range

    # Map to simple on-chain instructions
    action = result["action"]
    if action in ("STAY_CASH", "HOLD", "HOLD_OOR"):
        do = "HOLD"
    elif action == "GO_CASH":
        do = "CLOSE_POSITION"
    elif action.startswith("ENTER_") or action == "RECENTER_SAME_WIDTH":
        do = "OPEN_POSITION"
    else:
        do = "HOLD"

    # Print
    print(f"\n{'=' * 45}")
    print(f"  ETH/USDT 0.05%  |  ${current_price:,.2f}")
    print(f"{'=' * 45}")
    print(f"  Do:     {do}")
    if do == "OPEN_POSITION" and lp_range:
        print(f"  Width:      W{lp_range['width']}")
        print(f"  tickLower:  {lp_range['lower_tick']}")
        print(f"  tickUpper:  {lp_range['upper_tick']}")
        print(f"  fee:        500")
        print(f"  (~${lp_range['price_lower']:,.2f} - ${lp_range['price_upper']:,.2f})")
    elif do == "CLOSE_POSITION":
        print(f"  -> Remove liquidity + collect fees")
    else:
        print(f"  -> Check again next hour")
    print(f"{'=' * 45}\n")

    if args.output:
        with open(args.output, "w") as f:
            json.dump(output, f, indent=2, default=str)
        print(f"  Saved to {args.output}")

    return output


def main():
    parser = argparse.ArgumentParser(
        description="Kongtrae v2 - Hedged LP decision engine for Uniswap V3 ETH/USDT 0.05%"
    )

    # Strategy
    parser.add_argument("--strategy", default="dqn", choices=["dqn", "rule"],
                        help="Strategy: 'dqn' (shipped three-head DQN, default) or 'rule' (bb_width threshold benchmark)")

    # Market data
    parser.add_argument("--swap-csv", default=None,
                        help="Raw swap CSV (evt_block_time, sqrtPriceX96, amount0/1)")
    parser.add_argument("--ohlcv-csv", default=None,
                        help="Hourly OHLCV CSV (200+ rows for accuracy)")
    parser.add_argument("--price", type=float, default=None,
                        help="Current ETH price (quick mode, less accurate)")
    parser.add_argument("--volume", type=float, default=5_000_000,
                        help="Hourly volume USD (quick mode)")

    # Position state
    parser.add_argument("--state", default="cash", choices=["cash", "lp_in_range", "lp_oor"],
                        help="Current position state")
    parser.add_argument("--current-width", type=int, default=None,
                        help="Current LP width if in position (4, 6, 10, or 20)")
    parser.add_argument("--in-range", action="store_true",
                        help="Position is currently in range")
    parser.add_argument("--hours-since-rebalance", type=int, default=0,
                        help="Hours since last rebalance")

    # Rule strategy options
    parser.add_argument("--width", type=int, default=4,
                        help="LP width for rule strategy (default: 4)")

    # Model options
    parser.add_argument("--device", default="cpu", help="cpu or cuda")

    # Output
    parser.add_argument("-o", "--output", default=None, help="Save to JSON")

    args = parser.parse_args()
    decide(args)


if __name__ == "__main__":
    main()
