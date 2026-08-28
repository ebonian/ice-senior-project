# `_data_usdt/` — the pool the shipped checkpoint was actually trained on

These are the **ETH/USDT 0.3% (Ethereum mainnet)** exports from `dune_pipeline/`,
copied here under `*_eth_usdc_0p05.csv` filenames.

The filenames are a lie and that is deliberate: the current
`prepare_interval_data` (`simulation_14/training/uniswap_v3_ppo_paper.py:420-429`)
hardcodes the `*_eth_usdc_0p05.csv` glob, but the pool identity comes entirely
from the *contents* of `pool_config_*.csv` (fee, tickSpacing, token addresses),
not from the name. Renaming lets the unmodified snapshot load the USDT pool.

`pool_config` here is `fee=3000, tickSpacing=60`, tokens WETH/USDT mainnet — the
configuration in tree at commit b208379 (2026-04-17 16:25), which is the commit
that added the shipped `dqn_three_head_v3_1h.zip`. The switch to ETH/USDC 0.05%
landed ~10h later in f94b312.

Coverage is one month (2025-09-01 .. 2025-10-01), which is all of this pool that
survives in the repo, and it falls inside the checkpoint's own training span — so
results here are in-sample and only indicative.
