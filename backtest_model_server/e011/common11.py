"""E011 shared plumbing: E010's engine path, loaded once, unmodified.

Everything venue- and capital-defining is imported from e010/e005/gate1
(loop/experiments/E011-link-ceiling.md pre-registers this file's imports as
the frozen surface):

  REUSED BY IMPORT (no copies):
    e010/registry.py      capital split, gas envelope reader, window, arms
    e010/race10.py        load_spec10 / load_marks10 / load_funding10 and the
                          e005 race module it loads by file path (R5):
                          PoolSpec, run_arm, always_cash, load_swaps, Bucket
    e006/oracle.py        dp_select, streaks_of, hour_grid  (the DP)
    e007/constrained_oracle.py  dp_minhold, dp_grain        (coarseness)
    e006/signals.py       trailing_signals, auc             (descriptive)

  WRITTEN HERE (venue-specific, no engine semantics):
    two-leg hourly payoff construction (oracle11.py), the coupled gas/HPL
    point patching, and the streak slicer (e006/exact.py's simulate_streak
    re-expressed against e005's run_arm signature).

Import order matters: registry then race10 establish sys.path with e005
ahead of e003 for bare imports they perform; the e006/e007 modules are
loaded by explicit file path afterwards and re-order sys.path for their own
bare imports. Nothing in e011 bare-imports `race` — the e005 engine is only
ever referenced through R5.
"""

from __future__ import annotations

import contextlib
import importlib.util as _ilu
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

E011 = Path(__file__).resolve().parent
BMS = E011.parent
E010 = BMS / "e010"
OUT = E011 / "out"
DATA = E011 / "data"

if str(E010) not in sys.path:
    sys.path.insert(0, str(E010))

import registry as R  # noqa: E402  (e010 — sets sys.path for gate1/e003/e005)
import race10  # noqa: E402         (e010 — loads e005 race as R5)
from engine import cost_model as CM  # noqa: E402

R5 = race10.R5                       # the e005 simulator module


def _load_by_path(name: str, path: Path):
    spec = _ilu.spec_from_file_location(name, path)
    mod = _ilu.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


E6O = _load_by_path("e006_oracle", BMS / "e006" / "oracle.py")
E7C = _load_by_path("e007_constrained", BMS / "e007" / "constrained_oracle.py")
E6S = _load_by_path("e006_signals", BMS / "e006" / "signals.py")

SLUG = "m_link_weth_0p30"
CHAIN = "mainnet"
CAPITAL = R.REFERENCE_CAPITAL_USD                    # 10_000
LP_CAPITAL = R.lp_notional(CAPITAL)                  # 7147.887...
TARGET_10PCT = R.target_usd_per_day(CAPITAL)         # 2.7397.../day
TARGET_20PCT = 2.0 * TARGET_10PCT
POINTS = ("optimistic", "central", "pessimistic")    # coupled gas+HPL names
ENVELOPE_BY_NAME = R.ENVELOPE_BY_NAME

E010_RESULTS = {
    p: E010 / "out" / SLUG / f"lag1h_rh1h_cap10000_gas-{p}" / "results.json"
    for p in POINTS
}


@contextlib.contextmanager
def chain_gas(point: str):
    """Patch the frozen gas constant to the chain's measured envelope point
    for the duration — exactly race10.py's mechanism, restored after."""
    prev = CM.GAS_USD_PER_TX
    CM.GAS_USD_PER_TX = R.gas_usd_per_tx(CHAIN, point)
    try:
        yield CM.GAS_USD_PER_TX
    finally:
        CM.GAS_USD_PER_TX = prev


_cache: dict = {}


def load_all():
    """(spec, swaps, funding, marks) for the E011 venue — E010's loaders."""
    if "spec" not in _cache:
        spec, chain = race10.load_spec10(SLUG)
        assert chain == CHAIN
        marks = race10.load_marks10(spec.token1)
        funding = {c: race10.load_funding10(c)
                   for c in (spec.coin0, spec.coin1)}
        swaps = R5.load_swaps(spec, R.WINDOW_START, R.WINDOW_END, marks,
                              E010 / "data" / "swaps" / spec.slug)
        _cache.update(spec=spec, marks=marks, funding=funding, swaps=swaps)
    return _cache["spec"], _cache["swaps"], _cache["funding"], _cache["marks"]


def arms():
    spec, _, _, _ = load_all()
    return R.arms_for_spacing(spec.tick_spacing)


def window_days(swaps) -> float:
    ts = swaps["timestamp"].to_numpy(np.int64)
    return (int(ts[-1]) - int(ts[0])) / 86400.0


def simulate_streak(arm: dict, t_from: int, t_to: int):
    """e006/exact.py's simulate_streak against e005's run_arm: fresh mint at
    the slice's first swap, lag1h_rh1h loop inside, burn + flatten at its
    last swap. A slice spanning the whole window IS E010's race run."""
    spec, swaps, funding, marks = load_all()
    ts_all = swaps["timestamp"].to_numpy(np.int64)
    a = int(np.searchsorted(ts_all, t_from, side="left"))
    b = int(np.searchsorted(ts_all, t_to, side="left"))
    sub = swaps.iloc[a:b].reset_index(drop=True)
    if len(sub) < 2:
        return None
    tse = sub["timestamp"].to_numpy(np.int64)
    h0 = (int(tse[0]) // 3600 + 1) * 3600
    h1 = (int(tse[-1]) // 3600) * 3600
    hour_ts = np.arange(h0, h1 + 1, 3600, dtype=np.int64)
    hour_idx = np.searchsorted(tse, hour_ts, side="right") - 1
    hour_px = np.where(hour_idx >= 0,
                       sub["price"].to_numpy()[np.clip(hour_idx, 0, None)],
                       np.nan)
    return R5.run_arm(spec, arm, sub, funding, marks, hour_ts, hour_px,
                      hour_idx, detect_lag_hours=1, rehedge_hours=1,
                      lp_capital=LP_CAPITAL)


BUCKET_FIELDS = [f for f in R5.Bucket.__dataclass_fields__ if f != "label"]


def add_bucket(dst: dict, b) -> None:
    for f in BUCKET_FIELDS:
        dst[f] = dst.get(f, 0.0) + getattr(b, f)


def net_usd(tot: dict, point) -> float:
    return (tot["lp_value_change_usd"] + tot["lp_fees_usd"]
            - tot["onchain_cost_usd"] + tot["hedge_price_pnl_usd"]
            + tot["funding_usd"] - point.cost(tot["rehedge_notional_usd"]))


def read_json(p: Path) -> dict:
    return json.loads(p.read_text())


def write_json(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, indent=2, sort_keys=False))
