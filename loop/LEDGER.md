# Experiment ledger

> Append-only index of loop iterations — one row per experiment (E) or review (R); details live in `experiments/`. **A row without a file, or a file without a row, is a bug.**

| ID | Date | Family | Claim (short) | Verdict | File |
|---|---|---|---|---|---|
| E001 | 2026-08-29 | H-model-class | The shipped DQN beats an always-in-W10 recenter rule in its own training env | **REFUTED** | [E001](experiments/E001-baseline-race.md) |
| E002 | 2026-08-29 | Gate-1-instrumentation | The backtest engine can reproduce T4/T5 per cost line within tolerance | **SUPPORTED** | [E002](experiments/E002-gate1-trial-reproduction.md) |
| E003 | 2026-08-29 | H-width | Some always-in width nets ≥ +$0.39/day under honest costs (central envelope) | **REFUTED** (strongest clause: no arm ≥ $0 even optimistic) | [E003](experiments/E003-cost-honest-width-race.md) |
| E004 | 2026-08-29 | Gate-1-instrumentation | Report 01's basket-delta derivation, not the engine's chain read, explains the E002 mismatch | **T5 SUPPORTED · T4 INCONCLUSIVE** (cause located: issue-X boundary) | [E004](experiments/E004-basket-delta-reconciliation.md) |
| E005 | 2026-08-30 | H-pool | Some Arbitrum V3 pool, HL-hedgeable, pays fees/gamma ≥ 1.5 with margin at our size | **INCONCLUSIVE** (watchlist: wstETH/WETH 0.01% fails only the +$0.389/day floor at +$0.22–0.27/day; LINK/WETH 0.05% f/g 1.20 honest-share; all USD-quoted pools 0.63–0.97) | [E005](experiments/E005-pool-screen.md) |
| E006 | 2026-09-02 | H-timing | A perfect-foresight in/out timing policy on ETH/USDC 0.05% clears the target with modelable margin | **SUPPORTED** (stage-2 exact oracle +$6.06/day at ±0.2%, +$3.72 at ±0.5%; 6.4% capture reaches target — but named causal signals separate at AUC ≤ 0.53) | [E006](experiments/E006-timing-oracle-bound.md) |
| E007 | 2026-09-02 | H-timing | Some pre-named causal in/out signal (M001 set) nets ≥ +$0.389/day central via the stage-2 exact simulator, incl. held-out August | **REFUTED** (all 6 candidates negative full-window AND held-out August at both arms; best C6 w10 −$0.074/day; 0/540 tune configs positive; best causal AUC 0.616 — selection without contiguity) | [E007](experiments/E007-causal-signal-test.md) |
| E008 | 2026-09-03 | H-timing | Some pre-named streak-aware rule (M002 set S1–S6: hysteresis / dwell / DP-on-forecast) nets ≥ +$0.389/day central full-window and > $0/day central on held-out August | **REFUTED** (all 6 candidates negative full-window AND held-out August at both arms; best S5 w10 −$0.025/day; 3/404 tune configs positive, all fail August; the contiguity gradient is negative everywhere — H-timing closed, venue retired per operator pre-commitment, B2 activates) | [E008](experiments/E008-streak-aware-rules.md) |
| E009 | 2026-09-03 | H-carry | The wstETH package's +$0.2095/day funding carry is representative out of window: trailing-12m package net ≥ +$0.15/day central and the M003 downside bounds hold over full HL history | **SUPPORTED** (central +$0.186/day, 4.8% APR; every bound holds — worst 30d −$0.086, longest neg run 11d; carry positive in down-trends; 49% of hours pinned at HL's interest floor = 38% of carry; but compressing: 2024H1 +$0.77 → 2026H1 +$0.12/day, and HL's era holds no full bear market — Binance's Merge-2022 30d worst −$0.58/day would breach the bound) | [E009](experiments/E009-funding-persistence.md) |
| E010 | 2026-09-03 | H-pool (capital-param.) | At $10k reference capital some HL-hedgeable venue (mainnet in scope) passes the full E005 gate set (f/g ≥ 1.5 central, > 1.0 monthly, net ≥ 10% APR) — incl. the feeProtocol ×1.33 hypothesis, read on-chain | RUNNING | [E010](experiments/E010-capital-rescreen.md) |

## Closed sub-goals

_None yet._
