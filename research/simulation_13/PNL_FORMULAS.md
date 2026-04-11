# PnL Formula Compliance (sim13)

This document confirms that the PnL script (`scripts/compute_pnl.py`) uses the same definitions as the repo’s training environments and standard quant/Uniswap conventions.

**Compliance with Uniswap (GitHub v3-core):** Fee share (`agent_fee = fee_usd × (agent_L / pool_L)`), liquidity/position value formulas, and tick/price math align with [Uniswap/v3-core](https://github.com/Uniswap/v3-core) (e.g. `UniswapV3Pool.sol` fee accrual and concentrated liquidity invariants).

---

## 1. Gross fee (LP fee share)

**Formula (per swap, in range):**
```text
agent_fee = fee_usd × (agent_L / pool_L)
```

**Source / compliance:**
- **Uniswap V3 (on-chain):** Fee accrual is per unit of liquidity. From `UniswapV3Pool.sol`: `feeGrowthGlobal += feeAmount * Q128 / liquidity`. So each LP’s share of a swap’s fee is proportional to their liquidity in range: `fee_earned = fee_amount × (L_position / L_active_at_swap)`. Our `agent_L` is the agent’s liquidity (in on-chain units) at that swap’s price; `pool_L` is the active liquidity at the swap (from the swap row). So the formula matches the contract logic.
- **Repo:** Same formula in `compute_real_fees.py`, `compute_fees_from_downloaded_data.py`, and in the env’s fee computation (share of pool fees by L).

**Real-world:** Standard Uniswap V3 LP fee = (position liquidity / active liquidity at swap) × swap fee. ✓

---

## 2. LVR (Loss-Versus-Rebalancing)

**Formula (discrete, per swap, in range):**
```text
LVR = Σ_i { V(p_{i+1}) − V(p_i) − x(p_i) × (p_{i+1} − p_i) }
```
- `V(p)` = position value (in USD) at price `p` for the agent’s range `[p_lower, p_upper]`.
- `x(p)` = amount of token0 (e.g. ETH) in the position at price `p`.
- Sum over consecutive swap prices within each hour; only include swaps whose price is in range (we clamp `p_i`, `p_{i+1}` to `[p_lower, p_upper]` for in-range segments).

**Source / compliance:**
- **Zhang et al. (2023) / LVR literature:** Discrete LVR is the difference between the LP’s mark-to-market value change and the “rebalancing” (delta-hedge) PnL: `ΔV − x Δp`. Summing over each trade gives the total LVR. It is a cost to the LP (LVR ≤ 0 in practice). Our formula is exactly that.
- **Repo:** Same formula in `uniswap_v3_dqn_paper._compute_lvr()` and `uniswap_v3_ppo_paper._compute_lvr()`: “LVR = Σ { V(p_{i+1}) - V(p_i) - x(p_i) × (p_{i+1} - p_i) }” (paper Equation 5). The PnL script uses the same `position_value_at` and `x_at_price` helpers and the same per-swap sum.

**Real-world:** Standard discrete LVR = value change minus delta-hedge term; our implementation is consistent with that. ✓

### LVR vs IL (impermanent loss) – what we include

| Term | Meaning | In PnL? |
|------|--------|--------|
| **LVR** | Loss from adverse selection **while in range** (price moves through your range; arbitrageurs trade against you). | ✓ Yes – we sum Σ(ΔV − x Δp) over in-range swaps. |
| **IL (in-range)** | Often same idea as LVR: “impermanent loss” from providing liquidity when price moves. | ✓ Yes – captured by LVR. |
| **Slippage** | Execution cost **on the rebalance swap** (your trade moves the price, worse fill). | ✓ Yes – use `--slippage-per-rebalance`. |
| **IL (out-of-range)** | When price **leaves** the range you’re 100% in one asset; the “loss” vs being in range or holding the mix is **opportunity cost**. | Optional – use `--out-of-range-opportunity-apy` (e.g. 0.05 for 5%) to include it. |

So: we have **LVR** (in-range IL-like cost), **slippage** (rebalance execution), and optionally **out-of-range opportunity cost** (IL when stuck in one asset). Narrow ranges → more time out of range → that opportunity cost matters; the script can now subtract it if you pass the flag.

### Out-of-range: position value drop (real IL) vs cumulative reward

When price **moves out of range and does not come back**, the position is 100% in one asset. If that asset’s price then moves against you (e.g. you’re stuck in ETH and ETH dumps), **position value falls** — that’s real loss of value vs initial capital (IL).

- **Cumulative reward** in the env (and in the 1-week LSTM plot) = sum of step rewards: fees + LVR − gas − swap fee − optional opportunity cost. It does **not** include the **mark-to-market change in position value** when out of range.
- So when price leaves range and doesn’t come back, the **plotted “Cumulative PnL” can be optimistic**: it shows fee-related PnL but not the drop in position value. The **Position value** panel in the 1-week viz shows that explicitly (value vs initial capital); the gap below the dashed line is the IL from being out of range.

**Total economic PnL** (if you want it) = (position value at end − initial capital) + cumulative fees received − gas − swap fees; or equivalently, track position value over time — when it goes below initial capital, that’s the IL you’re seeing.

**`total_value` in env info:** The env reports **net** cash-out value: `total_value = position_value + accumulated_fees − accumulated_costs` (gas and swap paid so far). So the “Total money” curve = what you have after paying gas/swap (and matches initial + cumulative reward).

**Rebalance compounds (position + fees − costs):** When we rebalance, we deploy **total money** = position value + accumulated fees − accumulated costs, then pay gas and swap from that; the rest is the new position size. So we **compound** fees into the next position. First deploy uses initial capital; every later rebalance uses (position + fees − costs), minus gas and swap for that step.

**Reward function (env):** The training envs (DQN and PPO) use step reward = **total_value_after − total_value_before − opportunity_cost**, where total_value = position_value + accumulated_fees − accumulated_costs. This equals fee + (position_value_after − position_value_before) − gas − swap − opportunity when rebalancing (gas and swap are subtracted via accumulated_costs), so the agent correctly learns that rebalancing is costly and HOLD is preferred when the current position is acceptable. LVR is embedded in the position value change when in range. So the agent sees: (1) fee income, (2) mark-to-market change (in-range LVR effect and, when OOR, full IL when price moves). Thus “positive cumulative fee PnL but lose money in the end” (OOR IL) produces negative step rewards when value drops, and cumulative reward aligns with total money at exit (minus gas/swap), so the policy is trained to maximize what you get when you cash out.

---

## 3. Gas cost

**Formula:**
```text
total_gas_cost = rebalance_count × gas_cost_per_rebalance
```

**Source / compliance:**
- **Repo:** Training envs use reward = total_value_after − total_value_before, so gas and swap are implicitly subtracted when rebalancing (they increase accumulated_costs, reducing total_value). PnL script counts “rebalance” as every non-HOLD action (same as env) and multiplies by a configurable `--gas-cost` (default $0.02 for L2).
- **Real-world:** Gas is a fixed cost per transaction; we use one rebalance = one tx. L2 (e.g. Arbitrum) ~$0.02–0.05, mainnet ~$0.50+. ✓

---

## 4. Rebalance cost (swap fee cost)

**Formula:**
```text
swap_fee_cost = 0.5 × pool_fee_rate × capital × rebalance_count
```
- `pool_fee_rate` = pool fee in decimal (e.g. 0.0005 for 0.05%).
- `capital` = agent’s position size (e.g. $100).

**Source / compliance:**
- **Repo:** In `uniswap_v3_dqn_paper.step()` (and PPO): “Swap fee cost: ~50% of position needs swapping during rebalance (heuristic)”: `swap_fee_cost = 0.5 * swap_fee_rate * initial_capital` per rebalance. So total = `0.5 × pool_fee × capital × rebalance_count`, which is what the PnL script uses.
- **Real-world:** On rebalance you swap part of your position through the AMM and pay the pool fee. The 50% is a conservative heuristic for “average fraction of position swapped per rebalance”; the exact fraction depends on width change and price. ✓

### What we do **not** include: slippage / price impact on rebalance

When you rebalance you (1) burn the old position, (2) swap one side to the other through the AMM, (3) mint a new position. That swap has:
- **Pool fee** (0.05% etc.) → we include this via the 50% heuristic above. ✓  
- **Slippage / price impact** (the trade moves the price, so you get a worse average fill) → we do **not** include this in the reward function or PnL. So rebalance cost in our model is a **lower bound**; real cost can be higher for larger sizes or thin pools.

**Reference – Llaminet rebalance cost eval (Arbitrum fork):** For $100 position, total rebalance cost ≈ **$0.044** per rebalance (Gas ≈ $0.018, SwapFees ≈ $0.027). So ~$0.02 gas + ~$0.025 swap fees matches our default; their total does not explicitly add slippage. For small sizes on L2, slippage is often negligible. You can pass `--rebalance-total-cost 0.044` (per rebalance) to align PnL with that eval instead of separate gas + swap fee.

**Should you include slippage?** Yes, if you want PnL to reflect real money. The rebalance swap does move the price (you get a worse fill), so you lose something. For small size ($100) on a deep pool it may be tiny; for larger size or thin pools it matters. Use `--slippage-per-rebalance 0.005` (e.g. half a cent) or a bps of notional if you have an estimate, so net PnL is closer to what you’d actually get.

---

## 5. Net PnL

**Formula:**
```text
net_pnl = gross_fees + LVR − total_gas_cost − swap_fee_cost
```

**Convention:** LVR is stored and reported as a negative number (cost), so we add it (e.g. `total_lvr = -148` → add −148 in the formula). Same as training reward: `reward = fee + lvr - gas - swap_fee_cost` (with `lvr ≤ 0`).

**Repo:** Matches `compare_algorithms.py` and env reward definition: “reward = fee + LVR − gas (if rebalance) − swap_fee_cost”. ✓

---

## Summary

| Term            | Formula / definition                                      | Matches repo env | In PnL script |
|-----------------|-----------------------------------------------------------|------------------|----------------|
| Gross fee      | `fee_usd × (agent_L / pool_L)` per in-range swap          | ✓                | ✓              |
| LVR (in-range IL) | Σ (ΔV − x Δp) per swap, in range                        | ✓ (Eq. 5)        | ✓              |
| Gas cost       | `rebalance_count × gas_cost`                             | ✓                | ✓              |
| Rebalance cost | gas + swap fee (or `--rebalance-total-cost`)             | ✓                | ✓              |
| Slippage       | $ per rebalance (execution cost)                         | no               | `--slippage-per-rebalance` |
| Out-of-range IL | opportunity cost when price outside range                | ✓ (env 5% APY)   | `--out-of-range-opportunity-apy` |
| Net PnL        | fees + LVR − rebalance_cost − slippage − out_of_range_cost | ✓                | ✓              |

---

## Real-world LP compliance (simulation vs reality)

The env models a real LP providing liquidity. The following checks ensure behavior matches reality:

| Scenario | Real behavior | Env behavior |
|----------|---------------|---------------|
| **Bankrupt (total_value ≤ 0)** | LP stops; can't keep acting | Episode terminates immediately ✓ |
| **Insufficient funds to rebalance** | Tx would fail (can't pay gas) | Rebalance treated as HOLD; no cost charged ✓ |
| **HOLD** | No gas; keep position; earn fees | No gas; fees accrue ✓ |
| **Rebalance** | Pay gas + swap fee; deploy remainder | Pay gas + swap; invest_amount = total − gas − swap ✓ |
| **No position** | LP holds cash (value = capital) | position_value = initial_capital ✓ |
| **Fee share** | our_fee = pool_fee × (our_L / pool_L) | Same; our_L in on-chain units ✓ |
| **Position value** | Uniswap V3 concentrated liquidity | Same formulas ✓ |
| **LVR** | In position value change when in range | Embedded in (V_after − V_before) ✓ |

**Simplifications (not in env):**

- **Slippage:** Rebalance swap has price impact; we use 50% heuristic for swap fee only. Add `--slippage-per-rebalance` in PnL script for evaluation.
- **Gas variance:** Fixed gas per rebalance; real gas fluctuates.
- **Min position size:** We allow tiny positions (1e-6 floor); real pools may have dust limits.

---

## Data sources: real-world Uniswap pool API

All **pool and swap data** needed for fees and LVR can be obtained from standard Uniswap V3 data sources (subgraph, RPC, or indexed swap CSVs). The table below maps each input to where it comes from.

| What we need | Used for | Real-world source |
|--------------|----------|-------------------|
| **Per-swap: `amount0`, `amount1`** | Fee amount (fee = amount × fee/(1−fee)); price | Uniswap V3 **Swap** event / subgraph `swap.amount0`, `amount1` |
| **Per-swap: `liquidity`** | Active liquidity at swap (pool_L in fee share) | Uniswap V3 **Swap** event / subgraph `swap.liquidity` (or slot0 / tick liquidity at that tick) |
| **Per-swap: `tick`** | In-range check; price | **Swap** event `tick` (current tick after swap) |
| **Per-swap: `sqrtPriceX96`** | Price for fee USD and LVR price path | **Swap** event `sqrtPriceX96` |
| **Per-swap: `timestamp`** (block time) | Order of swaps; hourly grouping | Block timestamp or **Swap** event `blockTimestamp` |
| **Pool: `fee` (e.g. 500 = 0.05%)** | Fee rate for fee_usd and rebalance cost | Pool contract / **Pool** entity: `feeTier` or config |
| **Pool: `tickSpacing`** | Range math; agent L | Pool contract / **Pool** entity |
| **Token decimals** | amount0/amount1 → USD | Token contract or **Token** entity (e.g. subgraph) |

So in practice:

- **Swaps:** Use the Uniswap V3 subgraph (e.g. `swaps` query for a pool by `pool.id`), or index **Swap(address,address,int24,int256,int256,uint160,uint128,int24)** events from the pool contract. Each event gives `amount0`, `amount1`, `sqrtPriceX96`, `liquidity`, `tick`; block timestamp gives ordering. That is enough for gross fee and LVR.
- **Pool config:** From the pool contract or subgraph **Pool** (fee tier, tickSpacing, token0, token1). Token decimals from token contracts or **Token** in the subgraph.

**Not from the pool API (external inputs):**

- **Gas cost:** Chain/network (gas price × gas used for a rebalance tx); e.g. from an RPC or gas oracle, not from the pool.
- **Rebalance count:** Comes from your **strategy/model** (how often you rebalance); the pool API only provides swap history.
- **Agent position (center, width) and capital:** Your **strategy** and sizing; we then compute agent_L from pool math (same formulas as the contract).

So yes: everything needed for **fees and LVR** is available from real-world Uniswap pool data (subgraph or on-chain events). Gas and rebalance count are strategy/network inputs, not pool API.
