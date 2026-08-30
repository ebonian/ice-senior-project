---
id: E005
family: H-pool
date: 2026-08-30
verdict: RUNNING
---

# E005 — At least one Arbitrum V3 pool we can hedge on Hyperliquid pays its gamma with margin

## Pre-registration (write BEFORE running)

**Hypothesis** — There exists at least one Uniswap V3 pool on Arbitrum, with every
non-stable leg hedgeable by a Hyperliquid perp, for which a fixed-width always-in
delta-hedged LP position at our size clears **fees/gamma ≥ 1.5 (central envelope,
full window)** with **fees/gamma > 1.0 in every calendar month**, and projects
**net ≥ +$0.39/day at $1,420 capital** through the full Gate-1 cost stack.

E003 measured the shortfall on ETH/USDC 0.05% at 1.51–1.74× and found it
near-constant across a 40× width range — a venue property. This experiment asks
whether any reachable venue does not have that property.

**The one variable** — the **venue (pool)**. Everything else is frozen at E003's
values: engine `gate1/engine/` unmodified; cost model `gate1-2026-08-29`; hedge
envelope `e003-2026-08-29` (optimistic 1.984 / central 3.359 / pessimistic 8.320
bps, notional-weighted maker share 64.63%); window **2026-05-01 → 2026-08-28 UTC**;
LP notional **$1,015 constant re-mint** from $1,420 capital (E003 §6 convention);
primary loop **lag1h_rh1h** (E003 §7's most realistic), recenter-only rehedge as
sensitivity. Baseline: ETH/USDC 0.05% (`0xC6962004…`), the control row.

**Candidate set** — four pre-registered families; the agent verifies existence via
the factory and records every screened-out candidate with its reason (never a
silent drop):

| Family | Mechanism that could move fees/gamma | Candidates |
|---|---|---|
| F1 same pair, higher tier | 6× gross fee per unit volume | WETH/USDC 0.30% |
| F2 correlated volatile pair | gamma ∝ *relative* variance of the pair (vol²) | WBTC/WETH 0.05%, WBTC/WETH 0.30% |
| F3 ultra-correlated | near-zero relative vol → near-zero gamma | wstETH/WETH 0.01% (alt: weETH/WETH 0.01%) |
| F4 retail flow | uninformed flow pays fees without matched variance | ARB/WETH 0.05%, ARB/WETH 0.30%, + up to 2 discovered |

F4 discovery rule (pre-stated): among tokens with a live HL perp, the top V3
Arbitrum pools by swap count over the window, excluding pools already listed and
stable/stable pairs.

**Eligibility gates per pool** (validity, not verdict):
- Pool exists on the Arbitrum V3 factory and has median ≥ 48 swaps/day over the
  window — thinner pools are marked `INELIGIBLE-thin`, not raced.
- Every non-stable leg has a Hyperliquid perp. Pre-registered exception: wstETH /
  weETH count as ETH-beta and hedge with the ETH perp (near-static full-notional
  short).
- Effective LP fee = tier × (1 − protocol share) read from the pool's
  `slot0().feeProtocol` **and** checked for `SetFeeProtocol` events over the
  window; a mid-window change applies piecewise. (Issue W: assuming 100% of the
  tier once overstated our fee income by 1.333×.)
- Data must pass the E003 coverage gates (chunk tiling, hourly floor, independent
  refetch, timestamp interpolation) generalized per pool; failure → `DATA-FAIL`,
  not a silent drop.

**Metric definitions (frozen)** —
- **fees/gamma** = LP fees accrued to the position (gate1 `fee_engine`,
  protocol-fee-correct) ÷ |hedged gamma|, where hedged gamma =
  `lp_value_change + hedge_price_pnl` on the 1h grid in USD (E003 §2 definition).
- Two-volatile-leg pools short each leg's token delta on its own perp; USD marks
  from Binance 1h closes (HL mid where Binance lacks the pair). Funding from the
  HL public funding-history API per perp, archived to CSV.
- Width arms per pool: **±0.1%, ±0.2%, ±0.5%, ±2.0%, ±8.3%** (percentage widths
  are comparable across pools; the narrow arms exist for F3, the wide for F1/F2).

**Engine-extension validity gate** — any code added for multi-leg hedging or new
pools lives under `e005/`, imports the frozen constants, and must first
**reproduce E003's ETH/USDC 0.05% control row within ±0.05 on fees/gamma and ±5%
on net $/day at matching arms**. Candidate numbers are not quotable until the
control reproduces.

**Decision rule** —
- **SUPPORTED**: ≥ 1 pool × arm passes ALL of:
  (a) fees/gamma ≥ 1.5 central, full window;
  (b) fees/gamma > 1.0 central in every calendar month;
  (c) net ≥ +$0.39/day central at $1,420 through the full cost stack;
  (d) our implied in-range liquidity share ≤ 1% (fee-credit honesty, E003 §3);
  (e) volume persistence — no month's swap count < 25% of that pool's peak month
  (incentive-cliff guard).
  Passing pools become the **candidate venue list**, ranked by central net $/day.
- **REFUTED**: no eligible pool reaches **fees/gamma ≥ 1.0 central** over the full
  window. G-pool then closes negative for the Arbitrum-V3 × HL-hedgeable set at
  this size, and the loop ESCALATES the structural conversation (larger capital,
  different strategy family, or stop).
- **INCONCLUSIVE**: pools land between 1.0 and 1.5 central or fail only secondary
  gates → a named watchlist; disambiguated by a longer window or per-pool cost
  calibration.

**Scope limit (pre-registered)** — Arbitrum only this pass: the frozen on-chain
cost constants are Arbitrum-calibrated. Mainnet/Base screens would need
recalibrated gas constants and are a follow-up experiment, not a silent extension.

**Abort criteria** — > half the candidate set DATA-FAILs (infra problem — report,
don't judge); or serial fetch projects > 36 h, in which case run priority is
F1 → F3 → F2 → F4 and cut candidates are named in the report.

**Method** — RPC `eth_getLogs` on public `arb1.arbitrum.io/rpc` (phased,
checkpointed, resumable — E003's `fetch_months.py` generalized; sparse pools may
use larger chunk spans); artifacts under `backtest_model_server/e005/`; per-pool
parquets gitignored and re-derivable from committed block ranges + anchors +
sha256; funding CSVs committed. Deterministic replay, no RNG.

## Result

_(pending)_

## Verdict

RUNNING

## Critique

_(pending)_

## What this changes

_(pending — SUPPORTED routes to a venue proposal for the operator + G2 unblocks
on the winning pool; REFUTED closes G-pool for this venue set and escalates.)_
