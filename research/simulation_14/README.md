# Kongtrae v2 – Three-Head DQN for Uniswap V3 LP

Deep RL agent (Three-Head Double-Dueling DQN) for delta-hedged concentrated liquidity on ETH/USDT 0.05%.

## Performance (Walk-Forward Cross-Validation, $1K capital)

| Fold | Test Period | DQN PnL | Widths Used |
|------|-------------|---------|-------------|
| 0 | Aug-Sep 2025 | +$330 | W4 55%, W6 28%, W10 2%, W20 15% |
| 1 | Sep-Oct 2025 | +$215 | W4 27%, W6 9%, W10 24%, W20 39% |
| 2 | Oct-Nov 2025 | +$256 | W6 68%, W10 29%, W20 2% |
| 3 | Nov-Dec 2025 | **+$287** | W4 28%, W6 25%, W10 31%, W20 16% |

**All 4 folds positive.** Mean +$272/fold. The model learns to pick different widths per market regime.

### Shipped Model: Fold 3 (most robust)

Selected for generalizability, not peak PnL:
- **Best eval→test consistency** (0.95 ratio — what it learned transferred almost perfectly)
- **Most balanced width mix** (no single width >31%) — adapts to market conditions
- **Most recent training data** (Apr-Oct 2025)
- **Active management** (255 trades/month vs fold 2's 15)

## Quick Start

```bash
pip install numpy pandas torch stable-baselines3 gymnasium
```

### DQN Model (Default)

```bash
# With OHLCV data (accurate):
python kongtrae/inference.py --ohlcv-csv hourly_eth.csv

# Quick mode (just price):
python kongtrae/inference.py --price 3000

# When you have an LP position that went out of range:
python kongtrae/inference.py --ohlcv-csv hourly_eth.csv --state lp_oor --current-width 4

# When you have an in-range position:
python kongtrae/inference.py --ohlcv-csv hourly_eth.csv --state lp_in_range
```

### Rule Strategy (Benchmark Alternative)

```bash
python kongtrae/inference.py --strategy rule --ohlcv-csv hourly_eth.csv
```

## How It Works

### The Shipped DQN

1. **State-aware control**: one shared DQN trunk with separate heads for `cash`, `lp_in_range`, and `lp_oor`
2. **Entry widths**: chooses among `W4`, `W6`, `W10`, and `W20`
3. **In-range**: `HOLD` or `GO_CASH`
4. **OOR**: `HOLD_OOR`, `GO_CASH`, or `RECENTER_SAME_WIDTH`
5. **Hedge**: short 80% of ETH delta to isolate fee income from first-order price exposure

### Rule Baseline

1. **Timing**: Deploy LP when `bb_width > expanding_median(bb_width)`
2. **Width**: fixed `W4`
3. **OOR**: recenter at the same width
4. **Hedge**: short 80% of ETH delta

### Why It Works

Concentrated LP is short convexity. You earn fees and pay a residual LP cost after hedging.
The shipped DQN learns when to stay cash, which width to deploy, and when to wait or recenter once OOR.
The rule strategy is kept as a simple benchmark.

## DQN Action Map

The model outputs an action integer (0-5). What it means depends on your current state:

| Action | `--state cash` | `--state lp_in_range` | `--state lp_oor` |
|--------|---------------|----------------------|------------------|
| 0 | STAY_CASH | HOLD | HOLD_OOR |
| 1 | ENTER_W4 | GO_CASH | GO_CASH |
| 2 | ENTER_W6 | *(masked)* | RECENTER_SAME_WIDTH |
| 3 | ENTER_W10 | *(masked)* | *(masked)* |
| 4 | ENTER_W20 | *(masked)* | *(masked)* |
| 5 | *(masked)* | *(masked)* | *(masked)* |

**What to do for each output:**
- **STAY_CASH** — Do nothing, check again next hour
- **ENTER_W4/W6/W10/W20** — Open LP position at that width + open hedge (short 80% delta)
- **HOLD** — Position is earning fees, do nothing
- **HOLD_OOR** — Stay out of range, wait for price to come back
- **GO_CASH** — Close LP position + close hedge
- **RECENTER_SAME_WIDTH** — Close current LP, reopen at current price with same width + rebalance hedge

Width = number of tick spacings above and below center. W4 = tightest (~0.4% range), W20 = widest (~2% range).

## Hourly Workflow

```
Hour 1:  inference.py --state cash             -> "ENTER_W10"           -> Open LP + hedge
Hour 2:  inference.py --state lp_in_range      -> "HOLD"                -> Do nothing
Hour 3:  inference.py --state lp_in_range      -> "HOLD"                -> Do nothing
Hour 4:  inference.py --state lp_oor --current-width 10 -> "RECENTER_SAME_WIDTH" -> Close, reopen at current price
Hour 5:  inference.py --state lp_in_range      -> "HOLD"                -> Do nothing
...
```

**Important:** You must tell the model your current state via `--state`. The model doesn't track state between runs.

## OHLCV Data Format

```csv
timestamp,open,high,low,close,volume
2026-04-09 00:00:00,3000,3020,2990,3010,8000000
2026-04-09 01:00:00,3010,3015,3000,3005,6500000
...
```

Need 200+ hourly rows for full indicator accuracy. You can use Binance 1h candles for ETH/USDT.

## Hedging

For every $1K deployed as LP:
- Short ~0.80 * ($1K / ETH_price) ETH on a perp/futures exchange
- Rebalance hedge when position changes (enter, exit, recenter)
- Funding cost: ~$0.50-1.00/day at typical rates

At $1K capital with the bundled fold-3 model, backtests showed:
- ~$4-8/day gross fee income
- ~$2-4/day after IL and funding
- roughly ~$215 to ~$330 per one-month fold in the packaged walk-forward run

These results assume active delta hedging at observed swap prices and do not include hedge slippage, latency, or exchange execution fees.

## Files

| File | Description |
|------|-------------|
| `inference.py` | Decision engine (rule + DQN) |
| `models/dqn_three_head_v2.zip` | Three-head Double-Dueling DQN model |
| `models/dqn_three_head_v2_vecnormalize.pkl` | Observation normalization stats |

## CLI Options

| Flag | Default | Description |
|------|---------|-------------|
| `--strategy` | `dqn` | `dqn` (default) or `rule` |
| `--ohlcv-csv` | - | Hourly OHLCV CSV path |
| `--swap-csv` | - | Raw Uniswap swap CSV path |
| `--price` | - | Quick mode: just ETH price |
| `--state` | `cash` | `cash`, `lp_in_range`, or `lp_oor` |
| `--current-width` | - | Current LP width (4, 6, 10, or 20) |
| `--width` | 4 | LP width for rule strategy |
| `--in-range` | false | Position currently in range |
| `--hours-since-rebalance` | 0 | Hours since last rebalance |
| `-o` | - | Save output to JSON |

## Capital Scaling

| Capital | Optimal Width | Expected Monthly PnL |
|---------|---------------|---------------------|
| $1K | W10 | ~$130 |
| $10K | W10 | ~$800 |
| $50K | W15-W20 | ~$1,500 |
| $100K+ | W20 | Diminishing (pool saturation) |

Max ~$10-20K per position before returns degrade due to liquidity share saturation.

## Not Financial Advice

Research models only. Past performance does not guarantee future results.
Smart contract risk, oracle risk, and market structure changes can invalidate backtested returns.
