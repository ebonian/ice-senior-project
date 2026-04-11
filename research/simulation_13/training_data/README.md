# Simulation 13 – Training Data

| File | Description |
|------|-------------|
| `swaps_20250504_to_20260212_eth_usdt_0p3.csv` | Concatenated swap data (May 4, 2025 – Feb 12, 2026); same format as sim12 |
| `pool_config_eth_usdt_0p3.csv` | Fee=500 (0.05%), tickSpacing=10 (ETH/USDT) |
| `token_metadata_eth_usdt_0p3.csv` | WETH (18 dec) / USDT (6 dec) |

**Regenerating the swaps CSV** (from `downloaded_data_csv/daily/swaps`):

```bash
python research/simulation_13/scripts/concat_swaps_to_training_data.py
```
