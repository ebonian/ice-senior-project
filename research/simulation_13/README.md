# Simulation 13

Clean simulation folder derived from simulation_12 (run_004). Use for final model runs and PnL evaluation.

## Contents

- **Training**: `uniswap_v3_dqn_paper.py`, `uniswap_v3_ppo_paper.py`, `compare_algorithms.py` (same as sim12).
- **Training data**: `training_data/` — pool_config, token_metadata; swap CSV optional (see `training_data/README.md`).
- **Run**: `run_004/` — RUN_CONFIG, visualizations; train with compare_algorithms to produce `run_004/models/`.
- **PnL**: `scripts/compute_pnl.py` — fees + LVR − gas − swap fee cost from downloaded swap data + run_004 model.

## How to run

```bash
# From repo root (or from research/simulation_13)
cd research/simulation_13

# Compare algorithms (uses training_data; ensure swaps CSV or data_dir points to sim12 if needed)
python compare_algorithms.py --data-dir training_data --run-dir run_004 \
  --ppo-timesteps 200000 --dqn-episodes 800 --lstm-episodes 1000

# PnL from downloaded data + run_004 models (default: sim13/run_004/models)
python scripts/compute_pnl.py --model dqn --capital 100
python scripts/compute_pnl.py --model ppo --model-dir run_004/models --gas-cost 0.02

# LSTM 1-week decision visualization (for presentation)
python scripts/visualize_lstm_1week.py --start-date 2026-01-15 --capital 100
# → saves run_004/visualizations/lstm_1week_2026-01-15.png
```

Models: if `run_004/models` is missing, the PnL script falls back to `kongtrae/models`.
