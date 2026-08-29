"""Bridge to the existing harness's verified Uniswap V3 math.

`scripts/03_run_infer_backtest.py` is not an importable module name (leading
digit), so it is loaded by path. Nothing in it runs at import time except
logging setup — `main()` sits behind an `if __name__ == "__main__"` guard.

Everything re-exported here was independently verified correct by the strategy
review (bot `analysis/strategy-review/04-backtest-design.md` §2.1): the closed-form
position value, the token0 delta, the liquidity inversion, the per-swap fee
formula, and the `L_raw = L_human x 10^((d0+d1)/2)` unit scale. Gate 1 extends
around these; it does not re-derive them.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]  # backtest_model_server/
_SCRIPT = BASE_DIR / "scripts" / "03_run_infer_backtest.py"


def _load():
    spec = importlib.util.spec_from_file_location("_bt_infer", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_bt_infer"] = mod
    spec.loader.exec_module(mod)
    return mod


bt = _load()

# --- verified V3 math (04-backtest-design.md §2.1) --------------------------
price_to_tick = bt.price_to_tick
tick_to_price = bt.tick_to_price
human_tick_to_v3_tick = bt.human_tick_to_v3_tick
v3_tick_to_human_tick = bt.v3_tick_to_human_tick
compute_position_value = bt.compute_position_value
compute_lp_delta = bt.compute_lp_delta
compute_liquidity_from_capital = bt.compute_liquidity_from_capital
compute_exit_swap_fraction = bt.compute_exit_swap_fraction
compute_swap_fraction = bt.compute_swap_fraction
_tick_in_range_fraction = bt._tick_in_range_fraction

# --- the pieces gate1 tests against, rather than reuses ---------------------
compute_fee = bt.compute_fee
HourlySwapData = bt.HourlySwapData


def liquidity_scale(decimals0: int = 18, decimals1: int = 6) -> float:
    """L_raw = L_human x 10^((d0+d1)/2). For 18/6 this is 1e12."""
    return 10 ** ((decimals0 + decimals1) / 2)


def v3_tick_to_price(v3_tick: int, decimals0: int = 18, decimals1: int = 6) -> float:
    """On-chain tick -> human ETH/USDC price."""
    return tick_to_price(v3_tick_to_human_tick(int(v3_tick), decimals0, decimals1))
