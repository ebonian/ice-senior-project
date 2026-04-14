# Run Configuration: run_004

**Last updated**: 2026-02-16 16:01:45
**Data**: research/simulation_13/training_data (or sim12 for swap CSV)

## Action Space

### DQN / LSTM DQN
- **Widths**: [1, 3, 5, 10, 20, 40] (tick_spacing units, ~0.1% to 1.0% ranges)
- **Always centered** at current price (no directional offset)
- **Total actions**: 1 (HOLD) + 6 = 7
- Action 0 = HOLD, Actions 1-6 = width choices

### PPO
- **Action ticks**: [0, 1, 3, 5, 10, 20, 40]
  - 0 = HOLD
  - [1, 3, 5, 10, 20, 40] map to widths [1, 3, 5, 10, 20, 40] (in tick_spacing units)
- **Total actions**: 7

## Training Configuration

| Parameter | PPO | DQN | LSTM DQN |
|-----------|-----|-----|----------|
| Episodes/Timesteps | 200,000 ts | 500 ep | 800 ep |
| LSTM Seq Length | - | - | 24 |
| Device | cpu | cpu | cpu |
| Eval Episodes | 10 | 10 | 10 |

## Environment Settings (Unchanged)
- **Fee model**: Exact per-swap (paper method)
- **Gas cost**: $0.02 per rebalance (Arbitrum L2)
- **Initial position**: 2.0 ETH
- **Pool**: ETH/USDC 0.05% (tick_spacing=10)

## Results

### Baselines
- **hold**: 0.00 +/- 0.00
- **fixed_width_1**: 244.67 +/- 0.00
- **fixed_width_5**: 155.59 +/- 0.00
- **fixed_width_10**: 25.50 +/- 0.00

### Algorithms
- **ppo**: 215.80 +/- 4.86
  - PPO actions: HOLD:22, W=1:2921, W=3:1715, W=5:428, W=10:177, W=20:1515, W=40:22
- **dqn**: 223.56 +/- 0.00
- **lstm_dqn**: 217.14 +/- 0.00
  - See "Actions in plain English" below for breakdown.

## Actions in plain English

**PPO** (6 actions):
- **HOLD** = do nothing, keep current LP range (no gas).
- **W=1** = set range width to ±1 tick_spacing (~0.1%), centered at current price.
- **W=3** = ±3 tick_spacings (~0.3%), centered.
- **W=5** = ±5 (~0.5%), centered.
- **W=10** = ±10 (~1%), centered.
- **W=20** = ±20 (~2%), centered.
- **W=40** = ±40 (~4%), centered.
Each non-HOLD action recenters the range at current price and costs gas ($0.02).

**DQN / LSTM** (7 actions):
- Same as PPO: HOLD + width=1,3,5,10,20,40, always centered.

**Important:** Both "Plotted trajectory" and "Eval (10 ep)" use the **same test period** (same dates). Plotted = 1 run through that period (what you see in the viz). Eval (10 ep) = 10 runs through the same period, aggregated.

**Viz panels:** In the plots, each panel is one model. PPO panel shows PPO's HOLD/rebalance counts (e.g. 785 HOLDs). DQN panel shows DQN's (often 0 HOLDs). LSTM panel shows LSTM's. The numbers in "Plotted trajectory" below match the panel for that model.

**Plotted trajectory (what you see in the viz)**

**ppo**
- **W=1**: 303 steps (44.6%)
- **W=3**: 261 steps (38.4%)
- **W=5**: 40 steps (5.9%)
- **W=10**: 18 steps (2.6%)
- **W=20**: 37 steps (5.4%)
- **W=40**: 21 steps (3.1%)

**dqn**
  - **HOLD**: 92 steps (13.5%)
  - **width=1**: 434 steps (63.8%)
  - **width=3**: 107 steps (15.7%)
  - **width=5**: 5 steps (0.7%)
  - **width=10**: 41 steps (6.0%)
  - **width=40**: 1 steps (0.1%)

**lstm_dqn**
  - **HOLD**: 212 steps (31.2%)
  - **width=1**: 437 steps (64.3%)
  - **width=3**: 23 steps (3.4%)
  - **width=5**: 7 steps (1.0%)
  - **width=10**: 1 steps (0.1%)

**Eval (10 episodes, aggregate)**

**ppo**
- **HOLD**: 22 steps (0.3%)
- **W=1**: 2921 steps (43.0%)
- **W=3**: 1715 steps (25.2%)
- **W=5**: 428 steps (6.3%)
- **W=10**: 177 steps (2.6%)
- **W=20**: 1515 steps (22.3%)
- **W=40**: 22 steps (0.3%)

**lstm_dqn**
  - **HOLD**: 2120 steps (31.2%)
  - **width=1**: 4370 steps (64.3%)
  - **width=3**: 230 steps (3.4%)
  - **width=5**: 70 steps (1.0%)
  - **width=10**: 10 steps (0.1%)


## PnL: $100 invested at test start

| Model | Plotted cum (USD) | Plotted return% | Plotted end $100 | Mean cum (10 ep) | Mean return% | Mean end $100 |
|-------|-------------------|-----------------|-------------------|------------------|---------------|------------------|
| ppo | 230.25 | 3.45% | $103.45 | 215.80 | 3.23% | $103.23 |
| dqn | 223.56 | 3.35% | $103.35 | 223.56 | 3.35% | $103.35 |
| lstm_dqn | 217.14 | 3.25% | $103.25 | 217.14 | 3.25% | $103.25 |

(Plotted = single trajectory in the viz; Mean = average over 10 eval episodes. Env uses 2 ETH ≈ $6681 at start.)


## Why PPO cumulative reward can dip (e.g. -15301)
- The **plot shows one test trajectory** (one episode). Cumulative reward is step-by-step.
- Each step: reward = fee - LVR - gas (if rebalance) - opportunity_cost (if out of range).
- **LVR** uses the instantaneous formula ℓ = L×σ²/4×√p (Equation 16). In high-volatility hours this can be large and exceed fees, so the step reward is negative.
- Over many such hours the cumulative can drop (e.g. to -15301), then recover when fees dominate again. The **reported mean reward** (e.g. 1170) is over 10 episodes; the plotted trajectory can be one where the curve dips then recovers.

## Key Differences from Previous Runs
- **Width options**: [1,2,5,8,10] (DQN) / [0,1,2,4,10,16,20] (PPO)
  - Added narrowest width=1 (~0.1% range) to both models
  - **Removed offsets** — all positions always centered at current price
  - Simplified action space: DQN 6 actions, PPO 7 actions
- **Bug fixes**: opportunity cost corrected (was 52.6% APY, now 5% APY), swap fee halved (50% of position swapped)
