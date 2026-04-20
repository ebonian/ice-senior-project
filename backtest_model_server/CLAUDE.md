# CLAUDE.md — Backtest Model Server

## Pool naming convention (read before renaming anything)

The monitored pool is **ETH/USDC 0.05%** on Arbitrum (address `0xC6962004f452bE9203591991D15f6b388e09E8D0`). All pool-side code, config (`pool_prefix: "eth_usdc_0p05"`), comments, and docs say **USDC**. The only place **USDT** appears is the Binance comparison step: Binance lists no ETH/USDC spot pair, so we use `ETHUSDT` as the off-chain reference. Do **not** rename pool/B2 references to USDT, and do **not** rename the Binance `ETHUSDT` symbol to USDC.

## Project Overview

Offline harness that replays historical market data against a running model server (`model/`, port 4001) to measure strategy P&L vs. always-cash / HODL baselines. Pulls raw swaps + daily OHLCV from B2 under `eth_usdc_0p05/`, concatenates into an hourly OHLCV parquet, runs `/infer/{strategy}` one step at a time, and produces metrics + plots.

## Pipeline

Run scripts in order (config: `config/backtest_config.yaml`):

1. `01_pull_data.py` — downloads B2 raw swap parquets + daily OHLCV for the date range into `data/raw_swaps/`. Uses `pool_prefix` from config (default `eth_usdc_0p05`).
2. `02_prepare_ohlcv.py` — concatenates daily OHLCV into `data/ohlcv/hourly_ohlcv.parquet` and validates vs. Binance `ETHUSDT` median.
3. `03_run_infer_backtest.py` — replays each hour through the model server, logs decisions.
4. `04_compute_metrics.py` — computes Sharpe, max drawdown, vs-baseline deltas.
5. `05_plot_dashboard.py` — renders the decision/portfolio/market dashboards (price label: `ETH/USDC Price`).
6. `06_audit_b2_prices.py`, `07_audit_ohlcv_quality.py` — data-quality audits.

Multi-strategy run: `run_all_strategies.py` fans out step 3 across `simulation_14_1h`, `simulation_14_15min`, `simulation_14_5min`.

## Key config fields (`backtest_config.yaml`)

- `pool_prefix: "eth_usdc_0p05"` — B2 prefix. Must match the model/eval pool.
- `pool_fee: 0.0005`, `decimals0: 18`, `decimals1: 6` — ETH/USDC 0.05% tier.
- `binance_deviation_threshold_pct` — halt if swap-derived vs. Binance `ETHUSDT` median diverge too far.
