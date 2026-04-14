# Simulation 13 – Training Data

| File | Description |
|------|-------------|
| `swaps_20250504_to_20260212_eth_usdc_0p05.csv` | Concatenated swap data (May 4, 2025 – Feb 12, 2026); same format as sim12 |
| `pool_config_eth_usdc_0p05.csv` | Fee=500 (0.05%), tickSpacing=10 (ETH/USDC, Arbitrum) |
| `token_metadata_eth_usdc_0p05.csv` | WETH (18 dec) / USDC (6 dec) |

**Regenerating the swaps CSV** (from `downloaded_data_csv/daily/swaps`):

```bash
python research/simulation_13/scripts/concat_swaps_to_training_data.py
```
