# Drift Fix Report

This document records the deployment/backtest drift fixes made after comparing
`simulation_14`, `kongtrae`, and `backtest_model_server`.

## Current Status

`simulation_14` is now good as a deployment package for the shipped Kongtrae
models, assuming the caller uses the same inputs:

- Pool/data contract: WETH/USDT, fee tier `500`, tick spacing `10`
- Timeframes: `1h`, `15min`, or `5min`
- Model aliases: `dqn_three_head_v3_1h`, `dqn_three_head_v3_15min`, `dqn_three_head_v3_5min`
- Action widths: `4,6,10,20`
- Hedge accounting for evaluation: `continuous_delta_hedged`

The 1h/15min/5min top-level model files and VecNormalize files in
`simulation_14/models/` now match the corresponding files in `kongtrae/models/`.

## What Was Wrong

### 1. Action label dialect mismatch

Kongtrae inference returns labels such as:

- `STAY_CASH`
- `ENTER_W10`
- `GO_CASH`
- `HOLD_OOR`
- `RECENTER_SAME_WIDTH`

The original `backtest_model_server` simulator expected labels like:

- `HOLD`
- `EXIT`
- `WIDTH-10`

This meant `GO_CASH` could fail to close the LP. Once one exit is missed, the
next request has the wrong state, wrong current width, wrong in-range/OOR state,
and therefore a different policy head. The action sequence then drifts.

Fix:

- `backtest_model_server/scripts/03_run_infer_backtest.py` now normalizes labels:
  - `GO_CASH`, `EXIT_TO_CASH`, `CLOSE_POSITION` -> `EXIT`
  - `ENTER_W10`, `DEPLOY_W10`, `RECENTER_W10` -> `WIDTH-10`
  - `RECENTER_SAME_WIDTH` -> `WIDTH-{current_width}`
  - `STAY_CASH`, `HOLD`, `HOLD_OOR` -> `HOLD`

### 2. LP width semantics were doubled

The training/evaluation environment treats width as total tick-spacings across
the LP range:

```text
W10 = center +/- 5 tick-spacings
```

The old deployment/viz path treated width as tick-spacings on each side:

```text
W10 = center +/- 10 tick-spacings
```

That doubles the range. It changes whether the LP is in range, fee accrual,
OOR state, re-enter/recenter decisions, and future observations.

Fix:

- `simulation_14/inference.py` now computes:

```python
half_width_ticks = width * TICK_SPACING // 2
lower_tick = center_tick - half_width_ticks
upper_tick = center_tick + half_width_ticks
```

This matches `UniswapV3PaperEnv._compute_position_bounds`.

### 3. Wrong pool/data prefix risk

Kongtrae was trained/evaluated on WETH/USDT fee tier `500`, tick spacing `10`.
The server data pull path had a hard-coded non-training pool prefix. Similar
ETH/stable prices can look close, but volume, liquidity, and technical features
can differ enough to flip model actions.

Fix:

- `backtest_model_server/config/backtest_config.yaml` now has:

```yaml
pool_prefix: "eth_usdt_0p05"
```

- `backtest_model_server/scripts/01_pull_data.py` uses `pool_prefix` from config.
- `simulation_14/training/uniswap_v3_ppo_paper.py` is synced back to the
  ETH/USDT filename contract used by `kongtrae`.

### 4. Dashboard hid exits

The dashboard plotted enter/recenter markers, but not `exit_to_cash`. This made
two different-looking plots even when the trace contained cash exits.

Fix:

- `backtest_model_server/scripts/05_plot_dashboard.py` now plots red exit
  markers for `exit_to_cash`.

### 5. Server API dependency blocked local verification

The HTTP path requires `localhost:4001`. On this machine the server was not
running, so a direct end-to-end server replay could not be executed.

Fix:

- Added `backtest_model_server/scripts/09_run_local_kongtrae_backtest.py`.
- This runner loads the shipped Kongtrae model and VecNormalize locally, writes
  output into `backtest_model_server/results/`, and lets the normal metrics and
  plot scripts run without the API server.

### 6. No hard timestamp-by-timestamp comparator

Screenshots can be misleading. The reliable check is timestamp-level action and
portfolio-value equality.

Fix:

- Added `backtest_model_server/scripts/08_compare_kongtrae_trace.py`.
- It compares canonical Kongtrae output against server/local-server output and
  reports first mismatches.

## Verification Result

For the window:

```text
2026-04-11 00:00 UTC -> 2026-04-14 23:00 UTC
```

The local `backtest_model_server` Kongtrae runner matched the old canonical
Kongtrae replay:

```text
action mismatches  : 0
action match rate  : 100.00%
max abs PV diff    : $0.000000
final canonical PV : $1015.686548
final server PV    : $1015.686548
```

Model PnL:

```text
Final PV: $1,015.686548
PnL:      +$15.686548
```

## Commands To Reproduce

From the repository root:

```bash
MPLCONFIGDIR=/tmp/mpl_kongtrae .venv/bin/python backtest_model_server/scripts/09_run_local_kongtrae_backtest.py
python3 backtest_model_server/scripts/04_compute_metrics.py
MPLCONFIGDIR=/tmp/mpl_kongtrae .venv/bin/python backtest_model_server/scripts/05_plot_dashboard.py
python3 backtest_model_server/scripts/08_compare_kongtrae_trace.py
```

Expected comparator output:

```text
action mismatches  : 0
action match rate  : 100.00%
max abs PV diff    : $0.000000
```

## If A Friend Still Gets Different Results

If the result still differs after these fixes, they are not running the same
backtest. Check these first:

- Same model zip and VecNormalize pickle
- Same timeframe
- Same `pool_prefix`
- Same OHLCV/history window
- Same action width list
- Same width semantics
- Same `GO_CASH -> EXIT` handling
- Same current position state and current width between calls

The comparator script should be used before looking at plots.
