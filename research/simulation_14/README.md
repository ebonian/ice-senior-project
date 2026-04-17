# Kongtrae v3 – Three-Head DQN for Uniswap V3 LP

Deep RL agent (Three-Head Double-Dueling DQN) for delta-hedged concentrated liquidity on ETH/USDT 0.05%.

## Performance (Walk-Forward Cross-Validation, $1K capital)

### 1h v3 model

| Fold | DQN Test PnL | Behavior Note |
|------|--------------|---------------|
| 0 | +$562 | Best explanation fold: W4/W10/W20 mix with some cash/exits |
| 1 | +$435 | Positive, but more W6-dominant |
| 2 | +$487 | Positive, but loses to paper on this window |
| 3 | +$718 | Highest-PnL alternate, but less mixed than fold 0 |

**Nominal gate:** mean +$550, median +$524, worst +$435, beat always-cash 4/4 folds, beat paper W4 threshold rule 3/4 folds, invalid actions 0.

### 5min v3 model

| Fold | DQN Test PnL |
|------|--------------|
| 0 | +$668 |
| 1 | +$220 |
| 2 | +$660 |
| 3 | +$279 |

**Comparison gate:** mean +$457, median +$469, beat always-cash 4/4 folds, beat paper W4 threshold rule 0/4 folds, invalid actions 0.

### 15min v3 model

| Fold | DQN Test PnL | Behavior Note |
|------|--------------|---------------|
| 0 | +$1,385 | High PnL, mostly W4/W6 |
| 1 | +$649 | Positive, but close to fixed W6 |
| 2 | +$169 | Most mixed/explainable policy, lower PnL |
| 3 | +$885 | Best shipped compromise: W10/W6/W20 mix with some cash/exits |

**Candidate gate:** mean +$773, median +$769, worst +$169, beat always-cash 4/4 folds, beat paper W4 threshold rule 2/4 folds, invalid actions 0.

### Shipped Aliases

- `v3_1h` is the strongest project candidate and the default for `--timeframe 1h`.
- `v3_15min` is packaged as a high-PnL candidate and the default for `--timeframe 15min`.
- `v3_5min` is saved for comparison/demo and is the default for `--timeframe 5min`.
- The 1h alias uses fold 0 because it gives the clearest width-selection explanation while still beating the paper rule.
- The 15min alias uses fold 3, not because it has the highest test PnL, but because it is the best compromise between explainable behavior and held-out PnL.

Stress note: under the conservative fee/liquidity stress test (`fee_haircut=0.5`, `active_liquidity_multiplier=2.0`), both 1h and 15min candidates lost money. Treat this as a research/project model, not a live deployable trading system without fresh venue validation.

## Quick Start

```bash
pip install numpy pandas torch stable-baselines3 gymnasium
```

### DQN Model (Default)

```bash
# With OHLCV data (accurate):
python kongtrae/inference.py --ohlcv-csv hourly_eth.csv

# Explicit 1h v3 model:
python kongtrae/inference.py --timeframe 1h --model-version v3_1h --ohlcv-csv hourly_eth.csv

# 15min v3 candidate model:
python kongtrae/inference.py --timeframe 15min --model-version v3_15min --ohlcv-csv eth_15min.csv

# 5min v3 comparison model:
python kongtrae/inference.py --timeframe 5min --model-version v3_5min --ohlcv-csv eth_5min.csv

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
5. **Hedge**: continuous delta-hedged accounting in backtest; inference assumes the LP is hedged externally when positions are opened, closed, or recentered

### Rule Baseline

1. **Timing**: Deploy LP when `bb_width > expanding_median(bb_width)`
2. **Width**: fixed `W4`
3. **OOR**: recenter at the same width
4. **Hedge**: same continuous delta-hedged accounting assumptions as the DQN evaluation

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
- **STAY_CASH** — Do nothing, check again next bar
- **ENTER_W4/W6/W10/W20** — Open LP position at that width + open hedge (short 80% delta)
- **HOLD** — Position is earning fees, do nothing
- **HOLD_OOR** — Stay out of range, wait for price to come back
- **GO_CASH** — Close LP position + close hedge
- **RECENTER_SAME_WIDTH** — Close current LP, reopen at current price with same width + rebalance hedge

Width = number of tick spacings above and below center. W4 = tightest (~0.4% range), W20 = widest (~2% range).

## Bar Workflow

```
Bar 1:  inference.py --state cash             -> "ENTER_W10"           -> Open LP + hedge
Bar 2:  inference.py --state lp_in_range      -> "HOLD"                -> Do nothing
Bar 3:  inference.py --state lp_in_range      -> "HOLD"                -> Do nothing
Bar 4:  inference.py --state lp_oor --current-width 10 -> "RECENTER_SAME_WIDTH" -> Close, reopen at current price
Bar 5:  inference.py --state lp_in_range      -> "HOLD"                -> Do nothing
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

For every LP position:
- Hedge the LP inventory externally using the model's continuous delta-hedged accounting assumption
- Rebalance hedge when position changes (enter, exit, recenter)
- Funding is included in the backtest reward/accounting model

At $1K capital, nominal walk-forward backtests showed +$435 to +$718 per one-month held-out fold for 1h and +$169 to +$1,385 for 15min.

These results assume active delta hedging at observed swap prices and do not include hedge slippage, latency, or exchange execution fees.

## Training Different Timeframes

The trainer supports `1h`, `15min`, and `5min` bars. The accounting still uses exact observed swaps inside each bar, active hedge funding is prorated by bar length, and episode/fold windows remain wall-clock based.

```bash
MPLCONFIGDIR=/tmp python kongtrae/training/train_hedged_three_head_v2_dqn.py \
  --timeframe 15min \
  --save-name dqn_three_head_v3_15min_experiment \
  --tb-log tb_dqn_three_head_v3_15min_experiment
```

```bash
MPLCONFIGDIR=/tmp python kongtrae/training/train_hedged_three_head_v2_dqn.py \
  --timeframe 5min \
  --save-name dqn_three_head_v3_5min_experiment \
  --tb-log tb_dqn_three_head_v3_5min_experiment
```

Walk-forward validation accepts the same flag:

```bash
MPLCONFIGDIR=/tmp python kongtrae/training/walk_forward_three_head_v2_dqn.py \
  --timeframe 15min \
  --run-prefix wf_three_head_v2_15min \
  --save-dir walk_forward_three_head_v2_15min
```

Inference also accepts the same timeframe, so the model must be queried with matching OHLCV cadence and matching action widths:

```bash
python kongtrae/inference.py \
  --timeframe 15min \
  --ohlcv-csv eth_15min.csv \
  --model-version v3_15min \
  --action-widths 4,6,10,20 \
  --state cash
```

## Files

| File | Description |
|------|-------------|
| `inference.py` | Decision engine (rule + DQN) |
| `models/dqn_three_head_v3_1h.zip` | Top-level 1h v3 Three-Head Double-Dueling DQN alias |
| `models/dqn_three_head_v3_1h_vecnormalize.pkl` | 1h v3 observation normalization stats |
| `models/dqn_three_head_v3_15min.zip` | Top-level 15min v3 candidate model alias |
| `models/dqn_three_head_v3_15min_vecnormalize.pkl` | 15min v3 observation normalization stats |
| `models/dqn_three_head_v3_5min.zip` | Top-level 5min v3 comparison model alias |
| `models/dqn_three_head_v3_5min_vecnormalize.pkl` | 5min v3 observation normalization stats |
| `models/dqn_three_head_v3_manifest.json` | Saved-model provenance and gate summary |
| `models/three_head_v3_1h/` | Fold-level 1h selected checkpoints |
| `models/three_head_v3_15min/` | Fold-level 15min selected checkpoints |
| `models/three_head_v3_5min/` | Fold-level 5min selected checkpoints |
| `models/dqn_three_head_v2.zip` | Older v2 backup model |

## CLI Options

| Flag | Default | Description |
|------|---------|-------------|
| `--strategy` | `dqn` | `dqn` (default) or `rule` |
| `--ohlcv-csv` | - | OHLCV CSV path at `--timeframe` cadence |
| `--swap-csv` | - | Raw Uniswap swap CSV path |
| `--timeframe` | `1h` | Model bar size: `1h`, `15min`, or `5min` |
| `--price` | - | Quick mode: just ETH price |
| `--state` | `cash` | `cash`, `lp_in_range`, or `lp_oor` |
| `--current-width` | - | Current LP width (4, 6, 10, or 20) |
| `--width` | 4 | LP width for rule strategy |
| `--model-dir` | `kongtrae/models` | Directory containing the DQN `.zip` and VecNormalize `.pkl` |
| `--model-version` | `auto` | `auto`, `v3_1h`, `v3_15min`, `v3_5min`, `v2`, or explicit filename prefix |
| `--action-widths` | `4,6,10,20` | Width catalog used by the trained DQN |
| `--full-recenter-actions` | false | Only enable for models trained with full width-recenter actions |
| `--in-range` | false | Position currently in range |
| `--hours-since-rebalance` | 0 | Hours since last rebalance |
| `-o` | - | Save output to JSON |

## Not Financial Advice

Research models only. Past performance does not guarantee future results.
Smart contract risk, oracle risk, and market structure changes can invalidate backtested returns.
