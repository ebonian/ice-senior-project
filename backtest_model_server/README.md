# Model Server Backtest Harness

End-to-end workflow to evaluate the llaminet model server against historical B2 swap data.
Replays hourly inference decisions, simulates portfolio outcomes, and produces a 4-panel dashboard.

## Prerequisites

- Python environment with `pandas`, `numpy`, `matplotlib`, `requests`, `pyyaml`, `pyarrow`
- B2 credentials in environment: `B2_ACCOUNT_ID`, `B2_ACCOUNT_KEY`, `B2_BUCKET_NAME`
- Model server runnable from `C:/Coding/llaminet/model/`

## Quick start

All commands run from `C:/Coding/llaminet/research/backtest_model_server/`.

### One-command run (model server already running)

```bat
run_backtest.bat
```

Optional custom config path:

```bat
run_backtest.bat config\backtest_config.yaml
```

### Step 1 — Configure

Edit `config/backtest_config.yaml`:

```yaml
start_date: "2025-10-01"
end_date:   "2025-10-31"
server_url: "http://localhost:4001"
strategy:   "default"
initial_capital_usd: 1000.0
```

### Step 2 — Pull B2 data

```bash
python scripts/01_pull_data.py
# Dry-run (list available dates without downloading):
python scripts/01_pull_data.py --list
```

Downloads raw swap parquet files to `data/raw_swaps/raw/swaps/` and `data/raw_swaps/raw/prices/`.

### Step 3 — Build OHLCV + validate

```bash
python scripts/02_prepare_ohlcv.py
# Skip Binance validation (offline / quick run):
python scripts/02_prepare_ohlcv.py --skip-validation
```

Converts raw swaps to hourly OHLCV, validates against Binance (halts if median price deviation > 0.5%).
Output: `data/ohlcv/hourly_ohlcv.parquet`, `data/ohlcv/binance_comparison.png`.
The script auto-detects both `data/raw_swaps/raw/swaps/` and legacy `data/raw_swaps/swaps/`.

### Step 4 — Start the model server

In a separate terminal:

```bash
cd C:/Coding/llaminet/model
uv sync
uvicorn app.main:app --host 0.0.0.0 --port 4001
```

Verify: `curl http://localhost:4001/health`

### Step 5 — Run the backtest

```bash
python scripts/03_run_infer_backtest.py
# Resume an interrupted run:
python scripts/03_run_infer_backtest.py --resume
# Preview request bodies without calling the server:
python scripts/03_run_infer_backtest.py --dry-run
```

Calls `POST /infer/{strategy}` for each hourly step with `reference_date` set to replay
historical B2 data. Outputs:

| File | Description |
|------|-------------|
| `results/inference_log.csv` | Per-step HTTP observability (latency, status, action, price, staleness) |
| `results/trace_df.parquet` | Full simulation trace (input to metrics + plots) |

**Performance note:** each unique `reference_date` triggers a fresh B2 download on the model
server (~2–3 s per call). A 31-day × 24h backtest = 744 calls ≈ 25–38 min.
The `--resume` flag lets you continue after interruptions without re-running completed steps.

### Step 6 — Compute metrics

```bash
python scripts/04_compute_metrics.py
```

Outputs:

| File | Description |
|------|-------------|
| `results/metrics.json` | All metrics as JSON (model + baselines) |
| `results/summary.md` | Human-readable comparison table |

Runs two baselines automatically:
- **Always-cash**: stays at initial capital, PnL = 0.
- **HODL**: buys ETH at first observed price, holds throughout.

### Step 7 — Plot dashboard

```bash
python scripts/05_plot_dashboard.py
# Open popup windows in addition to saving PNGs:
python scripts/05_plot_dashboard.py --show
```

Writes four PNGs to `plots/`:

| File | Contents |
|------|----------|
| `serving_health.png` | Latency distribution + over-time, error rate by status code, data staleness |
| `decision_analysis.png` | Daily action stacks, cumulative counts, hold-streak histogram |
| `portfolio_performance.png` | Equity curve (model vs HODL), drawdown, position-state timeline |
| `market_context.png` | Price chart with LP range bands + entry/recenter markers, realised volatility |

## Configuration reference

All options in `config/backtest_config.yaml`:

| Key | Default | Description |
|-----|---------|-------------|
| `start_date` | `"2025-10-01"` | Backtest start (ISO date) |
| `end_date` | `"2025-10-31"` | Backtest end (inclusive) |
| `server_url` | `"http://localhost:4001"` | Model server base URL |
| `strategy` | `"default"` | Strategy name for `/infer/{strategy}` |
| `api_key` | `null` | API key (or set `MODEL_API_KEY` env var) |
| `initial_capital_usd` | `1000.0` | Starting portfolio value |
| `cadence_hours` | `1` | Steps per hour |
| `tick_spacing` | `10` | Uniswap V3 tick spacing (ETH/USDC 0.05%) |
| `fee_tier_bps` | `5` | Pool fee tier in basis points |
| `tx_cost_usd` | `2.0` | Flat cost per enter/recenter |
| `slippage_bps` | `1` | Slippage on each rebalance |
| `base_fee_annual_pct` | `30.0` | Full-range LP APY baseline for fee simulation |
| `binance_deviation_threshold_pct` | `0.5` | Max acceptable price deviation vs Binance |
| `max_retries` | `3` | Retry count on HTTP 503 |
| `retry_backoff_base` | `1.0` | Exponential backoff base (seconds) |
| `request_timeout` | `30` | Per-request timeout (seconds) |

## Output directory layout

```
results/
├── inference_log.csv       # step, timestamp, status_code, latency_ms, action_label, ...
├── trace_df.parquet        # simulation trace (portfolio_value, position_state, effective_action, ...)
├── metrics.json            # all metrics: model_server, always_cash, hodl
└── summary.md              # markdown comparison table

plots/
├── serving_health.png
├── decision_analysis.png
├── portfolio_performance.png
└── market_context.png

data/
├── raw_swaps/
│   └── raw/
│       ├── swaps/YYYY-MM-DD/   # raw 15-min swap parquets from B2
│       └── prices/YYYY-MM-DD/
└── ohlcv/
    ├── hourly_ohlcv.parquet
    ├── ohlcv_candles.png
    ├── binance_comparison.csv
    └── binance_comparison.png
```

## Simulation model

The portfolio simulation uses a simplified LP model:

- **In-range**: 50% price exposure (balanced ETH/USDC LP approximation) + fee accrual scaled by concentration factor (`sqrt(upper/lower) / (sqrt(upper/lower) - 1)`).
- **OOR below range**: 100% ETH exposure (all capital in ETH), no fees.
- **OOR above range**: 0% price exposure (all capital in USDC), no fees.
- **Rebalance cost**: `tx_cost_usd` + `slippage_bps × portfolio_value` deducted on each enter or recenter.

The fee model is a calibrated approximation. For production accuracy, replace with on-chain fee data.

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `Cannot reach server at http://localhost:4001` | Start `uvicorn app.main:app --port 4001` in the model directory |
| `B2 credentials error` | Export `B2_ACCOUNT_ID`, `B2_ACCOUNT_KEY`, `B2_BUCKET_NAME` |
| `No parquet files found in data/raw_swaps/...` | Run `01_pull_data.py` first |
| Validation fails (deviation > 0.5%) | Check B2 data quality; widen `binance_deviation_threshold_pct` if expected |
| Slow backtest | Use `--resume` to checkpoint; reduce date range for testing |
| `Strategy 'default' not loaded` (HTTP 404) | Upload a model via `POST /models/default/upload` before running |
