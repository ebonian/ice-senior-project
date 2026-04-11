# How to Explain This Project to Your Professor

Use this for your presentation, report, or thesis defense. Adjust wording to your style.

---

## 1. Elevator pitch (30 seconds)

**“I’m using deep reinforcement learning to learn when and how to provide liquidity on Uniswap V3. The agent chooses whether to hold its current position or rebalance to a new price range each hour. It is rewarded for fees earned minus gas, swap costs, and the loss from adverse selection (LVR). We train with DQN and PPO on real swap data and evaluate PnL with the same formulas as the chain.”**

---

## 2. Problem and approach

- **Problem:** In Uniswap V3, LPs choose a price range. Narrow ranges earn more fees when in range but go “out of range” when price moves, and rebalancing costs gas and swap fees. So the LP must trade off fee income, rebalance cost, and risk of being out of range.
- **Approach:** We model this as a **Markov decision process**: each hour the agent sees price and technical features and chooses an action (HOLD or deploy a new range of a given width, centered at current price). We use **DQN** (value-based) and **PPO** (policy gradient) and train on historical swap data. Fee and position value are computed with the same math as Uniswap (concentrated liquidity, fee share by liquidity).

---

## 3. Reward and “total money” (what the agent maximizes)

- **Step reward** (what the agent gets each hour):
  - **+ Fees** earned that hour (our share of pool fees = fee × our_L / pool_L, in on-chain liquidity units).
  - **+ Change in position value** (mark-to-market: value at end of hour − value at start). This already includes the loss from adverse selection (LVR) when price moves through the range.
  - **− Gas** (fixed cost per rebalance).
  - **− Swap fee cost** (we pay the pool fee on the rebalance swap; we use a 50% heuristic of position size).
  - **− Opportunity cost** when out of range (small penalty so the agent prefers being in range).

- **Total money (net of costs)** = what you have if you cash out:
  - **Position value** (current value of the LP position) **+ accumulated fees − gas − swap costs**.
  - This is the green curve in the 1-week plots. The agent is trained to maximize this over time.

- **“Initial + cumulative reward”** (purple dashed line) = initial capital + sum of step rewards. It equals total money minus any out-of-range opportunity cost we penalized. So the two curves are almost the same; the difference is just that penalty.

---

## 4. Fee share (why we use “on-chain” liquidity)

- On Uniswap V3, **your fee share** for a swap = (your liquidity in range) / (total pool liquidity in range) at that moment. So we need **our L and pool L in the same units** (the chain’s liquidity units).
- We **don’t** use a simplified “simulation” liquidity that’s in different units; we compute **our L in on-chain units** with the same formula as the chain (token decimals, tick bounds, value-per-L in raw units). Then: **our fee = pool fee × (our_L_onchain / pool_L)**. Pool L comes from the swap CSV (chain data). This matches the contract and our PnL script.

---

## 5. LVR (loss versus rebalancing)

- **LVR** is the loss to the LP from adverse selection: when price moves through your range, arbitrageurs trade against you. Formally (discrete form): for each price move, LVR = (change in position value) − (delta-hedge PnL) = ΔV − x·Δp. We sum this over every swap in range. It’s already included in the **position value change** in the reward, so we don’t add LVR separately; the agent sees the real mark-to-market effect.

---

## 6. What we evaluate

- **Training:** Episodes (DQN/LSTM) or timesteps (PPO) on train/val split; we log reward and total value.
- **Test:** We run the trained policy on a held-out test period and plot (1) price and LP ranges, (2) actions, (3) step reward, (4) **total money** (position + fees − costs) vs initial capital.
- **PnL script:** For a given model and capital, we replay decisions on **downloaded swap data**, compute fees with **agent_L / pool_L** (on-chain), add LVR, subtract gas and swap fee cost. So we get a single “real-world style” PnL number consistent with the env.

---

## 7. Likely professor questions — short answers

| Question | Answer |
|----------|--------|
| **What is the state / action space?** | State: technical indicators (e.g. volatility, RSI, MAs) + position info (width, in-range, value ratio). Action: discrete — HOLD or 5 range widths (e.g. ±1 to ±40 ticks), always centered at current price. |
| **Why DQN and PPO?** | DQN from Zhang et al. (2023) for Uniswap V3 LP; we add PPO and LSTM-DQN for comparison. Same env and reward so we can compare sample efficiency and stability. |
| **Where does the data come from?** | Historical swap data (prices, volumes, pool liquidity) from the pool; we resample to hourly and build technical features. Train/val/test split by time. |
| **How do you know the reward is correct?** | Fee share and position value formulas match Uniswap v3-core and the PnL literature (e.g. Zhang et al.). We use one shared on-chain L formula everywhere (env and PnL script). See `PNL_FORMULAS.md`. |
| **What is “total money” vs “cumulative reward”?** | Total money = position value + fees − costs (actual cash-out value). Cumulative reward = sum of step rewards; it equals total money minus the small out-of-range opportunity cost we subtract in the reward. So they’re the same economically; the plot shows both. |
| **What’s next?** | (You can say: more pools, real execution backtests, or risk constraints.) |

---

## 8. One slide / one figure

If you only show one thing: the **1-week visualization** (e.g. `run_007/visualizations/dqn_1week_2026-01-15.png`): price, LP ranges over time, actions (HOLD vs rebalance), step reward, and **total money (green)** vs initial capital. That shows “the agent chose these ranges and this is the resulting PnL after costs.”

Good luck with your presentation.
